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


def _redeem(ts_dt, usdc_size, title="Market A"):
    return UserActivity(
        timestamp=_unix(ts_dt),
        type="REDEEM",
        title=title,
        outcome="Yes",
        side="",
        size=100.0,
        usdc_size=usdc_size,
        price=0.0,
    )


def _closed(pnl, redeem_value=None, resolved_date=None):
    if redeem_value is None:
        redeem_value = max(0.0, pnl + 50.0)
    cost_basis = redeem_value - pnl
    if resolved_date is None:
        resolved_date = str(_today())
    return ResolvedPosition(
        market="Test Market",
        outcome_held="Yes",
        winning_outcome="Yes" if pnl >= 0 else "No",
        quantity=100.0,
        cost_basis=cost_basis,
        redeem_value=redeem_value,
        redeemed=True,
        resolved_date=resolved_date,
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
        acts = [_redeem(t1, 75.0), _redeem(t2, 90.0)]
        cps  = [_closed(25.0, 75.0), _closed(40.0, 90.0)]
        points, _ = build_cumulative_pnl_points(acts, cps, "1d")
        ts_list = [p["timestamp"] for p in points]
        assert ts_list == sorted(ts_list)


# ── 1D: intraday event timestamps ─────────────────────────────────────────────

class TestBuild1DIntraday:
    def test_redeem_event_creates_point_at_its_timestamp(self):
        t = _et(9, 42)
        acts = [_redeem(t, 75.0)]
        cps  = [_closed(25.0, 75.0)]
        points, _ = build_cumulative_pnl_points(acts, cps, "1d")
        # midnight + event + now = 3
        assert len(points) == 3
        mid = points[1]
        mid_local = mid["timestamp"].astimezone(_ET)
        assert mid_local.hour == 9
        assert mid_local.minute == 42

    def test_multiple_events_create_multiple_points(self):
        acts = [_redeem(_et(9, 42), 75.0), _redeem(_et(10, 13), 90.0), _redeem(_et(11, 5), 60.0)]
        cps  = [_closed(25.0, 75.0), _closed(40.0, 90.0), _closed(10.0, 60.0)]
        points, _ = build_cumulative_pnl_points(acts, cps, "1d")
        # anchor + 3 events + now = 5
        assert len(points) == 5

    def test_same_day_events_not_aggregated_into_one_bucket(self):
        """Two events 30 minutes apart produce two separate chart points."""
        t1, t2 = _et(9, 0), _et(9, 30)
        acts = [_redeem(t1, 75.0), _redeem(t2, 90.0)]
        cps  = [_closed(25.0, 75.0), _closed(40.0, 90.0)]
        points, _ = build_cumulative_pnl_points(acts, cps, "1d")
        assert len(points) == 4   # anchor + 2 events + now

    def test_single_event_produces_three_points(self):
        acts = [_redeem(_et(10, 0), 75.0)]
        cps  = [_closed(25.0, 75.0)]
        points, _ = build_cumulative_pnl_points(acts, cps, "1d")
        assert len(points) == 3
        assert points[0]["value"] == 0.0
        assert abs(points[1]["value"] - 25.0) < 0.01

    def test_values_are_cumulative_not_per_event(self):
        acts = [_redeem(_et(9, 0), 75.0), _redeem(_et(10, 0), 90.0)]
        cps  = [_closed(30.0, 75.0), _closed(20.0, 90.0)]
        points, _ = build_cumulative_pnl_points(acts, cps, "1d")
        assert abs(points[1]["value"] - 30.0) < 0.01   # after first event
        assert abs(points[2]["value"] - 50.0) < 0.01   # after second event

    def test_final_point_matches_sum_of_all_closed(self):
        acts = [_redeem(_et(9, 0), 75.0), _redeem(_et(11, 0), 40.0)]
        cps  = [_closed(25.0, 75.0), _closed(-10.0, 40.0)]
        expected = 25.0 + (-10.0)
        points, _ = build_cumulative_pnl_points(acts, cps, "1d")
        assert abs(points[-1]["value"] - expected) < 0.01

    def test_yesterday_events_excluded_from_1d(self):
        yesterday = _today() - timedelta(days=1)
        t_yest = datetime(yesterday.year, yesterday.month, yesterday.day, 9, 0, tzinfo=_ET)
        acts = [_redeem(t_yest, 75.0)]
        cps  = [_closed(25.0, 75.0, resolved_date=str(yesterday))]
        points, _ = build_cumulative_pnl_points(acts, cps, "1d")
        # No events today → just midnight + now at $0
        assert len(points) == 2
        assert points[-1]["value"] == 0.0


# ── 1D: partial detection ─────────────────────────────────────────────────────

class TestBuild1DPartial:
    def test_not_partial_when_all_matched(self):
        acts = [_redeem(_et(9, 0), 75.0)]
        cps  = [_closed(25.0, 75.0)]
        _, is_partial = build_cumulative_pnl_points(acts, cps, "1d")
        assert not is_partial

    def test_partial_when_closed_has_no_matching_redeem(self):
        """Expired worthless: redeem_value=0, no REDEEM event in activity."""
        cps = [_closed(-50.0, redeem_value=0.0)]
        _, is_partial = build_cumulative_pnl_points([], cps, "1d")
        assert is_partial

    def test_partial_when_redeem_has_no_matching_closed(self):
        """REDEEM event with usdc_size that matches no closed position."""
        acts = [_redeem(_et(9, 0), 999.0)]   # no closed position with redeem_value=999
        _, is_partial = build_cumulative_pnl_points(acts, [], "1d")
        assert is_partial

    def test_partial_when_only_some_events_matched(self):
        acts = [_redeem(_et(9, 0), 75.0), _redeem(_et(10, 0), 999.0)]
        cps  = [_closed(25.0, 75.0)]   # second REDEEM has no match
        _, is_partial = build_cumulative_pnl_points(acts, cps, "1d")
        assert is_partial


# ── 1D: data source rules ─────────────────────────────────────────────────────

class TestBuild1DDataSource:
    def test_market_title_does_not_create_chart_points(self):
        """Title strings (even date-like) must not influence which timestamps are used."""
        t = _et(9, 42)
        # Title contains a past date — must NOT generate a chart point at that date
        act = _redeem(t, 75.0, title="Will BTC hit $100k by Jan 1 2020?")
        cp  = _closed(25.0, 75.0)
        points, _ = build_cumulative_pnl_points([act], [cp], "1d")
        assert len(points) == 3
        mid_local = points[1]["timestamp"].astimezone(_ET)
        assert mid_local.hour == 9
        assert mid_local.minute == 42

    def test_slug_utc_text_does_not_affect_timestamps(self):
        """Slug-style UTC strings in title must not be parsed as chart timestamps."""
        t = _et(10, 0)
        act = _redeem(t, 75.0, title="btc-100k-2020-01-01T00:00:00Z")
        cp  = _closed(25.0, 75.0)
        points, _ = build_cumulative_pnl_points([act], [cp], "1d")
        assert len(points) == 3
        mid_local = points[1]["timestamp"].astimezone(_ET)
        assert mid_local.hour == 10

    def test_non_redeem_activity_types_ignored(self):
        """TRADE BUY events must not create chart points."""
        buy = UserActivity(
            timestamp=_unix(_et(9, 0)),
            type="TRADE", title="Market A", outcome="Yes",
            side="BUY", size=100.0, usdc_size=50.0, price=0.5,
        )
        cp = _closed(25.0, 75.0)
        points, _ = build_cumulative_pnl_points([buy], [cp], "1d")
        # BUY event is not a REDEEM → unmatched closed → partial, but no event point
        # anchor + now = 2 data points (the buy event adds no chart point)
        event_points = [p for p in points[1:-1]]  # exclude anchor and now
        assert len(event_points) == 0


# ── 1D: SELL event handling (CLOB position exits) ────────────────────────────

def _sell(ts_dt, usdc_size, title="Market A"):
    """CLOB sell event (type='SELL', side='SELL')."""
    return UserActivity(
        timestamp=_unix(ts_dt),
        type="SELL",
        title=title,
        outcome="Yes",
        side="SELL",
        size=100.0,
        usdc_size=usdc_size,
        price=0.0,
    )


def _trade_sell(ts_dt, usdc_size, title="Market A"):
    """CLOB sell as TRADE event with side=SELL (alternate API format)."""
    return UserActivity(
        timestamp=_unix(ts_dt),
        type="TRADE",
        title=title,
        outcome="Yes",
        side="SELL",
        size=100.0,
        usdc_size=usdc_size,
        price=0.0,
    )


class TestBuild1DSellEvents:
    """CLOB sell events must create intraday chart points, just like REDEEM events."""

    def test_sell_event_creates_chart_point(self):
        t = _et(10, 30)
        act = _sell(t, usdc_size=75.0)
        cp  = _closed(25.0, 75.0)
        points, _ = build_cumulative_pnl_points([act], [cp], "1d")
        # anchor + sell event + now = 3
        assert len(points) == 3
        mid_local = points[1]["timestamp"].astimezone(_ET)
        assert mid_local.hour == 10
        assert mid_local.minute == 30

    def test_trade_sell_event_creates_chart_point(self):
        """type='TRADE', side='SELL' is also a close event."""
        t = _et(14, 0)
        act = _trade_sell(t, usdc_size=90.0)
        cp  = _closed(40.0, 90.0)
        points, _ = build_cumulative_pnl_points([act], [cp], "1d")
        assert len(points) == 3
        assert abs(points[1]["value"] - 40.0) < 0.01

    def test_trade_buy_event_still_ignored(self):
        """type='TRADE', side='BUY' must NOT create a chart point."""
        buy = UserActivity(
            timestamp=_unix(_et(9, 0)),
            type="TRADE", title="Market A", outcome="Yes",
            side="BUY", size=100.0, usdc_size=50.0, price=0.5,
        )
        cp = _closed(25.0, 75.0)
        points, _ = build_cumulative_pnl_points([buy], [cp], "1d")
        assert len(points) == 2   # anchor + now only (no event point)

    def test_sell_and_redeem_mixed_both_create_points(self):
        """A mix of SELL and REDEEM events should each create an intraday point."""
        acts = [
            _redeem(_et(9, 30), 75.0, title="Market A"),
            _sell(_et(11, 0),   90.0, title="Market B"),
        ]
        cps = [
            _closed(25.0, 75.0),
            _closed(40.0, 90.0),
        ]
        points, is_partial = build_cumulative_pnl_points(acts, cps, "1d")
        # anchor + 2 events + now = 4
        assert len(points) == 4
        assert not is_partial
        assert abs(points[1]["value"] - 25.0) < 0.01
        assert abs(points[2]["value"] - 65.0) < 0.01

    def test_title_based_match_avoids_ambiguity(self):
        """When two positions have identical redeem_value, title match picks the right one."""
        t1 = _et(9, 0)
        t2 = _et(10, 0)
        # Both positions have redeem_value=75.0 — title disambiguates
        acts = [
            _sell(t1, 75.0, title="Market A"),
            _sell(t2, 75.0, title="Market B"),
        ]
        cp_a = ResolvedPosition(
            market="Market A", outcome_held="Yes", winning_outcome="Yes",
            quantity=100.0, cost_basis=50.0, redeem_value=75.0,
            redeemed=True, resolved_date=str(_today()),
        )
        cp_b = ResolvedPosition(
            market="Market B", outcome_held="No", winning_outcome="No",
            quantity=100.0, cost_basis=60.0, redeem_value=75.0,
            redeemed=True, resolved_date=str(_today()),
        )
        points, is_partial = build_cumulative_pnl_points(acts, [cp_a, cp_b], "1d")
        assert not is_partial
        assert len(points) == 4  # anchor + 2 events + now
        # First event should match cp_a (pnl = 75 - 50 = 25)
        assert abs(points[1]["value"] - 25.0) < 0.01
        # Second event should match cp_b (pnl = 75 - 60 = 15, cumulative = 40)
        assert abs(points[2]["value"] - 40.0) < 0.01

    def test_partial_when_sell_has_no_matching_closed_position(self):
        """An unmatched SELL event marks the data as partial."""
        acts = [_sell(_et(10, 0), 999.0)]  # no closed position with redeem_value=999
        _, is_partial = build_cumulative_pnl_points(acts, [], "1d")
        assert is_partial

    def test_sell_value_within_tolerance_still_matches(self):
        """Minor floating-point difference (< _MATCH_TOL) must not break matching."""
        t = _et(11, 0)
        # usdc_size = 75.009, redeem_value = 75.0 → diff = 0.009 < 0.02 tolerance
        act_titled = UserActivity(
            timestamp=_unix(t), type="SELL", title="Market A", outcome="Yes",
            side="SELL", size=100.0, usdc_size=75.009, price=0.0,
        )
        cp_exact = ResolvedPosition(
            market="Market A", outcome_held="Yes", winning_outcome="Yes",
            quantity=100.0, cost_basis=50.0, redeem_value=75.0,
            redeemed=True, resolved_date=str(_today()),
        )
        points, is_partial = build_cumulative_pnl_points([act_titled], [cp_exact], "1d")
        assert not is_partial
        assert len(points) == 3


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
