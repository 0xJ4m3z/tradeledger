"""
Tests for polymarket_adapter.py.
All tests mock requests.get — no real network access required.
"""

from unittest.mock import MagicMock, call, patch

import pytest
import requests

from app.adapters.polymarket_adapter import (
    PolymarketLookupError,
    fetch_active_positions,
    fetch_redeemable_positions,
)

_FAKE_WALLET = "0x" + "a" * 40

# ── Helpers ────────────────────────────────────────────────────────────────────

def _mock_response(data: list) -> MagicMock:
    m = MagicMock()
    m.raise_for_status.return_value = None
    m.json.return_value = data
    return m


_ACTIVE_ROW = {
    "title": "Will X happen?",
    "outcome": "YES",
    "size": 100.0,
    "avgPrice": 0.6,
    "curPrice": 0.72,
    "currentValue": 72.0,
    "redeemable": False,
    "conditionId": "0x" + "a" * 64,
}

_REDEEMABLE_ROW = {
    "title": "Did Y happen?",
    "outcome": "YES",
    "size": 50.0,
    "avgPrice": 0.5,
    "currentValue": 50.0,
    "redeemable": True,
    "endDate": "2025-01-01",
    "conditionId": "0x" + "b" * 64,
}


# ── fetch_active_positions ─────────────────────────────────────────────────────

class TestFetchActivePositions:
    def test_returns_active_positions(self):
        with patch("requests.get", return_value=_mock_response([_ACTIVE_ROW])):
            result = fetch_active_positions(_FAKE_WALLET)
        assert len(result) == 1
        p = result[0]
        assert p.market        == "Will X happen?"
        assert p.outcome       == "YES"
        assert p.quantity      == pytest.approx(100.0)
        assert p.avg_cost      == pytest.approx(0.6)
        assert p.current_price == pytest.approx(0.72)

    def test_filters_out_redeemable_rows(self):
        data = [_ACTIVE_ROW, _REDEEMABLE_ROW]
        with patch("requests.get", return_value=_mock_response(data)):
            result = fetch_active_positions(_FAKE_WALLET)
        assert len(result) == 1
        assert result[0].market == "Will X happen?"

    def test_empty_response_returns_empty_list(self):
        with patch("requests.get", return_value=_mock_response([])):
            assert fetch_active_positions(_FAKE_WALLET) == []

    def test_network_error_raises(self):
        with patch("requests.get", side_effect=requests.RequestException("timeout")):
            with pytest.raises(PolymarketLookupError, match="Network error"):
                fetch_active_positions(_FAKE_WALLET)

    def test_minimal_record_uses_defaults(self):
        data = [{"redeemable": False}]
        with patch("requests.get", return_value=_mock_response(data)):
            result = fetch_active_positions(_FAKE_WALLET)
        assert len(result) == 1
        p = result[0]
        assert p.market        == "Unknown"
        assert p.outcome       == ""
        assert p.quantity      == pytest.approx(0.0)
        assert p.avg_cost      == pytest.approx(0.0)
        assert p.current_price == pytest.approx(0.0)

    def test_current_price_falls_back_to_avg_price_when_missing(self):
        row = {**_ACTIVE_ROW}
        del row["curPrice"]
        with patch("requests.get", return_value=_mock_response([row])):
            result = fetch_active_positions(_FAKE_WALLET)
        assert result[0].current_price == pytest.approx(0.6)   # falls back to avgPrice

    def test_unrealized_pnl_computed_correctly(self):
        # 100 shares, avg 0.60, current 0.72 → cost=60, value=72, pnl=+12
        with patch("requests.get", return_value=_mock_response([_ACTIVE_ROW])):
            p = fetch_active_positions(_FAKE_WALLET)[0]
        assert p.cost_basis      == pytest.approx(60.0)
        assert p.current_value   == pytest.approx(72.0)
        assert p.unrealized_pnl  == pytest.approx(12.0)


# ── fetch_redeemable_positions ─────────────────────────────────────────────────

