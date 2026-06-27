"""
Tests for wallet_adapter.py.
All tests use mocked network calls — no real internet access required.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from app.adapters.wallet_adapter import (
    WalletLookupError,
    _token_balance,
    fetch_wallet_usd_value,
)

_FAKE_ADDRESS = "0x" + "a" * 40
_FAKE_RPC = "https://rpc.example.com"


def _rpc_mock(hex_result: str) -> MagicMock:
    m = MagicMock()
    m.raise_for_status.return_value = None
    m.json.return_value = {"jsonrpc": "2.0", "result": hex_result, "id": 1}
    return m


class TestTokenBalance:
    def test_returns_correct_usdc_amount(self):
        hex_val = hex(1500 * 10**6)  # 1500 USDC.e (6 decimals)
        with patch("requests.post", return_value=_rpc_mock(hex_val)):
            result = _token_balance("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174", 6, _FAKE_ADDRESS, _FAKE_RPC)
        assert result == pytest.approx(1500.0)

    def test_returns_correct_pusd_amount(self):
        hex_val = hex(250 * 10**6)  # 250 pUSD (6 decimals)
        with patch("requests.post", return_value=_rpc_mock(hex_val)):
            result = _token_balance("0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB", 6, _FAKE_ADDRESS, _FAKE_RPC)
        assert result == pytest.approx(250.0)

    def test_empty_result_returns_zero(self):
        with patch("requests.post", return_value=_rpc_mock("0x")):
            result = _token_balance("0x" + "b" * 40, 6, _FAKE_ADDRESS, _FAKE_RPC)
        assert result == 0.0

    def test_zero_hex_returns_zero(self):
        with patch("requests.post", return_value=_rpc_mock(hex(0))):
            result = _token_balance("0x" + "b" * 40, 6, _FAKE_ADDRESS, _FAKE_RPC)
        assert result == 0.0

    def test_network_error_raises(self):
        with patch("requests.post", side_effect=requests.RequestException("timeout")):
            with pytest.raises(WalletLookupError, match="Network error"):
                _token_balance("0x" + "b" * 40, 6, _FAKE_ADDRESS, _FAKE_RPC)

    def test_rpc_error_in_response_raises(self):
        m = MagicMock()
        m.raise_for_status.return_value = None
        m.json.return_value = {"jsonrpc": "2.0", "error": {"message": "bad request"}, "id": 1}
        with patch("requests.post", return_value=m):
            with pytest.raises(WalletLookupError, match="RPC error"):
                _token_balance("0x" + "b" * 40, 6, _FAKE_ADDRESS, _FAKE_RPC)


class TestFetchWalletUsdValue:
    def test_sums_usdc_e_and_pusd(self):
        # 800 USDC.e + 400 pUSD = $1200
        usdc_e_hex = hex(800 * 10**6)
        pusd_hex   = hex(400 * 10**6)
        with patch("requests.post") as mock_post:
            mock_post.side_effect = [
                _rpc_mock(usdc_e_hex),  # balanceOf USDC.e
                _rpc_mock(pusd_hex),    # balanceOf pUSD
            ]
            result = fetch_wallet_usd_value(_FAKE_ADDRESS)
        assert result == pytest.approx(1200.0)

    def test_only_usdc_e_balance(self):
        usdc_e_hex = hex(500 * 10**6)
        with patch("requests.post") as mock_post:
            mock_post.side_effect = [_rpc_mock(usdc_e_hex), _rpc_mock("0x")]
            result = fetch_wallet_usd_value(_FAKE_ADDRESS)
        assert result == pytest.approx(500.0)

    def test_only_pusd_balance(self):
        pusd_hex = hex(333 * 10**6)
        with patch("requests.post") as mock_post:
            mock_post.side_effect = [_rpc_mock("0x"), _rpc_mock(pusd_hex)]
            result = fetch_wallet_usd_value(_FAKE_ADDRESS)
        assert result == pytest.approx(333.0)

    def test_zero_balances_returns_zero(self):
        with patch("requests.post") as mock_post:
            mock_post.side_effect = [_rpc_mock("0x"), _rpc_mock("0x")]
            result = fetch_wallet_usd_value(_FAKE_ADDRESS)
        assert result == 0.0

    def test_all_rpcs_fail_raises_wallet_lookup_error(self):
        with patch("requests.post", side_effect=requests.RequestException("401")):
            with pytest.raises(WalletLookupError, match="All Polygon RPCs failed"):
                fetch_wallet_usd_value(_FAKE_ADDRESS)

    def test_falls_back_to_second_rpc_on_first_failure(self):
        # RPC 1 fails, RPC 2 succeeds
        usdc_e_hex = hex(600 * 10**6)
        pusd_hex   = hex(100 * 10**6)
        with patch("requests.post") as mock_post:
            mock_post.side_effect = [
                requests.RequestException("401"),  # rpc 1 fails on first call
                _rpc_mock(usdc_e_hex),             # rpc 2: USDC.e
                _rpc_mock(pusd_hex),               # rpc 2: pUSD
            ]
            result = fetch_wallet_usd_value(_FAKE_ADDRESS)
        assert result == pytest.approx(700.0)

    def test_result_rounded_to_cents(self):
        # 1000.005 + 0.004 should round to 2 decimal places
        hex_val = hex(int(1000.005 * 10**6))
        with patch("requests.post") as mock_post:
            mock_post.side_effect = [_rpc_mock(hex_val), _rpc_mock("0x")]
            result = fetch_wallet_usd_value(_FAKE_ADDRESS)
        assert result == round(int(hex_val, 16) / 10**6, 2)

    def test_env_rpc_tried_first(self, monkeypatch):
        monkeypatch.setenv("POLYGON_RPC_URL", "https://custom-rpc.example.com")
        call_log = []

        def fake_post(url, **kwargs):
            call_log.append(url)
            raise requests.RequestException("always fail")

        with patch("requests.post", side_effect=fake_post):
            with pytest.raises(WalletLookupError):
                fetch_wallet_usd_value(_FAKE_ADDRESS)

        assert call_log[0] == "https://custom-rpc.example.com"
