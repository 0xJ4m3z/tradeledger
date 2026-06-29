"""Tests for pnl_points.build_cumulative_pnl_points."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models import ResolvedPosition, UserActivity
from app.services.pnl_points import build_cumulative_pnl_points

_ET = ZoneInfo("America/New_York")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _today():
    return datetime.now(_ET).date()


def _midnight():
    d = _today()
    return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=_ET)


def _et(hour, minute=0):
    """Timezone-aware datetime for today at hour:minute in ET."""
    d = _today()
    return datetime(d.year, d.month, d.day, hour, minute, 0, tzinfo=_ET)


def _unix(dt):
    return int(dt.timestamp())


def _closed(pnl, redeem_value=None, resolved_date=None, closed_at=None, market="Test Market"):
    if redeem_value is None:
        redeem_value = max(0.0, pnl + 50.0)
    cost_basis = redeem_value - pnl
    if resolved_date is None:
        resolved_date = str(_today())
    return ResolvedPosition(
        market=market,
        outcome_held="Yes",
        winning_outcome="Yes" if pnl >= 0 else "No",
        quantity=100.0,
        cost_basis=cost_basis,
        redeem_value=redeem_value,
        redeemed=True,
        resolved_date=resolved_date,
        closed_at=closed_at,
    )


# ── 1D: anchoring and structure ────────────────────────────────────────────────

class TestBuild1DAnchoring:
    def test_first_point_is_midnight_et_at_zero(self):
        points, _ = build_cumulative_pnl_points([], [], "1d")
        first = points[0]
        assert first["value"] == 0.0
        assert first["timestamp"].date() == _today()
        assert first["timestamp"].hour == 0
        assert first["timestamp"].minute == 0
        assert first["timestamp"].second == 0
        assert first["timestamp"].tzinfo is not None

    def test_no_data_produces_two_points_both_zero(self):
        points, is_partial = build_cumulative_pnl_points([], [], "1d")
        assert len(points) == 2
        assert points[0]["value"] == 0.0
        assert points[1]["value"] == 0.0
        assert not is_partial

    def test_last_point_is_close_to_now(self):
        points, _ = build_cumulative_pnl_points([], [], "1d")
        now = datetime.now(_ET)
        diff = abs((now - points[-1]["timestamp"].astimezone(_ET)).total_seconds())
        assert diff < 5   # within 5 seconds of test execution

    def test_points_are_in_chronological_order(self):
        t1 = _et(14, 0)
        t2 = _et(9, 0)   # earlier but listed second
        cps = [
            _closed(25.0, 75.0, closed_at=_unix(t1)),
            _closed(40.0, 90.0, closed_at=_unix(t2)),
        ]
        points, _ = build_cumulative_pnl_points([], cps, "1d")
        ts_list = [p["timestamp"] for p in points]
        assert ts_list == sorted(ts_list)


# ── 1D: intraday timestamps from closed_at ─────────────────────────────────────

class TestBuild1DIntraday:
    def test_closed_at_creates_point_at_its_timestamp(self):
        t = _et(9, 42)
        cp = _closed(25.0, 75.0, closed_at=_unix(t))
        points, _ = build_cumulative_pnl_points([], [cp], "1d")
        # anchor + position + now = 3
        assert len(points) == 3
        mid = points[1]
        mid_local = mid["timestamp"].astimezone(_ET)
        assert mid_local.hour == 9
        assert mid_local.minute == 42

    def test_multiple_positions_create_multiple_points(self):
        cps = [
            _closed(25.0, 75.0, closed_at=_unix(_et(9, 42))),
            _closed(40.0, 90.0, closed_at=_unix(_et(10, 13))),
            _closed(10.0, 60.0, closed_at=_unix(_et(11, 5))),
        ]
        points, _ = build_cumulative_pnl_points([], cps, "1d")
        # anchor + 3 positions + now = 5
        assert len(points) == 5

    def test_same_day_positions_not_aggregated_into_one_bucket(self):
        """Two positions 30 minutes apart produce two separate chart points."""
        cps = [
            _closed(25.0, 75.0, closed_at=_unix(_et(9, 0))),
            _closed(40.0, 90.0, closed_at=_unix(_et(9, 30))),
        ]
        points, _ = build_cumulative_pnl_points([], cps, "1d")
        assert len(points) == 4   # anchor + 2 positions + now

    def test_single_position_produces_three_points(self):
        cp = _closed(25.0, 75.0, closed_at=_unix(_et(10, 0)))
        points, _ = build_cumulative_pnl_points([], [cp], "1d")
        assert len(points) == 3
        assert points[0]["value"] == 0.0
        assert abs(points[1]["value"] - 25.0) < 0.01

    def test_values_are_cumulative_not_per_position(self):
        cps = [
            _closed(30.0, 75.0, closed_at=_unix(_et(9, 0))),
            _closed(20.0, 90.0, closed_at=_unix(_et(10, 0))),
        ]
        points, _ = build_cumulative_pnl_points([], cps, "1d")
        assert abs(points[1]["value"] - 30.0) < 0.01   # after first close
        assert abs(points[2]["value"] - 50.0) < 0.01   # after second close

    def test_final_point_matches_sum_of_all_closed(self):
        cps = [
            _closed(25.0, 75.0, closed_at=_unix(_et(9, 0))),
            _closed(-10.0, 40.0, closed_at=_unix(_et(11, 0))),
        ]
        expected = 25.0 + (-10.0)
        points, _ = build_cumulative_pnl_points([], cps, "1d")
        assert abs(points[-1]["value"] - expected) < 0.01

    def test_yesterday_positions_excluded_from_1d(self):
        yesterday = _today() - timedelta(days=1)
        t_yest = datetime(yesterday.year, yesterday.month, yesterday.day, 9, 0, tzinfo=_ET)
        cp = _closed(25.0, 75.0, resolved_date=str(yesterday), closed_at=_unix(t_yest))
        points, _ = build_cumulative_pnl_points([], [cp], "1d")
        # No positions today → just anchor + now at $0
        assert len(points) == 2
        assert points[-1]["value"] == 0.0

    def test_positions_sorted_by_closed_at_regardless_of_input_order(self):
        """Input order must not affect chart — positions are always sorted by closed_at."""
        cps = [
            _closed(40.0, 90.0, closed_at=_unix(_et(10, 0))),  # listed first but later
            _closed(25.0, 75.0, closed_at=_unix(_et(9, 0))),   # listed second but earlier
        ]
        points, _ = build_cumulative_pnl_points([], cps, "1d")
        # After sorting: 09:00 position first → cumulative=25, then 10:00 → cumulative=65
        assert abs(points[1]["value"] - 25.0) < 0.01
        assert abs(points[2]["value"] - 65.0) < 0.01


# ── 1D: partial detection ─────────────────────────────────────────────────────

class TestBuild1DPartial:
    def test_not_partial_when_all_have_closed_at(self):
        cp = _closed(25.0, 75.0, closed_at=_unix(_et(9, 0)))
        _, is_partial = build_cumulative_pnl_points([], [cp], "1d")
        assert not is_partial

    def test_partial_when_position_has_no_closed_at(self):
        """Position without closed_at cannot be precisely timed → partial."""
        cp = _closed(25.0, 75.0, closed_at=None)  # resolved_date fallback, no timestamp
        _, is_partial = build_cumulative_pnl_points([], [cp], "1d")
        assert is_partial

    def test_partial_when_only_some_positions_have_closed_at(self):
        cps = [
            _closed(25.0, 75.0, closed_at=_unix(_et(9, 0))),
            _closed(10.0, 60.0, closed_at=None),   # no timestamp
        ]
        _, is_partial = build_cumulative_pnl_points([], cps, "1d")
        assert is_partial

    def test_no_data_is_not_partial(self):
        _, is_partial = build_cumulative_pnl_points([], [], "1d")
        assert not is_partial


# ── 1D: data source rules ─────────────────────────────────────────────────────

class TestBuild1DDataSource:
    def test_closed_at_drives_timestamp_not_resolved_date(self):
        """closed_at epoch determines the chart point's time, not resolved_date."""
        t = _et(9, 42)
        cp = _closed(25.0, 75.0, closed_at=_unix(t))
        points, _ = build_cumulative_pnl_points([], [cp], "1d")
        assert len(points) == 3
        mid_local = points[1]["timestamp"].astimezone(_ET)
        assert mid_local.hour == 9
        assert mid_local.minute == 42

    def test_activity_events_do_not_create_chart_points(self):
        """Activity list is ignored entirely — no REDEEM event creates a chart point."""
        redeem = UserActivity(
            timestamp=_unix(_et(9, 0)),
            type="REDEEM", title="Market A", outcome="Yes",
            side="", size=100.0, usdc_size=75.0, price=0.0,
        )
        # No closed positions → no chart points even with REDEEM activity
        points, _ = build_cumulative_pnl_points([redeem], [], "1d")
        assert len(points) == 2   # anchor + now only

    def test_fallback_to_resolved_date_when_closed_at_absent(self):
        """Positions without closed_at are included via resolved_date fallback."""
        cp = _closed(25.0, 75.0, closed_at=None)  # resolved_date defaults to today
        points, is_partial = build_cumulative_pnl_points([], [cp], "1d")
        # Position IS included (via resolved_date), but partial because no timestamp
        assert len(points) == 3   # anchor + position (at now) + now
        assert is_partial


