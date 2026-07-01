"""Tests for range/timezone logic, partial data detection, and filter_closed_by_range."""

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.models import ResolvedPosition
from app.services.pnl_today import (
    filter_closed_by_range,
    is_data_partial,
    range_cutoff_et,
    today_date_et,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _pos(resolved_date: str, pnl: float = 10.0) -> ResolvedPosition:
    return ResolvedPosition(
        market="Test Market",
        outcome_held="Yes",
        winning_outcome="Yes",
        quantity=100,
        cost_basis=50.0,
        redeem_value=50.0 + pnl,
        redeemed=True,
        resolved_date=resolved_date,
    )


def _today_et():
    """Return today in ET without calling the real function (for test isolation)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/New_York")).date()


# ── range_cutoff_et ────────────────────────────────────────────────────────────

class TestRangeCutoffEt:
    def test_1d_is_today(self):
        today = _today_et()
        assert range_cutoff_et("1d") == today

    def test_1w_is_7_days_ago(self):
        today = _today_et()
        assert range_cutoff_et("1w") == today - timedelta(days=7)

    def test_1m_is_30_days_ago(self):
        today = _today_et()
        assert range_cutoff_et("1m") == today - timedelta(days=30)

    def test_1y_is_365_days_ago(self):
        today = _today_et()
        assert range_cutoff_et("1y") == today - timedelta(days=365)

    def test_ytd_is_jan_1(self):
        today = _today_et()
        assert range_cutoff_et("ytd") == date(today.year, 1, 1)

    def test_all_returns_none(self):
        assert range_cutoff_et("all") is None

    def test_unknown_key_returns_none(self):
        assert range_cutoff_et("bogus") is None


# ── today_date_et ──────────────────────────────────────────────────────────────

class TestTodayDateEt:
    def test_returns_a_date(self):
        result = today_date_et()
        assert isinstance(result, date)

    def test_uses_new_york_timezone(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        expected = datetime.now(ZoneInfo("America/New_York")).date()
        assert today_date_et() == expected


# ── filter_closed_by_range ────────────────────────────────────────────────────

class TestFilterClosedByRange:
    def setup_method(self):
        today = _today_et()
        self.today    = str(today)
        self.yest     = str(today - timedelta(days=1))
        self.week_ago = str(today - timedelta(days=7))
        self.month_ago = str(today - timedelta(days=30))
        self.old      = str(today - timedelta(days=400))

    def test_all_returns_everything(self):
        positions = [_pos(self.today), _pos(self.old)]
        assert filter_closed_by_range(positions, "all") == positions

    def test_1d_includes_today(self):
        p = _pos(self.today)
        result = filter_closed_by_range([p], "1d")
        assert p in result

    def test_1d_excludes_yesterday(self):
        p = _pos(self.yest)
        result = filter_closed_by_range([p], "1d")
        assert p not in result

    def test_1w_includes_7_days_ago(self):
        p = _pos(self.week_ago)
        result = filter_closed_by_range([p], "1w")
        assert p in result

    def test_1w_excludes_8_days_ago(self):
        today = _today_et()
        p = _pos(str(today - timedelta(days=8)))
        result = filter_closed_by_range([p], "1w")
        assert p not in result

    def test_1m_includes_30_days_ago(self):
        p = _pos(self.month_ago)
        result = filter_closed_by_range([p], "1m")
        assert p in result

    def test_1m_excludes_31_days_ago(self):
        today = _today_et()
        p = _pos(str(today - timedelta(days=31)))
        result = filter_closed_by_range([p], "1m")
        assert p not in result

    def test_1y_includes_365_days_ago(self):
        today = _today_et()
        p = _pos(str(today - timedelta(days=365)))
        result = filter_closed_by_range([p], "1y")
        assert p in result

    def test_1y_excludes_366_days_ago(self):
        today = _today_et()
        p = _pos(str(today - timedelta(days=366)))
        result = filter_closed_by_range([p], "1y")
        assert p not in result

    def test_ytd_includes_jan_1_this_year(self):
        today = _today_et()
        jan1 = str(date(today.year, 1, 1))
        p = _pos(jan1)
        result = filter_closed_by_range([p], "ytd")
        assert p in result

    def test_ytd_excludes_dec_31_last_year(self):
        today = _today_et()
        dec31 = str(date(today.year - 1, 12, 31))
        p = _pos(dec31)
        result = filter_closed_by_range([p], "ytd")
        assert p not in result

    def test_skips_missing_resolved_date(self):
        p = ResolvedPosition(
            market="X", outcome_held="Yes", winning_outcome="Yes",
            quantity=1, cost_basis=1.0, redeem_value=1.0,
            redeemed=True, resolved_date=None,
        )
        result = filter_closed_by_range([p], "1d")
        assert result == []

    def test_skips_bad_date_string(self):
        p = ResolvedPosition(
            market="X", outcome_held="Yes", winning_outcome="Yes",
            quantity=1, cost_basis=1.0, redeem_value=1.0,
            redeemed=True, resolved_date="not-a-date",
        )
        result = filter_closed_by_range([p], "1m")
        assert result == []

    def test_uses_date_prefix_only(self):
        # resolved_date may include time info; only the first 10 chars (YYYY-MM-DD) matter
        today = _today_et()
        p = ResolvedPosition(
            market="X", outcome_held="Yes", winning_outcome="Yes",
            quantity=1, cost_basis=1.0, redeem_value=2.0,
            redeemed=True,
            resolved_date=f"{today}T12:00:00Z",
        )
        result = filter_closed_by_range([p], "1d")
        assert p in result

    def test_empty_input_returns_empty(self):
        assert filter_closed_by_range([], "1w") == []


# ── is_data_partial ────────────────────────────────────────────────────────────

class TestIsDataPartial:
    def setup_method(self):
        today = _today_et()
        self.today    = str(today)
        self.yest     = str(today - timedelta(days=1))
        self.week_ago = str(today - timedelta(days=7))
        self.old      = str(today - timedelta(days=60))

    def test_all_is_never_partial(self):
        positions = [_pos(self.today)]
        assert not is_data_partial(positions, "all")

    def test_empty_list_is_not_partial(self):
        assert not is_data_partial([], "1d")
        assert not is_data_partial([], "1w")

    def test_partial_when_oldest_is_in_range(self):
        # Only have today's record; for 1w, oldest (today) >= 7-days-ago cutoff → partial
        positions = [_pos(self.today)]
        assert is_data_partial(positions, "1w")

    def test_not_partial_when_oldest_predates_cutoff(self):
        # oldest record is 60 days ago, which is before the 1w/1m cutoff
        positions = [_pos(self.today), _pos(self.old)]
        assert not is_data_partial(positions, "1w")
        assert not is_data_partial(positions, "1m")

    def test_partial_for_1d_when_oldest_is_today(self):
        # Only today's record — can't tell if earlier today's records were missed
        # (in practice they exist since data is newest-first, but the logic stays consistent)
        positions = [_pos(self.today)]
        assert is_data_partial(positions, "1d")

    def test_not_partial_for_1d_when_oldest_is_yesterday(self):
        positions = [_pos(self.today), _pos(self.yest)]
        assert not is_data_partial(positions, "1d")

    def test_partial_for_1y_when_oldest_within_year(self):
        today = _today_et()
        six_months = str(today - timedelta(days=180))
        positions = [_pos(self.today), _pos(six_months)]
        assert is_data_partial(positions, "1y")

    def test_not_partial_for_1y_when_oldest_predates_year(self):
        today = _today_et()
        old = str(today - timedelta(days=400))
        positions = [_pos(self.today), _pos(old)]
        assert not is_data_partial(positions, "1y")

    def test_partial_for_ytd_when_oldest_within_this_year(self):
        today = _today_et()
        feb1 = str(date(today.year, 2, 1))
        positions = [_pos(feb1)]
        result = is_data_partial(positions, "ytd")
        # Feb 1 >= Jan 1 → partial (unless today is before Feb 1, edge case)
        if today >= date(today.year, 2, 1):
            assert result
        # else: data goes back to start of range, so not partial

    def test_not_partial_for_ytd_when_oldest_is_last_year(self):
        today = _today_et()
        last_year = str(date(today.year - 1, 12, 31))
        positions = [_pos(self.today), _pos(last_year)]
        assert not is_data_partial(positions, "ytd")

    def test_skips_positions_without_resolved_date(self):
        none_date = ResolvedPosition(
            market="X", outcome_held="Yes", winning_outcome="Yes",
            quantity=1, cost_basis=1.0, redeem_value=1.0,
            redeemed=True, resolved_date=None,
        )
        # Only position has no date → can't determine oldest → not partial
        assert not is_data_partial([none_date], "1w")


# ── backward compat ────────────────────────────────────────────────────────────

def test_today_date_ct_alias():
    from app.services.pnl_today import today_date_ct
    assert today_date_ct() == today_date_et()
