"""
Read-only Polygon wallet USD value lookup.

Fetches USDC.e and pUSD balances via JSON-RPC balanceOf calls.
Both tokens are USD-pegged stablecoins, so balance == USD value directly.
No price API or API key required.

Tries each RPC in _FALLBACK_RPCS in order until one succeeds.

Environment variables (optional):
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

# USD-pegged stablecoins on Polygon — (contract_address, decimals)
# Balance in token units == USD value; no price conversion needed.
_STABLE_TOKENS = {
    "USDC.e": ("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174", 6),
    "pUSD":   ("0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB", 6),
}

_BALANCE_OF = "0x70a08231"  # balanceOf(address) selector


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


def _token_balance(contract: str, decimals: int, wallet: str, rpc_url: str) -> float:
    """Call balanceOf(wallet) on a USD-pegged ERC-20 and return the USD amount."""
    padded = wallet.lower().replace("0x", "").zfill(64)
    hex_val = _rpc("eth_call", [{"to": contract, "data": _BALANCE_OF + padded}, "latest"], rpc_url)
    if not hex_val or hex_val == "0x":
        return 0.0
    return int(hex_val, 16) / 10**decimals


def _rpc_list() -> list[str]:
    env = os.getenv("POLYGON_RPC_URL")
    return ([env] if env else []) + _FALLBACK_RPCS


def fetch_wallet_usd_value(address: str) -> float:
    """
    Return combined USD value of USDC.e + pUSD in a Polygon wallet.

    Tries each RPC in order until one succeeds.
    Raises WalletLookupError only if all RPCs fail.
    Never requests private keys or wallet permissions.
    """
    last_error: WalletLookupError | None = None

    for rpc_url in _rpc_list():
        try:
            total = sum(
                _token_balance(contract, decimals, address, rpc_url)
                for contract, decimals in _STABLE_TOKENS.values()
            )
            return round(total, 2)
        except WalletLookupError as exc:
            last_error = exc
            continue

    raise WalletLookupError(
        f"All Polygon RPCs failed. Try entering the value manually. "
        f"Last error: {last_error}"
    )
