"""
Tests for filter_snapshots_by_range in chart_ranges.py.
Pure function — no Qt or display required.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.chart_ranges import RANGE_LABELS, filter_snapshots_by_range


def _snap(hours_ago: float, value: float = 100.0) -> dict:
    ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return {"captured_at": ts.isoformat(), "total_tracked_value": value}


def _naive_snap(hours_ago: float) -> dict:
    """Snapshot with naive (no tzinfo) datetime, as stored by SQLite."""
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).replace(tzinfo=None)
    return {"captured_at": ts.isoformat(), "total_tracked_value": 200.0}


# ── All ────────────────────────────────────────────────────────────────────────

class TestAll:
    def test_all_returns_every_snapshot(self):
        snaps = [_snap(0.5), _snap(50), _snap(500)]
        assert filter_snapshots_by_range(snaps, "All") == snaps

    def test_all_empty_input_returns_empty(self):
        assert filter_snapshots_by_range([], "All") == []

    def test_unknown_range_key_returns_all(self):
        snaps = [_snap(0.5), _snap(48)]
        assert filter_snapshots_by_range(snaps, "UNKNOWN") == snaps

    def test_unknown_range_key_empty_input_returns_empty(self):
        assert filter_snapshots_by_range([], "UNKNOWN") == []


# ── 1D ─────────────────────────────────────────────────────────────────────────

class TestOneDay:
    def test_keeps_snapshots_within_24_hours(self):
        snaps = [_snap(0.5), _snap(12), _snap(23.9)]
        result = filter_snapshots_by_range(snaps, "1D")
        assert len(result) == 3

    def test_excludes_snapshots_older_than_24_hours(self):
        snaps = [_snap(0.5), _snap(24.1), _snap(200)]
        result = filter_snapshots_by_range(snaps, "1D")
        assert len(result) == 1
        assert result[0] is snaps[0]

    def test_empty_input_returns_empty(self):
        assert filter_snapshots_by_range([], "1D") == []

    def test_no_snapshots_in_range_returns_empty(self):
        snaps = [_snap(48), _snap(100)]
        assert filter_snapshots_by_range(snaps, "1D") == []


# ── 1W ─────────────────────────────────────────────────────────────────────────

class TestOneWeek:
    def test_keeps_snapshots_within_7_days(self):
        snaps = [_snap(1), _snap(72), _snap(167)]    # all < 168h
        result = filter_snapshots_by_range(snaps, "1W")
        assert len(result) == 3

    def test_excludes_snapshots_older_than_7_days(self):
        snaps = [_snap(1), _snap(168.1), _snap(300)]
        result = filter_snapshots_by_range(snaps, "1W")
        assert len(result) == 1

    def test_empty_input_returns_empty(self):
        assert filter_snapshots_by_range([], "1W") == []


# ── 1M ─────────────────────────────────────────────────────────────────────────

class TestOneMonth:
    def test_keeps_snapshots_within_30_days(self):
        snaps = [_snap(1), _snap(300), _snap(719)]   # all < 720h
        result = filter_snapshots_by_range(snaps, "1M")
        assert len(result) == 3

    def test_excludes_snapshots_older_than_30_days(self):
        snaps = [_snap(1), _snap(720.1), _snap(1000)]
        result = filter_snapshots_by_range(snaps, "1M")
        assert len(result) == 1

    def test_empty_input_returns_empty(self):
        assert filter_snapshots_by_range([], "1M") == []


# ── Edge cases ─────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_naive_datetime_treated_as_utc(self):
        """SQLite stores timestamps without timezone info; treat as UTC."""
        snaps = [_naive_snap(1), _naive_snap(48)]
        result = filter_snapshots_by_range(snaps, "1D")
        assert len(result) == 1

    def test_malformed_timestamp_skipped_silently(self):
        snaps = [
            {"captured_at": "not-a-date", "total_tracked_value": 100.0},
            _snap(1),
        ]
        result = filter_snapshots_by_range(snaps, "1D")
        assert len(result) == 1   # malformed one skipped

    def test_missing_captured_at_key_skipped(self):
        snaps = [{"total_tracked_value": 100.0}, _snap(1)]
        result = filter_snapshots_by_range(snaps, "1D")
        assert len(result) == 1

    def test_single_snapshot_within_range(self):
        result = filter_snapshots_by_range([_snap(0.5)], "1D")
        assert len(result) == 1

    def test_single_snapshot_outside_range(self):
        result = filter_snapshots_by_range([_snap(48)], "1D")
        assert len(result) == 0

    def test_order_preserved(self):
        snaps = [_snap(5), _snap(3), _snap(1)]
        result = filter_snapshots_by_range(snaps, "1D")
        assert result == snaps   # order unchanged

    def test_values_unmodified(self):
        snap = _snap(1, value=9999.99)
        result = filter_snapshots_by_range([snap], "1D")
        assert result[0]["total_tracked_value"] == 9999.99


# ── 1Y ─────────────────────────────────────────────────────────────────────────

class TestOneYear:
    def test_keeps_snapshots_within_365_days(self):
        snaps = [_snap(1), _snap(24 * 180), _snap(24 * 364)]   # all within 365 days
        result = filter_snapshots_by_range(snaps, "1Y")
        assert len(result) == 3

    def test_excludes_snapshots_older_than_365_days(self):
        snaps = [_snap(1), _snap(24 * 365 + 1), _snap(24 * 500)]
        result = filter_snapshots_by_range(snaps, "1Y")
        assert len(result) == 1

    def test_lowercase_key(self):
        snaps = [_snap(1), _snap(24 * 400)]
        result = filter_snapshots_by_range(snaps, "1y")
        assert len(result) == 1

    def test_empty_input_returns_empty(self):
        assert filter_snapshots_by_range([], "1Y") == []


# ── YTD ────────────────────────────────────────────────────────────────────────

class TestYTD:
    def _ytd_snap(self, year_fraction: float) -> dict:
        """Snapshot from `year_fraction` of the way through the current year."""
        now = datetime.now(timezone.utc)
        jan1 = datetime(now.year, 1, 1, tzinfo=timezone.utc)
        dec31 = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
        year_seconds = (dec31 - jan1).total_seconds()
        ts = jan1 + timedelta(seconds=year_seconds * year_fraction)
        return {"captured_at": ts.isoformat(), "total_tracked_value": 100.0}

    def _last_year_snap(self) -> dict:
        """Snapshot from December of the previous year."""
        now = datetime.now(timezone.utc)
        ts = datetime(now.year - 1, 12, 15, tzinfo=timezone.utc)
        return {"captured_at": ts.isoformat(), "total_tracked_value": 100.0}

    def test_includes_snapshots_from_this_year(self):
        snaps = [self._ytd_snap(0.1), self._ytd_snap(0.5), self._ytd_snap(0.9)]
        result = filter_snapshots_by_range(snaps, "YTD")
        assert len(result) == 3

    def test_excludes_last_year_snapshots(self):
        snaps = [self._ytd_snap(0.5), self._last_year_snap()]
        result = filter_snapshots_by_range(snaps, "YTD")
        assert len(result) == 1
        assert result[0] is snaps[0]

    def test_lowercase_key(self):
        snaps = [self._ytd_snap(0.5), self._last_year_snap()]
        result = filter_snapshots_by_range(snaps, "ytd")
        assert len(result) == 1

    def test_empty_input_returns_empty(self):
        assert filter_snapshots_by_range([], "YTD") == []


# ── Case insensitivity ─────────────────────────────────────────────────────────

class TestCaseInsensitivity:
    def test_lowercase_1d(self):
        snaps = [_snap(1), _snap(48)]
        assert len(filter_snapshots_by_range(snaps, "1d")) == 1

    def test_lowercase_1w(self):
        snaps = [_snap(1), _snap(24 * 10)]
        assert len(filter_snapshots_by_range(snaps, "1w")) == 1

    def test_lowercase_1m(self):
        snaps = [_snap(1), _snap(24 * 35)]
        assert len(filter_snapshots_by_range(snaps, "1m")) == 1

    def test_lowercase_all(self):
        snaps = [_snap(1), _snap(24 * 400)]
        assert filter_snapshots_by_range(snaps, "all") == snaps


# ── RANGE_LABELS export ────────────────────────────────────────────────────────

class TestRangeLabels:
    def test_all_six_ranges_present(self):
        assert set(RANGE_LABELS.keys()) == {"1d", "1w", "1m", "1y", "ytd", "all"}

    def test_labels_are_display_strings(self):
        assert RANGE_LABELS["1d"]  == "1D"
        assert RANGE_LABELS["1w"]  == "1W"
        assert RANGE_LABELS["1m"]  == "1M"
        assert RANGE_LABELS["1y"]  == "1Y"
        assert RANGE_LABELS["ytd"] == "YTD"
        assert RANGE_LABELS["all"] == "All"
