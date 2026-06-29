"""Tests for pnl_series.build_pnl_series — cumulative P/L chart data builder."""

from datetime import date, timedelta

import pytest

from app.models import ResolvedPosition
from app.services.pnl_series import build_pnl_series, _parse_date
from app.services.pnl_today import range_cutoff_et


# ── Helpers ────────────────────────────────────────────────────────────────────

def _closed(resolved_date: str, pnl: float) -> ResolvedPosition:
    cb = max(1.0, abs(pnl) + 10)
    rv = cb + pnl
    return ResolvedPosition(
        market="Test Market",
        outcome_held="Yes",
        winning_outcome="Yes" if pnl >= 0 else "No",
        quantity=100.0,
        cost_basis=cb,
        redeem_value=rv,
        redeemed=True,
        resolved_date=resolved_date,
    )


def _today():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/New_York")).date()


# ── _parse_date ────────────────────────────────────────────────────────────────

class TestParseDate:
    def test_plain_date(self):
        assert _parse_date("2024-06-15") == date(2024, 6, 15)

    def test_datetime_string(self):
        assert _parse_date("2024-06-15T12:30:00Z") == date(2024, 6, 15)

    def test_datetime_with_millis(self):
        assert _parse_date("2024-06-15T12:30:00.000Z") == date(2024, 6, 15)

    def test_none_returns_none(self):
        assert _parse_date(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_date("") is None

    def test_bad_string_returns_none(self):
        assert _parse_date("not-a-date") is None


# ── build_pnl_series ──────────────────────────────────────────────────────────

class TestBuildPnlSeries:
    def test_empty_closed_returns_anchor_only(self):
        x, y = build_pnl_series([], "1w")
        assert len(x) == 1
        assert y[0] == 0.0
        assert x[0] == range_cutoff_et("1w")

    def test_empty_all_range_returns_empty(self):
        x, y = build_pnl_series([], "all")
        assert x == []
        assert y == []

    def test_series_starts_at_zero(self):
        today = _today()
        pos = [_closed(str(today), 50.0)]
        x, y = build_pnl_series(pos, "1d")
        assert y[0] == 0.0

    def test_final_value_matches_pnl_card(self):
        """Last y value must equal sum(realized_pnl) for the same range."""
        today = _today()
        yest  = str(today - timedelta(days=1))
        positions = [
            _closed(str(today), 30.0),
            _closed(yest,       -10.0),
        ]
        x, y = build_pnl_series(positions, "1w")
        expected = sum(p.realized_pnl for p in positions)
        assert abs(y[-1] - expected) < 0.01

    def test_anchor_is_range_cutoff(self):
        today = _today()
        pos = [_closed(str(today), 20.0)]
        x, y = build_pnl_series(pos, "1m")
        cutoff = range_cutoff_et("1m")
        assert x[0] == cutoff

    def test_1d_anchor_is_today(self):
        today = _today()
        pos = [_closed(str(today), 5.0)]
        x, y = build_pnl_series(pos, "1d")
        assert x[0] == today

    def test_1w_anchor_is_7_days_ago(self):
        today = _today()
        week_ago = today - timedelta(days=7)
        pos = [_closed(str(today), 5.0)]
        x, y = build_pnl_series(pos, "1w")
        assert x[0] == week_ago

    def test_ytd_anchor_is_jan_1(self):
        today = _today()
        jan1 = date(today.year, 1, 1)
        pos = [_closed(str(today), 5.0)]
        x, y = build_pnl_series(pos, "ytd")
        assert x[0] == jan1

    def test_all_range_anchor_is_one_day_before_oldest(self):
        pos = [
            _closed("2024-01-10", 10.0),
            _closed("2024-01-20", 20.0),
        ]
        x, y = build_pnl_series(pos, "all")
        assert x[0] == date(2024, 1, 9)   # one day before oldest

    def test_single_data_point_produces_two_points(self):
        today = _today()
        pos = [_closed(str(today), 42.0)]
        x, y = build_pnl_series(pos, "1d")
        assert len(x) == 2
        assert y[0] == 0.0
        assert abs(y[1] - 42.0) < 0.01

    def test_cumulative_values_ascending_then_descending(self):
        today = _today()
        d1 = str(today - timedelta(days=3))
        d2 = str(today - timedelta(days=2))
        d3 = str(today - timedelta(days=1))
        positions = [
            _closed(d1,  50.0),
            _closed(d2, -20.0),
            _closed(d3,  10.0),
        ]
        x, y = build_pnl_series(positions, "1w")
        # Skip anchor y[0]=0
        assert abs(y[1] -  50.0) < 0.01
        assert abs(y[2] -  30.0) < 0.01
        assert abs(y[3] -  40.0) < 0.01

    def test_same_date_positions_are_aggregated(self):
        """Multiple positions on the same date → one net data point."""
        today = _today()
        positions = [
            _closed(str(today), 30.0),
            _closed(str(today), -10.0),
        ]
        x, y = build_pnl_series(positions, "1d")
        # anchor + 1 aggregated point
        assert len(x) == 2
        assert abs(y[-1] - 20.0) < 0.01

    def test_positions_outside_range_excluded(self):
        today = _today()
        old = str(today - timedelta(days=100))
        recent = str(today - timedelta(days=1))
        positions = [
            _closed(old,    999.0),   # outside 1W
            _closed(recent,  50.0),   # inside 1W
        ]
        x, y = build_pnl_series(positions, "1w")
        assert abs(y[-1] - 50.0) < 0.01   # only recent counted

    def test_all_unparseable_dates_treated_as_empty(self):
        pos = [
            ResolvedPosition(
                market="X", outcome_held="Yes", winning_outcome="Yes",
                quantity=1.0, cost_basis=1.0, redeem_value=2.0,
                redeemed=True, resolved_date="bad-date",
            )
        ]
        x, y = build_pnl_series(pos, "1w")
        assert len(x) == 1    # only anchor
        assert y[0] == 0.0

    def test_x_ascending(self):
        positions = [
            _closed("2024-06-20", 10.0),
            _closed("2024-06-10", 20.0),
            _closed("2024-06-15", -5.0),
        ]
        x, y = build_pnl_series(positions, "all")
        dates = x[1:]  # skip anchor
        assert dates == sorted(dates)

    def test_1y_range_excludes_older_positions(self):
        today = _today()
        very_old = str(today - timedelta(days=400))
        recent   = str(today - timedelta(days=10))
        positions = [
            _closed(very_old, 999.0),
            _closed(recent,    30.0),
        ]
        x, y = build_pnl_series(positions, "1y")
        assert abs(y[-1] - 30.0) < 0.01
