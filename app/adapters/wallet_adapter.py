"""
Read-only Polygon wallet value lookup.

Fetches native MATIC balance via public JSON-RPC and USDC balances via
direct contract calls — no API key required. Converts MATIC to USD via
CoinGecko.

Tries each RPC in _FALLBACK_RPCS in order until one succeeds.

Environment variables (all optional):
  POLYGON_RPC_URL  — prepended to the fallback list if set

Safety: read-only only. No private keys, signatures, or transactions.
"""

import os

import requests

_FALLBACK_RPCS = [
    "https://polygon.drpc.org",
    "https://poly.api.pocket.network",
    "https://polygon-bor-rpc.publicnode.com",
    "https://1rpc.io/matic",
]

_COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
_MATIC_DECIMALS = 18
_USDC_DECIMALS = 6

# Both USDC variants present on Polygon (native + bridged)
_USDC_CONTRACTS = [
    "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",  # Native USDC
    "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",  # USDC.e (bridged)
]


class WalletLookupError(Exception):
    pass


def _rpc(method: str, params: list, rpc_url: str) -> str:
    try:
        resp = requests.post(
            rpc_url,
            json={"jsonrpc": "2.0", "method": method, "params": params, "id": 1},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise WalletLookupError(f"Network error: {exc}") from exc
    data = resp.json()
    if "error" in data:
        raise WalletLookupError(f"RPC error: {data['error']}")
    return data.get("result", "0x0")


def _matic_balance(address: str, rpc_url: str) -> float:
    hex_val = _rpc("eth_getBalance", [address, "latest"], rpc_url)
    return int(hex_val, 16) / 10**_MATIC_DECIMALS


def _usdc_balance(contract: str, address: str, rpc_url: str) -> float:
    # Call balanceOf(address) — selector 0x70a08231
    padded = address.lower().replace("0x", "").zfill(64)
    data = "0x70a08231" + padded
    hex_val = _rpc("eth_call", [{"to": contract, "data": data}, "latest"], rpc_url)
    if not hex_val or hex_val == "0x":
        return 0.0
    return int(hex_val, 16) / 10**_USDC_DECIMALS


def _matic_usd_price() -> float:
    try:
        resp = requests.get(
            _COINGECKO_URL,
            params={"ids": "matic-network", "vs_currencies": "usd"},
            timeout=10,
        )
        resp.raise_for_status()
        return float(resp.json()["matic-network"]["usd"])
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise WalletLookupError(f"Price fetch failed: {exc}") from exc


def _rpc_list() -> list[str]:
    """Build ordered RPC list: env override first, then public fallbacks."""
    env = os.getenv("POLYGON_RPC_URL")
    return ([env] if env else []) + _FALLBACK_RPCS


def fetch_wallet_usd_value(address: str) -> float:
    """
    Return estimated USD value of a Polygon wallet (MATIC + USDC).

    Tries each RPC in _FALLBACK_RPCS in order until one succeeds.
    Raises WalletLookupError only if all RPCs fail.
    Never requests private keys or wallet permissions.
    """
    last_error: WalletLookupError | None = None

    for rpc_url in _rpc_list():
        try:
            matic = _matic_balance(address, rpc_url)
            matic_price = _matic_usd_price()
            usdc = sum(_usdc_balance(c, address, rpc_url) for c in _USDC_CONTRACTS)
            return round(matic * matic_price + usdc, 2)
        except WalletLookupError as exc:
            last_error = exc
            continue

    raise WalletLookupError(
        f"All Polygon RPCs failed. Try entering the value manually. "
        f"Last error: {last_error}"
    )