# ── 1D: close-type independence ───────────────────────────────────────────────

class TestBuild1DCloseTypes:
    """Chart works the same regardless of how the position was closed (REDEEM/SELL/MERGE)."""

    def test_any_closed_position_creates_chart_point(self):
        """closed_at-based approach: no special-casing by close mechanism."""
        t = _et(10, 30)
        # Label the market as a merge-closed position (the chart doesn't care)
        cp = _closed(25.0, 75.0, closed_at=_unix(t), market="Merge-closed market")
        points, _ = build_cumulative_pnl_points([], [cp], "1d")
        assert len(points) == 3
        mid_local = points[1]["timestamp"].astimezone(_ET)
        assert mid_local.hour == 10
        assert mid_local.minute == 30

    def test_multiple_close_types_all_produce_points(self):
        """Redeem, CLOB sell, and merge-closed positions each produce their own point."""
        cps = [
            _closed(25.0, 75.0, closed_at=_unix(_et(9, 30)), market="Market A (redeemed)"),
            _closed(40.0, 90.0, closed_at=_unix(_et(11, 0)), market="Market B (CLOB sold)"),
            _closed(-5.0, 45.0, closed_at=_unix(_et(14, 0)), market="Market C (merged)"),
        ]
        points, is_partial = build_cumulative_pnl_points([], cps, "1d")
        # anchor + 3 positions + now = 5
        assert len(points) == 5
        assert not is_partial
        assert abs(points[1]["value"] - 25.0) < 0.01
        assert abs(points[2]["value"] - 65.0) < 0.01
        assert abs(points[3]["value"] - 60.0) < 0.01

    def test_activity_argument_completely_ignored_for_1d(self):
        """Passing non-empty activity must not change the chart."""
        activities = [
            UserActivity(
                timestamp=_unix(_et(9, 0)), type="REDEEM", title="Market A",
                outcome="Yes", side="", size=100.0, usdc_size=75.0, price=0.0,
            ),
            UserActivity(
                timestamp=_unix(_et(10, 0)), type="SELL", title="Market B",
                outcome="No", side="SELL", size=50.0, usdc_size=30.0, price=0.0,
            ),
        ]
        cp = _closed(20.0, 60.0, closed_at=_unix(_et(11, 0)))
        points_with_activity, _ = build_cumulative_pnl_points(activities, [cp], "1d")
        points_without, _ = build_cumulative_pnl_points([], [cp], "1d")
        assert len(points_with_activity) == len(points_without)
        for a, b in zip(points_with_activity, points_without):
            assert abs(a["value"] - b["value"]) < 0.01

    def test_closed_at_for_today_filters_correctly(self):
        """Only today's positions appear; yesterday and tomorrow are excluded."""
        yesterday = _today() - timedelta(days=1)
        t_yest = datetime(yesterday.year, yesterday.month, yesterday.day, 15, 0, tzinfo=_ET)
        cps = [
            _closed(99.0, 149.0, closed_at=_unix(t_yest)),          # yesterday → excluded
            _closed(25.0, 75.0,  closed_at=_unix(_et(10, 0))),      # today → included
        ]
        points, _ = build_cumulative_pnl_points([], cps, "1d")
        # Only 1 position today → anchor + 1 + now = 3
        assert len(points) == 3
        assert abs(points[-1]["value"] - 25.0) < 0.01


