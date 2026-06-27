"""
Tests for wallet_adapter.py.
All tests use mocked network calls — no real internet access required.
"""

from unittest.mock import MagicMock, call, patch

import pytest
import requests

from app.adapters.wallet_adapter import (
    WalletLookupError,
    fetch_wallet_usd_value,
    _matic_balance,
    _usdc_balance,
    _matic_usd_price,
)

_FAKE_ADDRESS = "0x" + "a" * 40
_RPC_URL = "https://polygon-rpc.com"


def _rpc_mock(hex_result: str) -> MagicMock:
    m = MagicMock()
    m.raise_for_status.return_value = None
    m.json.return_value = {"jsonrpc": "2.0", "result": hex_result, "id": 1}
    return m


def _price_mock(price: float) -> MagicMock:
    m = MagicMock()
    m.raise_for_status.return_value = None
    m.json.return_value = {"matic-network": {"usd": price}}
    return m


class TestMaticBalance:
    def test_converts_hex_to_matic(self):
        # 2 * 10^18 wei = 2.0 MATIC
        hex_2_matic = hex(2 * 10**18)
        with patch("requests.post", return_value=_rpc_mock(hex_2_matic)):
            result = _matic_balance(_FAKE_ADDRESS, _RPC_URL)
        assert result == pytest.approx(2.0)

    def test_network_error_raises(self):
        with patch("requests.post", side_effect=requests.RequestException("timeout")):
            with pytest.raises(WalletLookupError, match="Network error"):
                _matic_balance(_FAKE_ADDRESS, _RPC_URL)

    def test_rpc_error_in_response_raises(self):
        m = MagicMock()
        m.raise_for_status.return_value = None
        m.json.return_value = {"jsonrpc": "2.0", "error": {"message": "bad"}, "id": 1}
        with patch("requests.post", return_value=m):
            with pytest.raises(WalletLookupError, match="RPC error"):
                _matic_balance(_FAKE_ADDRESS, _RPC_URL)


class TestUsdcBalance:
    def test_converts_hex_to_usdc(self):
        # 500 * 10^6 = 500 USDC
        hex_500_usdc = hex(500 * 10**6)
        with patch("requests.post", return_value=_rpc_mock(hex_500_usdc)):
            from app.adapters.wallet_adapter import _USDC_CONTRACTS
            result = _usdc_balance(_USDC_CONTRACTS[0], _FAKE_ADDRESS, _RPC_URL)
        assert result == pytest.approx(500.0)

    def test_empty_hex_returns_zero(self):
        with patch("requests.post", return_value=_rpc_mock("0x")):
            from app.adapters.wallet_adapter import _USDC_CONTRACTS
            result = _usdc_balance(_USDC_CONTRACTS[0], _FAKE_ADDRESS, _RPC_URL)
        assert result == 0.0


class TestMaticUsdPrice:
    def test_returns_price(self):
        with patch("requests.get", return_value=_price_mock(0.75)):
            price = _matic_usd_price()
        assert price == pytest.approx(0.75)

    def test_network_error_raises(self):
        with patch("requests.get", side_effect=requests.RequestException("timeout")):
            with pytest.raises(WalletLookupError, match="Price fetch failed"):
                _matic_usd_price()

    def test_malformed_response_raises(self):
        m = MagicMock()
        m.raise_for_status.return_value = None
        m.json.return_value = {"unexpected": "data"}
        with patch("requests.get", return_value=m):
            with pytest.raises(WalletLookupError):
                _matic_usd_price()


class TestFetchWalletUsdValue:
    def test_sums_matic_and_usdc(self):
        # 2 MATIC @ $0.80 = $1.60
        # 100 native USDC + 50 USDC.e = $150
        # Total = $151.60
        matic_hex    = hex(2 * 10**18)
        usdc_hex     = hex(100 * 10**6)
        usdc_e_hex   = hex(50 * 10**6)

        with patch("requests.post") as mock_post, patch("requests.get") as mock_get:
            mock_post.side_effect = [
                _rpc_mock(matic_hex),    # eth_getBalance
                _rpc_mock(usdc_hex),     # balanceOf native USDC
                _rpc_mock(usdc_e_hex),   # balanceOf USDC.e
            ]
            mock_get.return_value = _price_mock(0.80)

            result = fetch_wallet_usd_value(_FAKE_ADDRESS)

        assert result == pytest.approx(151.60)

    def test_network_error_raises_wallet_lookup_error(self):
        with patch("requests.post", side_effect=requests.RequestException("no route")):
            with pytest.raises(WalletLookupError):
                fetch_wallet_usd_value(_FAKE_ADDRESS)

    def test_zero_wallet_returns_zero(self):
        with patch("requests.post") as mock_post, patch("requests.get") as mock_get:
            mock_post.side_effect = [
                _rpc_mock(hex(0)),  # 0 MATIC
                _rpc_mock("0x"),    # 0 native USDC
                _rpc_mock("0x"),    # 0 USDC.e
            ]
            mock_get.return_value = _price_mock(1.0)

            result = fetch_wallet_usd_value(_FAKE_ADDRESS)

        assert result == 0.0
