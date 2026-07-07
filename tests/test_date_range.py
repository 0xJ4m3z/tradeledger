"""Tests for app/services/date_range.py.

Covers: DateRangeSelection model, normalize_record_datetime, calculate_date_range,
filter_records_by_date, filter_closed_by_selection, filter_snapshots_by_selection.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.models import ResolvedPosition
from app.services.date_range import (
    DateRangeSelection,
    calculate_date_range,
    filter_closed_by_selection,
    filter_records_by_date,
    filter_snapshots_by_selection,
    normalize_record_datetime,
)

_UTC = timezone.utc
_ET  = ZoneInfo("America/New_York")

# ── Fixed reference times ─────────────────────────────────────────────────────
# Anchor: 2025-03-15 noon ET → 17:00 UTC
_NOW_ET  = datetime(2025, 3, 15, 12, 0, 0, tzinfo=_ET)
_NOW_UTC = _NOW_ET.astimezone(_UTC)
_TODAY   = date(2025, 3, 15)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _epoch(d: date, hour: int = 12) -> int:
    return int(datetime(d.year, d.month, d.day, hour, 0, 0, tzinfo=_ET).timestamp())


def _closed(closed_at: int | None = None, resolved_date: str | None = None) -> ResolvedPosition:
    return ResolvedPosition(
        market="Test Market",
        outcome_held="YES",
        winning_outcome="YES",
        quantity=100,
        cost_basis=50.0,
        redeem_value=100.0,
        redeemed=True,
        closed_at=closed_at,
        resolved_date=resolved_date,
    )


def _snap(captured_at: str, value: float = 1000.0) -> dict:
    return {"captured_at": captured_at, "total_tracked_value": value}


# ── DateRangeSelection model ──────────────────────────────────────────────────

class TestDateRangeSelection:
    def test_preset_range_lowercases(self):
        sel = DateRangeSelection.preset_range("1M")
        assert sel.preset == "1m"
        assert sel.mode == "preset"

    def test_custom_range_stores_dates(self):
        start = date(2025, 1, 1)
        end   = date(2025, 1, 31)
        sel   = DateRangeSelection.custom_range(start, end)
        assert sel.mode == "custom"
        assert sel.start == start
        assert sel.end   == end

    def test_is_all_true_for_preset_all(self):
        assert DateRangeSelection.preset_range("all").is_all()

    def test_is_all_false_for_1d(self):
        assert not DateRangeSelection.preset_range("1d").is_all()

    def test_is_all_false_for_custom(self):
        sel = DateRangeSelection.custom_range(date(2025, 1, 1), date(2025, 1, 7))
        assert not sel.is_all()

    def test_is_preset(self):
        assert DateRangeSelection.preset_range("1w").is_preset()
        assert not DateRangeSelection.custom_range(date(2025, 1, 1), date(2025, 1, 7)).is_preset()

    def test_is_custom(self):
        sel = DateRangeSelection.custom_range(date(2025, 1, 1), date(2025, 1, 7))
        assert sel.is_custom()
        assert not DateRangeSelection.preset_range("1m").is_custom()

    def test_frozen(self):
        sel = DateRangeSelection.preset_range("1d")
        with pytest.raises((AttributeError, TypeError)):
            sel.preset = "1w"  # type: ignore[misc]

    def test_display_label_same_day(self):
        d = date(2025, 3, 15)
        sel = DateRangeSelection.custom_range(d, d)
        assert sel.display_label() == "Mar 15"

    def test_display_label_range(self):
        sel = DateRangeSelection.custom_range(date(2025, 3, 1), date(2025, 3, 15))
        label = sel.display_label()
        assert "Mar 01" in label or "Mar 1" in label
        assert "Mar 15" in label
        assert "–" in label

    def test_display_label_preset(self):
        sel = DateRangeSelection.preset_range("all")
        assert "All" in sel.display_label()


# ── normalize_record_datetime ─────────────────────────────────────────────────

class TestNormalizeRecordDatetime:
    def test_epoch_int(self):
        epoch = int(datetime(2025, 3, 15, 12, 0, 0, tzinfo=_UTC).timestamp())
        dt = normalize_record_datetime(epoch)
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt.year == 2025

    def test_epoch_float(self):
        epoch = float(int(datetime(2025, 3, 15, 12, 0, 0, tzinfo=_UTC).timestamp()))
        dt = normalize_record_datetime(epoch)
        assert dt is not None

    def test_iso_string_naive(self):
        dt = normalize_record_datetime("2025-03-15T12:00:00")
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt.year == 2025

    def test_iso_string_with_tz(self):
        dt = normalize_record_datetime("2025-03-15T12:00:00+00:00")
        assert dt is not None
        assert dt.year == 2025

    def test_date_object(self):
        d = date(2025, 3, 15)
        dt = normalize_record_datetime(d)
        assert dt is not None
        assert dt.date() == d

    def test_datetime_naive_becomes_utc(self):
        naive = datetime(2025, 3, 15, 12, 0, 0)
        dt = normalize_record_datetime(naive)
        assert dt is not None
        assert dt.tzinfo == _UTC

    def test_datetime_aware_preserved(self):
        aware = datetime(2025, 3, 15, 12, 0, 0, tzinfo=_ET)
        dt = normalize_record_datetime(aware)
        assert dt is not None
        assert dt.tzinfo is not None

    def test_none_returns_none(self):
        assert normalize_record_datetime(None) is None

    def test_bool_returns_none(self):
        assert normalize_record_datetime(True) is None
        assert normalize_record_datetime(False) is None

    def test_garbage_string_returns_none(self):
        assert normalize_record_datetime("not-a-date") is None

    def test_string_epoch_parsed(self):
        epoch = int(datetime(2025, 3, 15, 12, 0, 0, tzinfo=_UTC).timestamp())
        dt = normalize_record_datetime(str(epoch))
        assert dt is not None
        assert dt.year == 2025


# ── calculate_date_range ──────────────────────────────────────────────────────

class TestCalculateDateRange:
    def test_all_returns_none_none(self):
        sel = DateRangeSelection.preset_range("all")
        start, end = calculate_date_range(sel, now=_NOW_ET)
        assert start is None and end is None

    def test_1d_is_today(self):
        sel = DateRangeSelection.preset_range("1d")
        start, end = calculate_date_range(sel, now=_NOW_ET)
        assert start == _TODAY
        assert end   == _TODAY

    def test_1w_is_7_days_back(self):
        sel = DateRangeSelection.preset_range("1w")
        start, end = calculate_date_range(sel, now=_NOW_ET)
        assert start == _TODAY - timedelta(days=7)
        assert end   == _TODAY

    def test_1m_is_30_days_back(self):
        sel = DateRangeSelection.preset_range("1m")
        start, end = calculate_date_range(sel, now=_NOW_ET)
        assert start == _TODAY - timedelta(days=30)

    def test_1y_is_365_days_back(self):
        sel = DateRangeSelection.preset_range("1y")
        start, end = calculate_date_range(sel, now=_NOW_ET)
        assert start == _TODAY - timedelta(days=365)

    def test_ytd_starts_jan_1(self):
        sel = DateRangeSelection.preset_range("ytd")
        start, end = calculate_date_range(sel, now=_NOW_ET)
        assert start == date(_TODAY.year, 1, 1)
        assert end   == _TODAY

    def test_custom_passthrough(self):
        s = date(2025, 1, 10)
        e = date(2025, 2, 20)
        sel = DateRangeSelection.custom_range(s, e)
        start, end = calculate_date_range(sel, now=_NOW_ET)
        assert start == s
        assert end   == e

    def test_now_defaults_to_real_time(self):
        sel = DateRangeSelection.preset_range("1d")
        start, end = calculate_date_range(sel)  # no now= arg
        assert start is not None
        assert start <= end


# ── filter_records_by_date ────────────────────────────────────────────────────

class TestFilterRecordsByDate:
    def _records(self, epochs):
        return [{"ts": e, "label": str(i)} for i, e in enumerate(epochs)]

    def _getter(self, rec):
        return rec["ts"]

    def test_all_returns_all(self):
        records = self._records([_epoch(_TODAY - timedelta(days=i)) for i in range(5)])
        sel = DateRangeSelection.preset_range("all")
        assert filter_records_by_date(records, sel, self._getter) == records

    def test_excludes_before_start(self):
        old_epoch = _epoch(_TODAY - timedelta(days=10))
        new_epoch = _epoch(_TODAY)
        sel = DateRangeSelection.custom_range(_TODAY - timedelta(days=3), _TODAY)
        result = filter_records_by_date(
            [{"ts": old_epoch}, {"ts": new_epoch}], sel, self._getter
        )
        assert len(result) == 1
        assert result[0]["ts"] == new_epoch

    def test_excludes_after_end(self):
        future_epoch = _epoch(_TODAY + timedelta(days=5))
        in_range_epoch = _epoch(_TODAY - timedelta(days=1))
        sel = DateRangeSelection.custom_range(_TODAY - timedelta(days=7), _TODAY)
        result = filter_records_by_date(
            [{"ts": future_epoch}, {"ts": in_range_epoch}], sel, self._getter
        )
        assert len(result) == 1
        assert result[0]["ts"] == in_range_epoch

    def test_inclusive_boundaries(self):
        start = _TODAY - timedelta(days=5)
        end   = _TODAY
        records = [{"ts": _epoch(start)}, {"ts": _epoch(end)}]
        sel = DateRangeSelection.custom_range(start, end)
        result = filter_records_by_date(records, sel, self._getter)
        assert len(result) == 2

    def test_same_day_custom_range(self):
        d = _TODAY - timedelta(days=3)
        on_day   = _epoch(d)
        off_day  = _epoch(d - timedelta(days=1))
        sel = DateRangeSelection.custom_range(d, d)
        result = filter_records_by_date(
            [{"ts": on_day}, {"ts": off_day}], sel, self._getter
        )
        assert len(result) == 1

    def test_missing_date_excluded_in_preset(self):
        records = [{"ts": None}]
        sel = DateRangeSelection.preset_range("1d")
        result = filter_records_by_date(records, sel, self._getter)
        assert result == []

    def test_missing_date_included_in_all(self):
        records = [{"ts": None}]
        sel = DateRangeSelection.preset_range("all")
        result = filter_records_by_date(records, sel, self._getter)
        assert result == records

    def test_empty_list(self):
        sel = DateRangeSelection.custom_range(_TODAY - timedelta(days=7), _TODAY)
        assert filter_records_by_date([], sel, self._getter) == []


# ── filter_closed_by_selection ────────────────────────────────────────────────

class TestFilterClosedBySelection:
    def _make(self, days_ago: int) -> ResolvedPosition:
        d = _TODAY - timedelta(days=days_ago)
        return _closed(closed_at=_epoch(d))

    def test_all_returns_full_list(self):
        positions = [self._make(i) for i in range(5)]
        sel = DateRangeSelection.preset_range("all")
        assert filter_closed_by_selection(positions, sel) == positions

    def test_custom_range_single_day(self):
        target = _TODAY - timedelta(days=3)
        p_in   = _closed(closed_at=_epoch(target))
        p_out  = _closed(closed_at=_epoch(target - timedelta(days=1)))
        sel = DateRangeSelection.custom_range(target, target)
        result = filter_closed_by_selection([p_in, p_out], sel)
        assert p_in in result
        assert p_out not in result

    def test_custom_range_multi_day(self):
        start = _TODAY - timedelta(days=7)
        end   = _TODAY - timedelta(days=3)
        inside = _closed(closed_at=_epoch(start + timedelta(days=1)))
        before = _closed(closed_at=_epoch(start - timedelta(days=1)))
        after  = _closed(closed_at=_epoch(end   + timedelta(days=1)))
        sel = DateRangeSelection.custom_range(start, end)
        result = filter_closed_by_selection([inside, before, after], sel)
        assert inside in result
        assert before not in result
        assert after  not in result

    def test_custom_inclusive_on_start_boundary(self):
        start = _TODAY - timedelta(days=5)
        p = _closed(closed_at=_epoch(start))
        sel = DateRangeSelection.custom_range(start, _TODAY)
        assert p in filter_closed_by_selection([p], sel)

    def test_custom_inclusive_on_end_boundary(self):
        p = _closed(closed_at=_epoch(_TODAY))
        sel = DateRangeSelection.custom_range(_TODAY - timedelta(days=7), _TODAY)
        assert p in filter_closed_by_selection([p], sel)

    def test_missing_date_excluded_in_custom(self):
        p = _closed(closed_at=None, resolved_date=None)
        sel = DateRangeSelection.custom_range(_TODAY - timedelta(days=7), _TODAY)
        assert filter_closed_by_selection([p], sel) == []

    def test_missing_date_included_in_all(self):
        p = _closed(closed_at=None, resolved_date=None)
        sel = DateRangeSelection.preset_range("all")
        assert p in filter_closed_by_selection([p], sel)

    def test_falls_back_to_resolved_date(self):
        d = _TODAY - timedelta(days=2)
        p = _closed(closed_at=None, resolved_date=d.isoformat())
        sel = DateRangeSelection.custom_range(_TODAY - timedelta(days=7), _TODAY)
        result = filter_closed_by_selection([p], sel)
        assert p in result

    def test_preset_1d_delegates_correctly(self):
        real_today = datetime.now(_ET).date()
        today_p     = _closed(closed_at=_epoch(real_today))
        yesterday_p = _closed(closed_at=_epoch(real_today - timedelta(days=1)))
        sel = DateRangeSelection.preset_range("1d")
        result = filter_closed_by_selection([today_p, yesterday_p], sel)
        assert today_p in result
        assert yesterday_p not in result

    def test_empty_list(self):
        sel = DateRangeSelection.custom_range(_TODAY - timedelta(days=7), _TODAY)
        assert filter_closed_by_selection([], sel) == []


# ── filter_snapshots_by_selection ─────────────────────────────────────────────

class TestFilterSnapshotsBySelection:
    def _snap_at(self, d: date) -> dict:
        return _snap(datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=_UTC).isoformat())

    def test_all_returns_all(self):
        snaps = [self._snap_at(_TODAY - timedelta(days=i)) for i in range(5)]
        sel   = DateRangeSelection.preset_range("all")
        assert filter_snapshots_by_selection(snaps, sel) == snaps

    def test_custom_range_filters(self):
        start = _TODAY - timedelta(days=5)
        end   = _TODAY - timedelta(days=2)
        s_in  = self._snap_at(start + timedelta(days=1))
        s_out = self._snap_at(start - timedelta(days=1))
        sel   = DateRangeSelection.custom_range(start, end)
        result = filter_snapshots_by_selection([s_in, s_out], sel)
        assert s_in  in result
        assert s_out not in result

    def test_empty_list(self):
        sel = DateRangeSelection.custom_range(_TODAY - timedelta(days=7), _TODAY)
        assert filter_snapshots_by_selection([], sel) == []

    def test_preset_1w_excludes_old(self):
        real_today = datetime.now(_UTC).date()
        old    = self._snap_at(real_today - timedelta(days=10))
        recent = self._snap_at(real_today - timedelta(days=3))
        sel    = DateRangeSelection.preset_range("1w")
        result = filter_snapshots_by_selection([old, recent], sel)
        assert recent in result
        assert old not in result

    def test_ytd_includes_jan_1(self):
        real_today = datetime.now(_UTC).date()
        jan1  = self._snap_at(date(real_today.year, 1, 1))
        dec31 = self._snap_at(date(real_today.year - 1, 12, 31))
        sel   = DateRangeSelection.preset_range("ytd")
        result = filter_snapshots_by_selection([jan1, dec31], sel)
        assert jan1  in result
        assert dec31 not in result
