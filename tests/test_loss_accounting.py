"""Tests for close_type classification and loss accounting correctness.

All tests are offline — no network calls, no Qt widgets.
"""

import pytest

from app.models import ResolvedPosition, UserActivity


def _pos(market, cost, redeem, outcome_held="Yes", winning_outcome="Yes"):
    return ResolvedPosition(
        market=market, outcome_held=outcome_held, winning_outcome=winning_outcome,
        quantity=100.0, cost_basis=cost, redeem_value=redeem,
        redeemed=True,
    )


def _sell(market, outcome="Yes"):
    return UserActivity(
        timestamp=9000, type="TRADE", title=market, outcome=outcome,
        side="SELL", size=50.0, usdc_size=25.0, price=0.5,
    )


class TestCloseTypeBasic:
    def test_win_positive_pnl(self):
        from app.services.pnl_today import classify_closed_positions
        p = _pos("M", cost=50.0, redeem=60.0)
        classify_closed_positions([p], [])
        assert p.close_type == "REDEEMED_WIN"

    def test_full_loss_zero_redeem(self):
        from app.services.pnl_today import classify_closed_positions
        p = _pos("M", cost=50.0, redeem=0.0, outcome_held="Yes", winning_outcome="No")
        classify_closed_positions([p], [])
        assert p.close_type == "RESOLVED_LOSS"

    def test_partial_loss_positive_redeem(self):
        from app.services.pnl_today import classify_closed_positions
        p = _pos("M", cost=50.0, redeem=30.0)
        classify_closed_positions([p], [])
        assert p.close_type == "SOLD"

    def test_sell_in_activity_overrides_to_sold(self):
        from app.services.pnl_today import classify_closed_positions
        p = _pos("Market X", cost=50.0, redeem=0.0)
        classify_closed_positions([p], [_sell("Market X")])
        assert p.close_type == "SOLD"

    def test_sell_different_market_no_override(self):
        from app.services.pnl_today import classify_closed_positions
        p = _pos("Market X", cost=50.0, redeem=0.0)
        classify_closed_positions([p], [_sell("Market Y")])
        assert p.close_type == "RESOLVED_LOSS"


class TestPnlFormulas:
    def test_full_loss_pnl_equals_neg_cost(self):
        p = _pos("M", cost=75.0, redeem=0.0)
        assert p.realized_pnl == pytest.approx(-75.0)

    def test_win_pnl_equals_gain(self):
        p = _pos("M", cost=50.0, redeem=65.0)
        assert p.realized_pnl == pytest.approx(15.0)

    def test_partial_sell_pnl_is_negative(self):
        p = _pos("M", cost=50.0, redeem=30.0)
        assert p.realized_pnl == pytest.approx(-20.0)

    def test_pnl_pct_correct(self):
        p = _pos("M", cost=50.0, redeem=75.0)
        assert p.realized_pnl_pct == pytest.approx(50.0)

    def test_zero_cost_pnl_pct_safe(self):
        p = _pos("M", cost=0.0, redeem=0.0)
        assert p.realized_pnl_pct == 0.0


class TestSellDetection:
    def test_sell_outcome_match_required(self):
        from app.services.pnl_today import classify_closed_positions
        p = _pos("Market A", cost=50.0, redeem=0.0, outcome_held="Yes")
        # SELL for same market but different outcome — should NOT override
        wrong_outcome_sell = UserActivity(
            timestamp=9000, type="TRADE", title="Market A", outcome="No",
            side="SELL", size=50.0, usdc_size=25.0, price=0.5,
        )
        classify_closed_positions([p], [wrong_outcome_sell])
        assert p.close_type == "RESOLVED_LOSS"

    def test_multiple_positions_classified_independently(self):
        from app.services.pnl_today import classify_closed_positions
        win  = _pos("Win",  cost=50.0, redeem=65.0)
        sold = _pos("Sold", cost=50.0, redeem=0.0)
        loss = _pos("Loss", cost=50.0, redeem=0.0)
        classify_closed_positions([win, sold, loss], [_sell("Sold")])
        assert win.close_type  == "REDEEMED_WIN"
        assert sold.close_type == "SOLD"
        assert loss.close_type == "RESOLVED_LOSS"

    def test_buy_activity_does_not_affect_classification(self):
        from app.services.pnl_today import classify_closed_positions
        p = _pos("M", cost=50.0, redeem=0.0)
        buy_activity = UserActivity(
            timestamp=9000, type="TRADE", title="M", outcome="Yes",
            side="BUY", size=50.0, usdc_size=25.0, price=0.5,
        )
        classify_closed_positions([p], [buy_activity])
        # BUY is not a SELL — loss remains RESOLVED_LOSS
        assert p.close_type == "RESOLVED_LOSS"

    def test_sell_from_unrelated_wallet_activity_not_matched(self):
        from app.services.pnl_today import classify_closed_positions
        p = _pos("BigMarket", cost=50.0, redeem=0.0)
        # We pass only activity for this wallet; SELL for a different market
        classify_closed_positions([p], [_sell("OtherMarket")])
        assert p.close_type == "RESOLVED_LOSS"


class TestDefaultCloseType:
    def test_default_is_unknown(self):
        p = _pos("M", cost=50.0, redeem=0.0)
        assert p.close_type == "UNKNOWN"

    def test_classify_modifies_in_place(self):
        from app.services.pnl_today import classify_closed_positions
        p = _pos("M", cost=50.0, redeem=0.0)
        assert p.close_type == "UNKNOWN"
        classify_closed_positions([p], [])
        assert p.close_type != "UNKNOWN"

    def test_empty_closed_list_is_safe(self):
        from app.services.pnl_today import classify_closed_positions
        classify_closed_positions([], [])  # must not raise

    def test_empty_activity_list_is_safe(self):
        from app.services.pnl_today import classify_closed_positions
        p = _pos("M", cost=50.0, redeem=60.0)
        classify_closed_positions([p], [])
        assert p.close_type == "REDEEMED_WIN"
