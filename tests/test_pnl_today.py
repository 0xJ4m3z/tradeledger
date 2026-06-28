"""
Tests for app/services/pnl_today.py.
Verifies CT-day boundary logic, credit/debit classification, and rounding.
"""

from datetime import datetime, timezone, timedelta

import pytest

from app.models import UserActivity
from app.services.pnl_today import compute_pnl_today, today_date_ct


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ct_now_ts() -> int:
    """Approximate Unix timestamp for right now in CT (UTC-6 fixed offset)."""
    # Use UTC-6 fixed offset so tests pass regardless of system timezone
    ct = timezone(timedelta(hours=-6))
    return int(datetime.now(tz=ct).replace(hour=12, minute=0, second=0, microsecond=0).timestamp())


def _yesterday_ts() -> int:
    ct = timezone(timedelta(hours=-6))
    return int((datetime.now(tz=ct) - timedelta(days=1)).replace(
        hour=12, minute=0, second=0, microsecond=0
    ).timestamp())


def _make(side: str, type_: str, usdc: float, ts: int | None = None) -> UserActivity:
    return UserActivity(
        timestamp=ts if ts is not None else _ct_now_ts(),
        type=type_,
        title="Test Market",
        outcome="Yes",
        side=side,
        size=0.0,
        usdc_size=usdc,
        price=0.0,
    )


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestComputePnlToday:
    def test_empty_activity_returns_zero(self):
        assert compute_pnl_today([]) == 0.0

    def test_buy_is_debit(self):
        a = _make("BUY", "TRADE", 50.0)
        assert compute_pnl_today([a]) == -50.0

    def test_sell_is_credit(self):
        a = _make("SELL", "TRADE", 80.0)
        assert compute_pnl_today([a]) == 80.0

    def test_redeem_is_credit(self):
        a = _make("", "REDEEM", 100.0)
        assert compute_pnl_today([a]) == 100.0

    def test_reward_is_credit(self):
        a = _make("", "REWARD", 5.0)
        assert compute_pnl_today([a]) == 5.0

    def test_maker_rebate_is_credit(self):
        a = _make("", "MAKER_REBATE", 0.50)
        assert compute_pnl_today([a]) == 0.50

    def test_taker_rebate_is_credit(self):
        a = _make("", "TAKER_REBATE", 0.25)
        assert compute_pnl_today([a]) == 0.25

    def test_referral_reward_is_credit(self):
        a = _make("", "REFERRAL_REWARD", 2.00)
        assert compute_pnl_today([a]) == 2.00

    def test_net_buy_sell(self):
        activity = [
            _make("BUY",  "TRADE", 100.0),
            _make("SELL", "TRADE", 120.0),
        ]
        assert compute_pnl_today(activity) == 20.0

    def test_negative_net(self):
        activity = [
            _make("BUY",  "TRADE", 200.0),
            _make("SELL", "TRADE", 150.0),
        ]
        assert compute_pnl_today(activity) == -50.0

    def test_yesterday_events_excluded(self):
        yesterday = _yesterday_ts()
        activity = [
            _make("SELL", "TRADE", 100.0, ts=yesterday),
            _make("BUY",  "TRADE",  50.0),
        ]
        assert compute_pnl_today(activity) == -50.0

    def test_mixed_today_and_yesterday(self):
        yesterday = _yesterday_ts()
        activity = [
            _make("BUY",  "TRADE", 100.0, ts=yesterday),   # excluded
            _make("SELL", "TRADE",  60.0),                  # +60
            _make("BUY",  "TRADE",  20.0),                  # -20
            _make("",     "REDEEM", 15.0),                  # +15
        ]
        assert compute_pnl_today(activity) == 55.0

    def test_rounding_to_two_decimals(self):
        activity = [
            _make("SELL", "TRADE", 0.001),
            _make("SELL", "TRADE", 0.004),
        ]
        result = compute_pnl_today(activity)
        assert result == round(result, 2)

    def test_unknown_type_ignored(self):
        a = _make("", "SPLIT", 999.0)
        assert compute_pnl_today([a]) == 0.0


class TestTodayDateCt:
    def test_returns_date(self):
        from datetime import date
        result = today_date_ct()
        assert isinstance(result, date)
