"""
Tests for app/services/pnl_today.py.
Verifies cost-basis matching, CT-day boundary logic, and rounding.
"""

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models import UserActivity
from app.services.pnl_today import compute_pnl_today, count_trades_today, today_date_ct

# ── Helpers ────────────────────────────────────────────────────────────────────

# Use ET so timestamps match the ET-based today_date_et() used inside pnl_today.py.
_CT = ZoneInfo("America/New_York")


def _ts_today(hour: int = 12) -> int:
    return int(datetime.now(tz=_CT).replace(
        hour=hour, minute=0, second=0, microsecond=0
    ).timestamp())


def _ts_yesterday(hour: int = 12) -> int:
    from datetime import timedelta as td
    return int((datetime.now(tz=_CT) - td(days=1)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    ).timestamp())


def _make(
    side: str,
    type_: str,
    usdc: float,
    size: float = 0.0,
    ts: int | None = None,
    title: str = "Test Market",
    outcome: str = "Yes",   # pass "" to simulate Polymarket REDEEM (no outcome in API)
) -> UserActivity:
    return UserActivity(
        timestamp=ts if ts is not None else _ts_today(),
        type=type_,
        title=title,
        outcome=outcome,
        side=side,
        size=size,
        usdc_size=usdc,
        price=0.0,
    )


# ── Core P/L logic ─────────────────────────────────────────────────────────────

