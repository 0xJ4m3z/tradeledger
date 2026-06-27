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
    fetch_activity,
    fetch_closed_positions,
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

    def test_includes_redeemable_rows_as_active(self):
        # Redeemable = won but not yet claimed — still shows as active until redeemed
        data = [_ACTIVE_ROW, _REDEEMABLE_ROW]
        with patch("requests.get", return_value=_mock_response(data)):
            result = fetch_active_positions(_FAKE_WALLET)
        assert len(result) == 2

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

# ── fetch_closed_positions ─────────────────────────────────────────────────────

_CLOSED_ROW = {
    "title": "Was Z true?",
    "outcome": "YES",
    "oppositeOutcome": "NO",
    "avgPrice": 0.5,
    "totalBought": 50.0,
    "realizedPnl": 50.0,
    "curPrice": 1.0,
    "endDate": "2025-03-01",
}

_CLOSED_LOSS_ROW = {
    "title": "Was W true?",
    "outcome": "YES",
    "oppositeOutcome": "NO",
    "avgPrice": 0.7,
    "totalBought": 70.0,
    "realizedPnl": -70.0,
    "curPrice": 0.0,
    "endDate": "2025-04-01",
}


class TestFetchClosedPositions:
    def test_returns_closed_positions(self):
        with patch("requests.get", return_value=_mock_response([_CLOSED_ROW])):
            result = fetch_closed_positions(_FAKE_WALLET)
        assert len(result) == 1
        p = result[0]
        assert p.market       == "Was Z true?"
        assert p.outcome_held == "YES"
        assert p.redeemed     is True
        assert p.resolved_date == "2025-03-01"

    def test_winning_position_sets_winning_outcome_to_held(self):
        with patch("requests.get", return_value=_mock_response([_CLOSED_ROW])):
            p = fetch_closed_positions(_FAKE_WALLET)[0]
        assert p.is_win          is True
        assert p.winning_outcome == "YES"

    def test_losing_position_sets_winning_outcome_to_opposite(self):
        with patch("requests.get", return_value=_mock_response([_CLOSED_LOSS_ROW])):
            p = fetch_closed_positions(_FAKE_WALLET)[0]
        assert p.is_win          is False
        assert p.winning_outcome == "NO"

    def test_stop_loss_sell_at_loss_treated_as_loss(self):
        # Bought at 0.70, stop-loss sold at 0.30 (mid-market, not a resolved price)
        sold_row = {
            "title": "Volatile market",
            "outcome": "YES",
            "oppositeOutcome": "NO",
            "avgPrice": 0.70,
            "totalBought": 70.0,
            "realizedPnl": -40.0,   # sold for $30, paid $70 → -$40
            "curPrice": 0.30,       # mid-market at time of sell (NOT resolution price)
            "endDate": None,
        }
        with patch("requests.get", return_value=_mock_response([sold_row])):
            p = fetch_closed_positions(_FAKE_WALLET)[0]
        # curPrice=0.30 would wrongly look like a loss via threshold,
        # but realizedPnl=-40 correctly identifies it as a loss
        assert p.is_win is False
        assert p.realized_pnl == pytest.approx(-40.0)
        assert p.redeem_value == pytest.approx(30.0)  # proceeds received

    def test_stop_loss_sell_at_profit_treated_as_win(self):
        sold_row = {
            "title": "Another market",
            "outcome": "NO",
            "oppositeOutcome": "YES",
            "avgPrice": 0.30,
            "totalBought": 30.0,
            "realizedPnl": 20.0,   # sold for $50, paid $30 → +$20
            "curPrice": 0.50,
            "endDate": None,
        }
        with patch("requests.get", return_value=_mock_response([sold_row])):
            p = fetch_closed_positions(_FAKE_WALLET)[0]
        assert p.is_win is True
        assert p.realized_pnl == pytest.approx(20.0)

    def test_cost_basis_maps_to_total_bought(self):
        with patch("requests.get", return_value=_mock_response([_CLOSED_ROW])):
            p = fetch_closed_positions(_FAKE_WALLET)[0]
        assert p.cost_basis == pytest.approx(50.0)

    def test_redeem_value_is_cost_plus_pnl(self):
        # totalBought=50, realizedPnl=50 → proceeds=100
        with patch("requests.get", return_value=_mock_response([_CLOSED_ROW])):
            p = fetch_closed_positions(_FAKE_WALLET)[0]
        assert p.redeem_value == pytest.approx(100.0)

    def test_realized_pnl_correct(self):
        with patch("requests.get", return_value=_mock_response([_CLOSED_ROW])):
            p = fetch_closed_positions(_FAKE_WALLET)[0]
        assert p.realized_pnl == pytest.approx(50.0)

    def test_quantity_derived_from_total_bought_and_avg_price(self):
        # totalBought=50, avgPrice=0.5 → 100 shares
        with patch("requests.get", return_value=_mock_response([_CLOSED_ROW])):
            p = fetch_closed_positions(_FAKE_WALLET)[0]
        assert p.quantity == pytest.approx(100.0)

    def test_empty_response_returns_empty_list(self):
        with patch("requests.get", return_value=_mock_response([])):
            assert fetch_closed_positions(_FAKE_WALLET) == []

    def test_network_error_raises(self):
        with patch("requests.get", side_effect=requests.RequestException("timeout")):
            with pytest.raises(PolymarketLookupError):
                fetch_closed_positions(_FAKE_WALLET)

    def test_hits_closed_positions_endpoint(self):
        with patch("requests.get", return_value=_mock_response([])) as mock_get:
            fetch_closed_positions(_FAKE_WALLET)
        url = mock_get.call_args[0][0]
        assert "closed-positions" in url