# ── 1W / 1M / 1Y / YTD / All ─────────────────────────────────────────────────

class TestBuildRanges:
    def test_1w_anchor_is_7_days_ago_midnight(self):
        today = _today()
        cp = _closed(50.0, resolved_date=str(today))
        points, _ = build_cumulative_pnl_points([], [cp], "1w")
        anchor_date = points[0]["timestamp"].astimezone(_ET).date()
        assert anchor_date == today - timedelta(days=7)
        assert points[0]["value"] == 0.0

    def test_1w_multiple_days_produce_multiple_points(self):
        today = _today()
        cps = [
            _closed(20.0, resolved_date=str(today - timedelta(days=5))),
            _closed(30.0, resolved_date=str(today - timedelta(days=3))),
            _closed(10.0, resolved_date=str(today)),
        ]
        points, _ = build_cumulative_pnl_points([], cps, "1w")
        # anchor + 3 days + now = 5
        assert len(points) == 5

    def test_1w_daily_values_cumulative(self):
        today = _today()
        cps = [
            _closed(20.0, resolved_date=str(today - timedelta(days=3))),
            _closed(30.0, resolved_date=str(today)),
        ]
        points, _ = build_cumulative_pnl_points([], cps, "1w")
        values = [p["value"] for p in points]
        assert values[0] == 0.0
        assert abs(values[1] - 20.0) < 0.01
        assert abs(values[2] - 50.0) < 0.01
        assert abs(values[-1] - 50.0) < 0.01

    def test_1m_excludes_positions_older_than_30_days(self):
        today = _today()
        cps = [
            _closed(999.0, resolved_date=str(today - timedelta(days=60))),
            _closed(50.0,  resolved_date=str(today)),
        ]
        points, _ = build_cumulative_pnl_points([], cps, "1m")
        assert abs(points[-1]["value"] - 50.0) < 0.01

    def test_1y_excludes_positions_older_than_365_days(self):
        today = _today()
        cps = [
            _closed(999.0, resolved_date=str(today - timedelta(days=400))),
            _closed(30.0,  resolved_date=str(today - timedelta(days=10))),
        ]
        points, _ = build_cumulative_pnl_points([], cps, "1y")
        assert abs(points[-1]["value"] - 30.0) < 0.01

    def test_all_range_anchor_is_one_day_before_oldest(self):
        cps = [
            _closed(10.0, resolved_date="2024-01-10"),
            _closed(20.0, resolved_date="2024-01-20"),
        ]
        points, _ = build_cumulative_pnl_points([], cps, "all")
        anchor_date = points[0]["timestamp"].astimezone(_ET).date()
        assert anchor_date.isoformat() == "2024-01-09"

    def test_all_range_no_data_returns_empty(self):
        points, is_partial = build_cumulative_pnl_points([], [], "all")
        assert points == []
        assert not is_partial

    def test_range_points_end_with_now(self):
        today = _today()
        cps = [_closed(50.0, resolved_date=str(today - timedelta(days=3)))]
        points, _ = build_cumulative_pnl_points([], cps, "1w")
        now = datetime.now(_ET)
        diff = abs((now - points[-1]["timestamp"].astimezone(_ET)).total_seconds())
        assert diff < 5

    def test_1w_not_marked_partial(self):
        """Partial detection for 1W+ comes from pnl_today.is_data_partial, not here."""
        today = _today()
        cps = [_closed(10.0, resolved_date=str(today))]
        _, is_partial = build_cumulative_pnl_points([], cps, "1w")
        assert not is_partial

    def test_same_day_positions_aggregated_for_1w(self):
        """For 1W+, multiple positions on the same day are summed into one daily step."""
        today = _today()
        cps = [
            _closed(20.0, resolved_date=str(today)),
            _closed(30.0, resolved_date=str(today)),
        ]
        points, _ = build_cumulative_pnl_points([], cps, "1w")
        # anchor + 1 aggregated day + now = 3 points
        assert len(points) == 3
        assert abs(points[1]["value"] - 50.0) < 0.01