class TestComputePnlToday:
    def test_empty_activity_returns_zero(self):
        assert compute_pnl_today([]) == 0.0

    def test_buy_only_returns_zero(self):
        # BUY with no close today → nothing realized
        a = _make("BUY", "TRADE", 50.0, size=500.0)
        assert compute_pnl_today([a]) == 0.0

    def test_sell_without_matching_buy_is_skipped(self):
        # No BUY in feed → skip rather than count raw proceeds as "profit"
        a = _make("SELL", "TRADE", 80.0, size=800.0)
        assert compute_pnl_today([a]) == 0.0

    def test_redeem_without_matching_buy_is_skipped(self):
        a = _make("", "REDEEM", 100.0, size=100.0)
        assert compute_pnl_today([a]) == 0.0

    def test_sell_with_matching_buy_profit(self):
        # Bought 1000 tokens at $0.10 = $100 cost; sold today at $0.12 = $120
        activity = [
            _make("BUY",  "TRADE", 100.0, size=1000.0),
            _make("SELL", "TRADE", 120.0, size=1000.0),
        ]
        assert compute_pnl_today(activity) == 20.0   # 120 − 100

    def test_sell_with_matching_buy_loss(self):
        activity = [
            _make("BUY",  "TRADE", 100.0, size=1000.0),
            _make("SELL", "TRADE",  80.0, size=1000.0),
        ]
        assert compute_pnl_today(activity) == -20.0  # 80 − 100

    def test_redeem_with_matching_buy(self):
        # Bought 500 tokens at $0.20 = $100; redeemed at $1.00 = $500
        activity = [
            _make("BUY",   "TRADE",   100.0, size=500.0),
            _make("",      "REDEEM",  500.0, size=500.0),
        ]
        assert compute_pnl_today(activity) == 400.0  # 500 − 100

    def test_buy_from_yesterday_still_provides_cost_basis(self):
        # BUYs from ANY date in the feed count toward cost basis
        activity = [
            _make("BUY",  "TRADE", 100.0, size=1000.0, ts=_ts_yesterday()),
            _make("SELL", "TRADE", 130.0, size=1000.0),  # today
        ]
        assert compute_pnl_today(activity) == 30.0   # 130 − 100

    def test_partial_sell_proportional_cost(self):
        # Bought 1000 tokens for $100 total; sell only 500 today for $60
        activity = [
            _make("BUY",  "TRADE", 100.0, size=1000.0),
            _make("SELL", "TRADE",  60.0, size=500.0),
        ]
        # avg cost = $0.10; cost for 500 = $50; P/L = 60 − 50 = 10
        assert compute_pnl_today(activity) == 10.0

    def test_multiple_buys_weighted_average(self):
        # Two BUYs at different prices → weighted avg
        activity = [
            _make("BUY",  "TRADE",  50.0, size=500.0),   # $0.10 each
            _make("BUY",  "TRADE", 100.0, size=500.0),   # $0.20 each
            _make("SELL", "TRADE", 100.0, size=500.0),   # sell 500 at $0.20
        ]
        # avg = (50+100)/(500+500) = $0.15; cost for 500 = $75; P/L = 100−75 = 25
        assert compute_pnl_today(activity) == 25.0

    def test_different_markets_not_mixed(self):
        # BUY for Market A should not provide cost basis for Market B SELL
        activity = [
            UserActivity(_ts_today(), "TRADE", "Market A", "Yes", "BUY",  1000.0, 100.0, 0.10),
            UserActivity(_ts_today(), "TRADE", "Market B", "Yes", "SELL",  500.0,  60.0, 0.12),
        ]
        # No BUY for Market B → skipped
        assert compute_pnl_today(activity) == 0.0

    def test_different_outcomes_not_mixed_for_sell(self):
        # BUY "Yes" should not cover SELL "No" (different outcome keys, no fallback for SELL)
        activity = [
            UserActivity(_ts_today(), "TRADE", "Market X", "Yes", "BUY",  1000.0, 100.0, 0.10),
            UserActivity(_ts_today(), "TRADE", "Market X", "No",  "SELL",  500.0,  60.0, 0.12),
        ]
        assert compute_pnl_today(activity) == 0.0

    # ── REDEEM with empty outcome (real Polymarket API behaviour) ──────────────

    def test_redeem_empty_outcome_matches_by_title(self):
        # Polymarket REDEEM events return outcome="" in the API response.
        # Should match BUYs for the same title regardless of outcome field.
        activity = [
            _make("BUY",  "TRADE", 504.0, size=514.29, outcome="Up"),
            _make("",     "REDEEM", 514.29, size=514.29, outcome=""),   # empty outcome
        ]
        # P/L = 514.29 - 504.0 = 10.29
        assert compute_pnl_today(activity) == round(514.29 - 504.0, 2)

    def test_redeem_empty_outcome_uses_all_buys_for_title(self):
        # Multiple BUYs at different prices; REDEEM has no outcome.
        activity = [
            _make("BUY", "TRADE",  27.30, size=27.86,  outcome="Up"),
            _make("BUY", "TRADE",   4.90, size=5.00,   outcome="Up"),
            _make("BUY", "TRADE", 422.80, size=431.43, outcome="Up"),
            _make("BUY", "TRADE",  49.00, size=50.00,  outcome="Up"),
            _make("",    "REDEEM", 514.29, size=514.29, outcome=""),
        ]
        total_qty  = 27.86 + 5.00 + 431.43 + 50.00   # 514.29
        total_cost = 27.30 + 4.90 + 422.80 + 49.00   # 504.00
        avg_price  = total_cost / total_qty
        expected   = round(514.29 - 514.29 * avg_price, 2)
        assert compute_pnl_today(activity) == expected

    def test_sell_with_outcome_still_uses_outcome_key(self):
        # SELL events have an outcome — should use (title, outcome) not title-only
        activity = [
            UserActivity(_ts_today(), "TRADE", "Market X", "Yes", "BUY",  1000.0, 100.0, 0.10),
            UserActivity(_ts_today(), "TRADE", "Market X", "No",  "BUY",   500.0,  60.0, 0.12),
            UserActivity(_ts_today(), "TRADE", "Market X", "Yes", "SELL",  500.0,  55.0, 0.11),
        ]
        # SELL is "Yes" → only Yes BUY costs used: avg = 100/1000 = 0.10, cost = 50
        assert compute_pnl_today(activity) == round(55.0 - 50.0, 2)  # 5.0

    def test_yesterday_sell_excluded(self):
        # SELL from yesterday should not count even if BUY is in feed
        activity = [
            _make("BUY",  "TRADE", 100.0, size=1000.0, ts=_ts_yesterday()),
            _make("SELL", "TRADE", 130.0, size=1000.0, ts=_ts_yesterday()),
        ]
        assert compute_pnl_today(activity) == 0.0

    def test_mixed_today_and_yesterday(self):
        activity = [
            _make("BUY",  "TRADE", 100.0, size=1000.0, ts=_ts_yesterday()),  # cost basis
            _make("SELL", "TRADE",  60.0, size=500.0),   # today: 60 − 50 = +10
            _make("",     "REWARD",  2.0),                # today: +2 (direct credit)
        ]
        assert compute_pnl_today(activity) == 12.0

    def test_sell_with_zero_size_is_skipped(self):
        # size=0 means we can't compute quantity → skip
        activity = [
            _make("BUY",  "TRADE", 100.0, size=1000.0),
            _make("SELL", "TRADE",  80.0, size=0.0),
        ]
        assert compute_pnl_today(activity) == 0.0

    def test_rounding_to_two_decimals(self):
        activity = [
            _make("BUY",  "TRADE", 10.0, size=300.0),  # avg = 1/30
            _make("SELL", "TRADE", 11.0, size=100.0),
        ]
        result = compute_pnl_today(activity)
        assert result == round(result, 2)

    def test_unknown_type_ignored(self):
        a = _make("", "SPLIT", 999.0, size=100.0)
        assert compute_pnl_today([a]) == 0.0

    # ── Rebates / rewards ──────────────────────────────────────────────────────

    def test_reward_is_direct_credit(self):
        assert compute_pnl_today([_make("", "REWARD", 5.0)]) == 5.0

    def test_maker_rebate_is_direct_credit(self):
        assert compute_pnl_today([_make("", "MAKER_REBATE", 0.50)]) == 0.50

    def test_taker_rebate_is_direct_credit(self):
        assert compute_pnl_today([_make("", "TAKER_REBATE", 0.25)]) == 0.25

    def test_referral_reward_is_direct_credit(self):
        assert compute_pnl_today([_make("", "REFERRAL_REWARD", 2.00)]) == 2.00

    def test_rebate_combined_with_sell_pnl(self):
        activity = [
            _make("BUY",  "TRADE", 100.0, size=1000.0),
            _make("SELL", "TRADE", 120.0, size=1000.0),   # +20
            _make("",     "MAKER_REBATE", 0.50),           # +0.50
        ]
        assert compute_pnl_today(activity) == 20.50