class TestPagination:
    def test_fetches_second_page_when_first_is_full(self):
        page1 = [
            {**_ACTIVE_ROW, "title": f"Market {i}"}
            for i in range(50)
        ]
        page2 = [
            {**_ACTIVE_ROW, "title": f"Market {i+50}"}
            for i in range(3)
        ]
        with patch("requests.get") as mock_get:
            mock_get.side_effect = [
                _mock_response(page1),
                _mock_response(page2),
                _mock_response([]),
            ]
            result = fetch_active_positions(_FAKE_WALLET)
        assert len(result) == 53

    def test_stops_after_partial_page(self):
        page = [_ACTIVE_ROW] * 10   # fewer than PAGE_SIZE=50
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
        # sizeThreshold omitted to avoid server-side 408 timeouts
        assert "sizeThreshold" not in params


# ── Activity ───────────────────────────────────────────────────────────────────

_ACTIVITY_ROW = {
    "timestamp":  1_750_000_000,
    "type":       "TRADE",
    "title":      "Will something happen?",
    "outcome":    "YES",
    "side":       "BUY",
    "size":       50.0,
    "usdcSize":   35.0,
    "price":      0.70,
    "proxyWallet": "0x" + "a" * 40,
}

_REDEEM_ROW = {
    "timestamp":  1_750_001_000,
    "type":       "REDEEM",
    "title":      "Resolved market",
    "outcome":    "YES",
    "side":       "",
    "size":       50.0,
    "usdcSize":   50.0,
    "price":      0.0,
}


class TestFetchActivity:
    def test_returns_activity_list(self):
        with patch("requests.get", return_value=_mock_response([_ACTIVITY_ROW])):
            result = fetch_activity(_FAKE_WALLET)
        assert len(result) == 1

    def test_trade_fields_mapped_correctly(self):
        with patch("requests.get", return_value=_mock_response([_ACTIVITY_ROW])):
            a = fetch_activity(_FAKE_WALLET)[0]
        assert a.timestamp  == 1_750_000_000
        assert a.type       == "TRADE"
        assert a.title      == "Will something happen?"
        assert a.outcome    == "YES"
        assert a.side       == "BUY"
        assert a.size       == pytest.approx(50.0)
        assert a.usdc_size  == pytest.approx(35.0)
        assert a.price      == pytest.approx(0.70)

    def test_redeem_row_no_side(self):
        with patch("requests.get", return_value=_mock_response([_REDEEM_ROW])):
            a = fetch_activity(_FAKE_WALLET)[0]
        assert a.type == "REDEEM"
        assert a.side == ""
        assert a.price == pytest.approx(0.0)

    def test_datetime_utc_property_formats_timestamp(self):
        with patch("requests.get", return_value=_mock_response([_ACTIVITY_ROW])):
            a = fetch_activity(_FAKE_WALLET)[0]
        # Just check it returns a string in expected format — exact value depends on TZ
        assert len(a.datetime_utc) == 16   # "YYYY-MM-DD HH:MM"
        assert "-" in a.datetime_utc
        assert ":" in a.datetime_utc

    def test_empty_response_returns_empty_list(self):
        with patch("requests.get", return_value=_mock_response([])):
            result = fetch_activity(_FAKE_WALLET)
        assert result == []

    def test_network_error_raises(self):
        with patch("requests.get", side_effect=requests.ConnectionError("timeout")):
            with pytest.raises(PolymarketLookupError):
                fetch_activity(_FAKE_WALLET)

    def test_hits_activity_endpoint(self):
        with patch("requests.get", return_value=_mock_response([])) as mock_get:
            fetch_activity(_FAKE_WALLET)
        url = mock_get.call_args[0][0]
        assert url.endswith("/activity")

    def test_sorted_descending_by_timestamp(self):
        with patch("requests.get", return_value=_mock_response([])) as mock_get:
            fetch_activity(_FAKE_WALLET)
        params = mock_get.call_args[1]["params"]
        assert params["sortBy"]        == "TIMESTAMP"
        assert params["sortDirection"] == "DESC"

    def test_capped_at_single_page(self):
        # max_pages=1 means a full first page stops pagination (no second request)
        full_page = [_ACTIVITY_ROW] * 100
        with patch("requests.get") as mock_get:
            mock_get.return_value = _mock_response(full_page)
            fetch_activity(_FAKE_WALLET)
        assert mock_get.call_count == 1

    def test_missing_fields_default_gracefully(self):
        sparse = {"timestamp": 1_700_000_000, "type": "REWARD"}
        with patch("requests.get", return_value=_mock_response([sparse])):
            a = fetch_activity(_FAKE_WALLET)[0]
        assert a.title     == ""
        assert a.outcome   == ""
        assert a.side      == ""
        assert a.size      == pytest.approx(0.0)
        assert a.usdc_size == pytest.approx(0.0)
        assert a.price     == pytest.approx(0.0)
