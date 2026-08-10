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
    fetch_resolved_positions,
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

    def test_includes_resolved_rows_as_active(self):
        # The raw /positions endpoint returns both active and resolved-not-yet-redeemed;
        # dedup happens in the UI layer (wallet_panel), not in the adapter
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


# ── fetch_resolved_positions ───────────────────────────────────────────────────

class TestFetchResolvedPositions:
    def test_returns_resolved_positions(self):
        with patch("requests.get", return_value=_mock_response([_REDEEMABLE_ROW])):
            result = fetch_resolved_positions(_FAKE_WALLET)
        assert len(result) == 1
        p = result[0]
        assert p.market          == "Did Y happen?"
        assert p.outcome_held    == "YES"
        assert p.winning_outcome == "YES"   # resolved + not redeemed ⟹ user's outcome won
        assert p.redeemed        is False
        assert p.resolved_date   == "2025-01-01"

    def test_cost_basis_is_avg_price_times_size(self):
        # 50 shares × $0.50 avg = $25 cost basis
        with patch("requests.get", return_value=_mock_response([_REDEEMABLE_ROW])):
            p = fetch_resolved_positions(_FAKE_WALLET)[0]
        assert p.cost_basis == pytest.approx(25.0)

    def test_redeem_value_maps_to_current_value(self):
        with patch("requests.get", return_value=_mock_response([_REDEEMABLE_ROW])):
            p = fetch_resolved_positions(_FAKE_WALLET)[0]
        assert p.redeem_value == pytest.approx(50.0)

    def test_empty_response_returns_empty_list(self):
        with patch("requests.get", return_value=_mock_response([])):
            assert fetch_resolved_positions(_FAKE_WALLET) == []

    def test_network_error_raises(self):
        with patch("requests.get", side_effect=requests.RequestException("timeout")):
            with pytest.raises(PolymarketLookupError):
                fetch_resolved_positions(_FAKE_WALLET)

    def test_missing_size_defaults_to_zero(self):
        row = {"title": "Test", "outcome": "NO", "avgPrice": 0.5,
               "currentValue": 0.0, "redeemable": True}
        with patch("requests.get", return_value=_mock_response([row])):
            p = fetch_resolved_positions(_FAKE_WALLET)[0]
        assert p.quantity   == pytest.approx(0.0)
        assert p.cost_basis == pytest.approx(0.0)

    def test_is_win_true_for_all_resolved(self):
        with patch("requests.get", return_value=_mock_response([_REDEEMABLE_ROW])):
            p = fetch_resolved_positions(_FAKE_WALLET)[0]
        assert p.is_win is True

    def test_realized_pnl_is_redeem_minus_cost(self):
        # 50 shares × $0.50 = $25 cost; current value $50 → P/L = +$25
        with patch("requests.get", return_value=_mock_response([_REDEEMABLE_ROW])):
            p = fetch_resolved_positions(_FAKE_WALLET)[0]
        assert p.realized_pnl == pytest.approx(25.0)

    def test_multi_market_event_cur_price_approx_picks_correct_winner(self):
        # Root cause of the "ETH above X" display bug: multiple sub-markets share
        # one event slug, and the old Gamma fallback returned the first resolved
        # sub-market's winner for ALL positions.
        #
        # The fix: _to_resolved now uses currentValue / size as the primary signal
        # (identical to _to_closed's curPrice logic).  For a resolved binary market,
        # winning tokens = ~$1 each, losing tokens = ~$0 each.  This means:
        #   - row_1830 ("Yes", 5 shares, $5 current value) → $1/share → Yes won ✓
        #   - row_1990 ("No",  5 shares, $5 current value) → $1/share → No won  ✓
        # No Gamma API calls needed — the answer is in the row itself.
        import app.adapters.polymarket_adapter as _mod
        _mod._slug_winner_cache.clear()

        row_1830 = {          # ETH > 1830 → Yes won; user holds Yes at $1/share
            "title":        "Ethereum above 1,830 on August 6, 11AM ET?",
            "outcome":      "Yes",
            "eventSlug":    "eth-price-aug6-11am",
            "conditionId":  "0xcondition_1830",
            "size":         5.0,
            "avgPrice":     0.50,
            "currentValue": 5.0,   # 5 shares × $1 = winning token
        }
        row_1990 = {          # ETH < 1990 → No won; user holds No at $1/share
            "title":        "Ethereum above 1,990 on August 6, 10AM ET?",
            "outcome":      "No",
            "eventSlug":    "eth-price-aug6-11am",
            "conditionId":  "0xcondition_1990",
            "size":         5.0,
            "avgPrice":     0.50,
            "currentValue": 5.0,   # 5 shares × $1 = winning token
        }

        # Only one requests.get call: the positions API.  No Gamma calls.
        with patch("requests.get", return_value=_mock_response([row_1830, row_1990])):
            results = fetch_resolved_positions(_FAKE_WALLET)

        assert len(results) == 2
        by_title = {p.market: p for p in results}

        p_1830 = by_title["Ethereum above 1,830 on August 6, 11AM ET?"]
        assert p_1830.winning_outcome == "Yes"   # $1/share → Yes won
        assert p_1830.outcome_held    == "Yes"
        assert p_1830.is_win          is True

        p_1990 = by_title["Ethereum above 1,990 on August 6, 10AM ET?"]
        assert p_1990.winning_outcome == "No"    # $1/share → No won
        assert p_1990.outcome_held    == "No"
        assert p_1990.is_win          is True

    def test_resolved_losing_position_uses_binary_opposite_when_gamma_unavailable(self):
        # Losing resolved position: user holds Yes but No won (currentValue ≈ 0).
        # Gamma unavailable (no slug, no conditionId) → _binary_opposite fallback.
        row = {
            "title":        "Will it rain?",
            "outcome":      "Yes",
            "size":         10.0,
            "avgPrice":     0.50,
            "currentValue": 0.05,   # ~$0/share → Yes lost
        }
        with patch("requests.get", return_value=_mock_response([row])):
            p = fetch_resolved_positions(_FAKE_WALLET)[0]
        assert p.winning_outcome == "No"    # binary opposite of "Yes"
        assert p.outcome_held    == "Yes"
        assert p.is_win          is False

    def test_partial_sell_winner_cost_basis_proportional(self):
        # Real failing case: bought 203.04 shares @ $0.990, sold 201 before resolution,
        # 2.04 shares redeemed at $1.  The API returns size=203.04 (total bought) and
        # currentValue=2.04 (remaining value).  Without the fix, cost_basis = $201 and
        # P/L = -$199 (a contradiction: labeled Win but -99% loss).
        # With the fix, cost_basis = avgPrice × remaining_qty = 0.990 × 2.04 ≈ $2.02.
        row = {
            "title":        "Bitcoin Up or Down - August 10, 1:30PM-1:45PM ET",
            "outcome":      "Up",
            "size":         203.04,   # total originally bought (NOT remaining)
            "avgPrice":     0.990,
            "currentValue": 2.04,     # value of the 2.04 shares still held to resolution
            "redeemable":   True,
        }
        with patch("requests.get", return_value=_mock_response([row])):
            p = fetch_resolved_positions(_FAKE_WALLET)[0]

        assert p.winning_outcome == "Up"           # cur_price_approx detects winner
        assert p.is_win          is True
        assert abs(p.quantity   - 2.04)     < 0.01  # remaining qty, not total bought
        assert abs(p.cost_basis - 0.990 * 2.04) < 0.02  # ~$2.02, not ~$201
        assert abs(p.redeem_value - 2.04)   < 0.01
        assert p.realized_pnl > 0                  # small win, not -$199

    def test_resolved_losing_position_up_down_binary_opposite(self):
        row = {
            "title":        "BTC Up or Down?",
            "outcome":      "Up",
            "size":         10.0,
            "avgPrice":     0.50,
            "currentValue": 0.0,    # Up token worth $0 → Down won
        }
        with patch("requests.get", return_value=_mock_response([row])):
            p = fetch_resolved_positions(_FAKE_WALLET)[0]
        assert p.winning_outcome == "Down"
        assert p.is_win          is False

    def test_gamma_winner_cached_separately_per_asset_id(self):
        # Verify the (slug, asset_id) cache key on the event slug path — a second
        # call for the same slug but different asset_id must NOT return the first
        # call's cached winner (clobTokenIds filtering path).
        import app.adapters.polymarket_adapter as _mod
        _mod._slug_winner_cache.clear()

        from app.adapters.polymarket_adapter import _fetch_winner_from_gamma

        gamma_event = [{
            "markets": [
                {
                    "outcomes":      '["Yes","No"]',
                    "outcomePrices": '["1","0"]',
                    "clobTokenIds":  ["token_a_yes", "token_a_no"],
                },
                {
                    "outcomes":      '["Yes","No"]',
                    "outcomePrices": '["0","1"]',
                    "clobTokenIds":  ["token_b_yes", "token_b_no"],
                },
            ],
        }]

        with patch("requests.get") as mock_get:
            mock_get.side_effect = [
                _mock_response(gamma_event),   # first call
                _mock_response(gamma_event),   # second call (different asset_id)
            ]
            winner_a = _fetch_winner_from_gamma("shared-slug", "token_a_yes")
            winner_b = _fetch_winner_from_gamma("shared-slug", "token_b_yes")

        assert winner_a == "Yes"   # token_a sub-market: Yes resolved to $1
        assert winner_b == "No"    # token_b sub-market: No resolved to $1
        assert winner_a != winner_b

    def test_condition_id_winner_cached_independently(self):
        # _fetch_winner_by_condition_id caches under ("cond", condition_id) —
        # different condition IDs never share a cached winner.
        import app.adapters.polymarket_adapter as _mod
        _mod._slug_winner_cache.clear()

        from app.adapters.polymarket_adapter import _fetch_winner_by_condition_id

        with patch("requests.get") as mock_get:
            mock_get.side_effect = [
                _mock_response([{"outcomes": '["Yes","No"]', "outcomePrices": '["1","0"]'}]),
                _mock_response([{"outcomes": '["Yes","No"]', "outcomePrices": '["0","1"]'}]),
            ]
            w1 = _fetch_winner_by_condition_id("cond_a")
            w2 = _fetch_winner_by_condition_id("cond_b")

        assert w1 == "Yes"
        assert w2 == "No"
        assert ("cond", "cond_a") in _mod._slug_winner_cache
        assert ("cond", "cond_b") in _mod._slug_winner_cache


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

    def test_winning_position_close_type_is_redeemed_win(self):
        # _CLOSED_ROW: 50 shares × $0.50 = $25 cost, +$50 pnl → $75 received → $1.50/share
        with patch("requests.get", return_value=_mock_response([_CLOSED_ROW])):
            p = fetch_closed_positions(_FAKE_WALLET)[0]
        assert p.close_type == "REDEEMED_WIN"

    def test_losing_position_sets_winning_outcome_to_opposite(self):
        with patch("requests.get", return_value=_mock_response([_CLOSED_LOSS_ROW])):
            p = fetch_closed_positions(_FAKE_WALLET)[0]
        assert p.is_win          is False
        assert p.winning_outcome == "NO"

    def test_losing_position_close_type_is_resolved_loss(self):
        # _CLOSED_LOSS_ROW: got back $0 → RESOLVED_LOSS
        with patch("requests.get", return_value=_mock_response([_CLOSED_LOSS_ROW])):
            p = fetch_closed_positions(_FAKE_WALLET)[0]
        assert p.close_type == "RESOLVED_LOSS"

    def test_stop_loss_sold_negative_pnl_but_outcome_won(self):
        # BNB scenario: held "Up", stop-loss fired at a loss.
        # Market then resolved "Up" (user's direction was correct).
        # curPrice = 1.0 → the "Up" token is now worth $1 → "Up" won.
        # This was the original bug: P/L < 0 incorrectly implied the opposite outcome won.
        sold_row = {
            "title": "Will BNB go up?",
            "outcome": "Up",
            "oppositeOutcome": "Down",
            "avgPrice": 0.60,
            "totalBought": 100.0,     # 100 shares
            "realizedPnl": -20.0,     # sold at $0.40/share → $40 proceeds − $60 cost = −$20
            "curPrice": 1.0,           # "Up" token resolved to $1 → Up won
            "endDate": "2026-01-01",
        }
        with patch("requests.get", return_value=_mock_response([sold_row])):
            p = fetch_closed_positions(_FAKE_WALLET)[0]
        assert p.winning_outcome == "Up"    # market resolved in user's favour
        assert p.outcome_held    == "Up"
        assert p.is_win          is True    # correct direction despite stop-loss
        assert p.close_type      == "SOLD"  # exited via stop-loss, not redemption
        assert p.realized_pnl    == pytest.approx(-20.0)
        assert p.cost_basis      == pytest.approx(60.0)
        assert p.redeem_value    == pytest.approx(40.0)

    def test_stop_loss_sold_negative_pnl_and_outcome_lost_cur_price_zero(self):
        # Stop-loss fired; market resolved against user AND curPrice=0.0 confirms it.
        sold_row = {
            "title": "Will BTC go up?",
            "outcome": "Up",
            "oppositeOutcome": "Down",
            "avgPrice": 0.70,
            "totalBought": 100.0,
            "realizedPnl": -40.0,     # sold at $0.30/share
            "curPrice": 0.0,           # "Up" resolved to $0 → Down won
            "endDate": "2026-01-01",
        }
        with patch("requests.get", return_value=_mock_response([sold_row])):
            p = fetch_closed_positions(_FAKE_WALLET)[0]
        assert p.winning_outcome == "Down"
        assert p.outcome_held    == "Up"
        assert p.is_win          is False
        assert p.close_type      == "SOLD"   # got back $30 (not $0) → SOLD not RESOLVED_LOSS
        assert p.realized_pnl    == pytest.approx(-40.0)

    def test_gamma_api_returns_actual_winner_for_sold_position(self):
        # SOLD position with mid-market curPrice and a slug.
        # Gamma API returns the actual market resolution — "Up" won even though P/L < 0.
        # (This is the stop-loss-too-early case the user cares about most.)
        import app.adapters.polymarket_adapter as _mod
        _mod._slug_winner_cache.clear()

        sold_row = {
            "title": "Dogecoin Up or Down - 3:30-3:45PM ET",
            "outcome": "Up",
            "oppositeOutcome": "Down",
            "eventSlug": "doge-up-down-1234",
            "avgPrice": 0.60,
            "totalBought": 100.0,
            "realizedPnl": -20.0,     # stop-loss sold at a loss
            "curPrice": 0.40,          # sell price, not resolution price
            "endDate": "2026-08-04",
        }
        gamma_event = [{
            "slug": "doge-up-down-1234",
            "markets": [{
                "outcomes":      '["Up","Down"]',
                "outcomePrices": '["1","0"]',   # "Up" resolved to $1 → Up won
            }],
        }]
        # side_effect: first call → closed positions; second → Gamma event
        with patch("requests.get") as mock_get:
            mock_get.side_effect = [
                _mock_response([sold_row]),   # data-api closed-positions
                _mock_response(gamma_event),  # gamma-api/events?slug=...
            ]
            p = fetch_closed_positions(_FAKE_WALLET)[0]

        # Gamma API correctly identifies "Up" as the winner, despite negative P/L
        assert p.winning_outcome == "Up"
        assert p.outcome_held    == "Up"
        assert p.is_win          is True    # user was right, just stopped out early
        assert p.close_type      == "SOLD"
        assert p.realized_pnl    == pytest.approx(-20.0)  # they still lost money on the trade

    def test_gamma_api_unavailable_falls_back_to_pnl_sign(self):
        # Gamma API errors → fall back to P/L sign heuristic.
        import app.adapters.polymarket_adapter as _mod
        _mod._slug_winner_cache.clear()

        sold_row = {
            "title": "Ethereum Up or Down - 3:30-3:35PM ET",
            "outcome": "Up",
            "oppositeOutcome": "Down",
            "eventSlug": "eth-up-down-5678",
            "avgPrice": 0.50,
            "totalBought": 100.0,
            "realizedPnl": -10.0,
            "curPrice": 0.40,
        }
        with patch("requests.get") as mock_get:
            data_response = _mock_response([sold_row])
            gamma_error = MagicMock()
            gamma_error.raise_for_status.side_effect = requests.RequestException("timeout")
            mock_get.side_effect = [data_response, gamma_error]
            p = fetch_closed_positions(_FAKE_WALLET)[0]

        assert p.winning_outcome == "Down"   # P/L < 0 → opposite (last-resort heuristic)
        assert p.close_type      == "SOLD"

    def test_mid_curprice_no_slug_falls_back_to_pnl_heuristic_negative_pnl(self):
        # No slug → Gamma lookup skipped → P/L < 0 → opposite assumed winner.
        sold_row = {
            "title": "Dogecoin Up or Down - 3:30-3:45PM ET",
            "outcome": "Up",
            "oppositeOutcome": "Down",
            "avgPrice": 0.60,
            "totalBought": 100.0,
            "realizedPnl": -20.0,
            "curPrice": 0.40,
            "endDate": "2026-08-04",
        }
        with patch("requests.get", return_value=_mock_response([sold_row])):
            p = fetch_closed_positions(_FAKE_WALLET)[0]
        assert p.winning_outcome == "Down"
        assert p.is_win          is False
        assert p.close_type      == "SOLD"

    def test_mid_curprice_no_slug_falls_back_to_pnl_heuristic_positive_pnl(self):
        # No slug, P/L ≥ 0 → user's outcome assumed winner.
        sold_row = {
            "title": "Ethereum Up or Down - 3:30-3:35PM ET",
            "outcome": "Up",
            "oppositeOutcome": "Down",
            "avgPrice": 0.50,
            "totalBought": 100.0,
            "realizedPnl": 10.0,
            "curPrice": 0.60,
            "endDate": "2026-08-04",
        }
        with patch("requests.get", return_value=_mock_response([sold_row])):
            p = fetch_closed_positions(_FAKE_WALLET)[0]
        assert p.winning_outcome == "Up"
        assert p.is_win          is True
        assert p.close_type      == "SOLD"

    def test_stop_loss_sold_at_profit_outcome_won(self):
        # Exited early at a profit; market resolved in user's favour.
        # curPrice = 1.0 → user's outcome won, but they sold before full resolution value.
        sold_row = {
            "title": "Another market",
            "outcome": "NO",
            "oppositeOutcome": "YES",
            "avgPrice": 0.30,
            "totalBought": 100.0,
            "realizedPnl": 20.0,      # sold at $0.50/share → $50 proceeds − $30 cost = $20
            "curPrice": 1.0,           # "NO" ultimately resolved to $1 → No won
            "endDate": None,
        }
        with patch("requests.get", return_value=_mock_response([sold_row])):
            p = fetch_closed_positions(_FAKE_WALLET)[0]
        assert p.winning_outcome == "NO"
        assert p.is_win          is True
        assert p.close_type      == "SOLD"   # $50 proceeds on 100 shares = $0.50/share, not $1
        assert p.realized_pnl    == pytest.approx(20.0)

    def test_cost_basis_is_shares_times_avg_price(self):
        # _CLOSED_ROW: totalBought=50 shares, avgPrice=0.5 → cost_basis=25 USDC
        with patch("requests.get", return_value=_mock_response([_CLOSED_ROW])):
            p = fetch_closed_positions(_FAKE_WALLET)[0]
        assert p.cost_basis == pytest.approx(25.0)

    def test_redeem_value_is_cost_plus_pnl(self):
        # cost_basis=25, realizedPnl=50 → redeem_value=75 USDC received
        with patch("requests.get", return_value=_mock_response([_CLOSED_ROW])):
            p = fetch_closed_positions(_FAKE_WALLET)[0]
        assert p.redeem_value == pytest.approx(75.0)

    def test_realized_pnl_correct(self):
        with patch("requests.get", return_value=_mock_response([_CLOSED_ROW])):
            p = fetch_closed_positions(_FAKE_WALLET)[0]
        assert p.realized_pnl == pytest.approx(50.0)

    def test_quantity_is_total_bought_shares(self):
        # totalBought = shares purchased, not USDC — quantity must equal totalBought directly
        with patch("requests.get", return_value=_mock_response([_CLOSED_ROW])):
            p = fetch_closed_positions(_FAKE_WALLET)[0]
        assert p.quantity == pytest.approx(50.0)

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

    def test_redeemable_filter_passed_for_resolved_fetch(self):
        with patch("requests.get", return_value=_mock_response([])) as mock_get:
            fetch_resolved_positions(_FAKE_WALLET)
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
        assert len(a.datetime_utc) == 19   # "YYYY-MM-DD HH:MM:SS"
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