class TestCountTradesToday:
    def test_empty_returns_zero(self):
        assert count_trades_today([]) == 0

    def test_multiple_buys_same_market_count_as_one(self):
        # 4 BUYs for the same market window = 1 distinct market traded
        activity = [
            _make("BUY", "TRADE", 27.30,  size=27.86,  title="BTC Up or Down 1:50-1:55"),
            _make("BUY", "TRADE",  4.90,  size=5.00,   title="BTC Up or Down 1:50-1:55"),
            _make("BUY", "TRADE", 422.80, size=431.43, title="BTC Up or Down 1:50-1:55"),
            _make("BUY", "TRADE",  49.00, size=50.00,  title="BTC Up or Down 1:50-1:55"),
        ]
        assert count_trades_today(activity) == 1

    def test_buy_and_redeem_same_market_count_as_one(self):
        activity = [
            _make("BUY", "TRADE",   504.0, size=514.29, title="BTC Up or Down 1:50-1:55"),
            _make("",    "REDEEM",  514.29, size=514.29, title="BTC Up or Down 1:50-1:55"),
        ]
        assert count_trades_today(activity) == 1

    def test_two_different_markets_count_as_two(self):
        activity = [
            _make("BUY", "TRADE", 100.0, size=100.0, title="BTC Up or Down 1:50-1:55"),
            _make("BUY", "TRADE", 200.0, size=200.0, title="BTC Up or Down 1:05-1:10"),
        ]
        assert count_trades_today(activity) == 2

    def test_five_markets_with_multiple_events_each(self):
        markets = [f"BTC Window {i}" for i in range(5)]
        activity = [
            _make("BUY",    "TRADE",  100.0, title=m)
            for m in markets
            for _ in range(3)   # 3 BUYs per market
        ] + [
            _make("", "REDEEM", 110.0, title=m) for m in markets
        ]
        assert count_trades_today(activity) == 5

    def test_yesterday_markets_excluded(self):
        activity = [
            _make("BUY", "TRADE", 100.0, title="Yesterday Market", ts=_ts_yesterday()),
            _make("BUY", "TRADE", 100.0, title="Today Market"),
        ]
        assert count_trades_today(activity) == 1

    def test_events_with_no_title_excluded(self):
        activity = [
            _make("", "MAKER_REBATE", 0.50, title=""),  # rebate, no market title
            _make("BUY", "TRADE", 100.0, title="Real Market"),
        ]
        assert count_trades_today(activity) == 1


class TestTodayDateCt:
    def test_returns_date(self):
        from datetime import date
        result = today_date_ct()
        assert isinstance(result, date)