class TestFetchRedeemablePositions:
    def test_returns_redeemable_positions(self):
        with patch("requests.get", return_value=_mock_response([_REDEEMABLE_ROW])):
            result = fetch_redeemable_positions(_FAKE_WALLET)
        assert len(result) == 1
        p = result[0]
        assert p.market          == "Did Y happen?"
        assert p.outcome_held    == "YES"
        assert p.winning_outcome == "YES"   # redeemable ⟹ user's outcome won
        assert p.redeemed        is False
        assert p.resolved_date   == "2025-01-01"

    def test_cost_basis_is_avg_price_times_size(self):
        # 50 shares × $0.50 avg = $25 cost basis
        with patch("requests.get", return_value=_mock_response([_REDEEMABLE_ROW])):
            p = fetch_redeemable_positions(_FAKE_WALLET)[0]
        assert p.cost_basis == pytest.approx(25.0)

    def test_redeem_value_maps_to_current_value(self):
        with patch("requests.get", return_value=_mock_response([_REDEEMABLE_ROW])):
            p = fetch_redeemable_positions(_FAKE_WALLET)[0]
        assert p.redeem_value == pytest.approx(50.0)

    def test_empty_response_returns_empty_list(self):
        with patch("requests.get", return_value=_mock_response([])):
            assert fetch_redeemable_positions(_FAKE_WALLET) == []

    def test_network_error_raises(self):
        with patch("requests.get", side_effect=requests.RequestException("timeout")):
            with pytest.raises(PolymarketLookupError):
                fetch_redeemable_positions(_FAKE_WALLET)

    def test_missing_size_defaults_to_zero(self):
        row = {"title": "Test", "outcome": "NO", "avgPrice": 0.5,
               "currentValue": 0.0, "redeemable": True}
        with patch("requests.get", return_value=_mock_response([row])):
            p = fetch_redeemable_positions(_FAKE_WALLET)[0]
        assert p.quantity   == pytest.approx(0.0)
        assert p.cost_basis == pytest.approx(0.0)

    def test_is_win_true_for_all_redeemable(self):
        with patch("requests.get", return_value=_mock_response([_REDEEMABLE_ROW])):
            p = fetch_redeemable_positions(_FAKE_WALLET)[0]
        assert p.is_win is True

    def test_realized_pnl_is_redeem_minus_cost(self):
        # 50 shares × $0.50 = $25 cost; current value $50 → P/L = +$25
        with patch("requests.get", return_value=_mock_response([_REDEEMABLE_ROW])):
            p = fetch_redeemable_positions(_FAKE_WALLET)[0]
        assert p.realized_pnl == pytest.approx(25.0)


# ── Pagination ─────────────────────────────────────────────────────────────────

class TestPagination:
    def test_fetches_second_page_when_first_is_full(self):
        page1 = [
            {**_ACTIVE_ROW, "title": f"Market {i}"}
            for i in range(100)
        ]
        page2 = [
            {**_ACTIVE_ROW, "title": f"Market {i+100}"}
            for i in range(3)
        ]
        with patch("requests.get") as mock_get:
            mock_get.side_effect = [
                _mock_response(page1),
                _mock_response(page2),
                _mock_response([]),
            ]
            result = fetch_active_positions(_FAKE_WALLET)
        assert len(result) == 103

    def test_stops_after_partial_page(self):
        page = [_ACTIVE_ROW] * 10   # fewer than PAGE_SIZE=500
        with patch("requests.get") as mock_get:
            mock_get.return_value = _mock_response(page)
            result = fetch_active_positions(_FAKE_WALLET)
        assert mock_get.call_count == 1
        assert len(result) == 10

    def test_passes_user_param_to_request(self):
        with patch("requests.get", return_value=_mock_response([])) as mock_get:
            fetch_active_positions(_FAKE_WALLET)
        call_kwargs = mock_get.call_args
        params = call_kwargs[1]["params"]
        assert params["user"] == _FAKE_WALLET

    def test_redeemable_filter_passed_for_redeemable_fetch(self):
        with patch("requests.get", return_value=_mock_response([])) as mock_get:
            fetch_redeemable_positions(_FAKE_WALLET)
        params = mock_get.call_args[1]["params"]
        assert params["redeemable"] == "true"
