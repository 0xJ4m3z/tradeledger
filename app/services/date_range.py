"""Date-range model and filter helpers for TradeLedger analytics tabs.

``DateRangeSelection`` is the canonical representation of a user-chosen range.
It supports both preset ranges (1d/1w/1m/1y/ytd/all) and arbitrary custom
From/To date ranges.

Filter helpers:
  filter_records_by_date   — generic; accepts a date_getter callable
  filter_closed_by_selection   — convenience wrapper for ResolvedPosition lists
  filter_activity_by_selection — convenience wrapper for UserActivity lists
  filter_snapshots_by_selection — convenience wrapper for snapshot dicts
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable, List, Optional, TypeVar

_ET = "America/New_York"


def _et_zone():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(_ET)
    except Exception:
        from datetime import timedelta as td
        return timezone(td(hours=-5))


# ── Model ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DateRangeSelection:
    """Immutable description of a user-selected date range.

    mode == "preset": one of 1d/1w/1m/1y/ytd/all (case-insensitive).
    mode == "custom": explicit start/end date fields (both inclusive).
    """
    mode:   str                    # "preset" or "custom"
    preset: Optional[str] = None   # "1d", "1w", "1m", "1y", "ytd", "all"
    start:  Optional[date] = None  # inclusive start (custom only)
    end:    Optional[date] = None  # inclusive end   (custom only)

    # ── Factory helpers ───────────────────────────────────────────────────

    @classmethod
    def preset_range(cls, preset: str) -> "DateRangeSelection":
        return cls(mode="preset", preset=preset.lower())

    @classmethod
    def custom_range(cls, start: date, end: date) -> "DateRangeSelection":
        return cls(mode="custom", start=start, end=end)

    # ── Predicates ────────────────────────────────────────────────────────

    def is_all(self) -> bool:
        return self.mode == "preset" and self.preset == "all"

    def is_preset(self) -> bool:
        return self.mode == "preset"

    def is_custom(self) -> bool:
        return self.mode == "custom"

    # ── Display ───────────────────────────────────────────────────────────

    def display_label(self) -> str:
        """Return a short human-readable label for this selection."""
        from app.services.chart_ranges import RANGE_LABELS
        if self.mode == "custom":
            if self.start and self.end:
                s = self.start.strftime("%b %d")
                e = self.end.strftime("%b %d")
                return s if self.start == self.end else f"{s} – {e}"
            return "Custom"
        return RANGE_LABELS.get(self.preset or "all", "All")


# ── Helpers ───────────────────────────────────────────────────────────────────

def normalize_record_datetime(value) -> Optional[datetime]:
    """Convert various date/timestamp representations to a UTC-aware datetime.

    Accepts: int/float epoch, ISO string, date, datetime (naive → UTC).
    Returns None on failure — never raises.
    """
    tz = timezone.utc
    if value is None:
        return None
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=tz)
        if isinstance(value, datetime):
            return value.replace(tzinfo=tz) if value.tzinfo is None else value.astimezone(tz)
        if isinstance(value, date):
            # date without time → midnight UTC
            return datetime(value.year, value.month, value.day, tzinfo=tz)
        if isinstance(value, str):
            try:
                return datetime.fromtimestamp(float(value), tz=tz)
            except (ValueError, OSError):
                pass
            dt = datetime.fromisoformat(value)
            return dt.replace(tzinfo=tz) if dt.tzinfo is None else dt.astimezone(tz)
    except (OSError, OverflowError, ValueError, TypeError):
        pass
    return None


def calculate_date_range(
    selection: DateRangeSelection,
    now: Optional[datetime] = None,
) -> tuple:
    """Return (start_date, end_date) in ET for a DateRangeSelection.

    Both dates are inclusive calendar dates. Returns (None, None) for "all".
    """
    tz = _et_zone()
    if now is None:
        now = datetime.now(tz)
    else:
        now = now.astimezone(tz)
    today = now.date()

    if selection.mode == "custom":
        return selection.start, selection.end

    preset = (selection.preset or "all").lower()
    if preset == "all":
        return None, None
    if preset == "1d":
        return today, today
    if preset == "1w":
        return today - timedelta(days=7), today
    if preset == "1m":
        return today - timedelta(days=30), today
    if preset == "1y":
        return today - timedelta(days=365), today
    if preset == "ytd":
        return date(today.year, 1, 1), today
    return None, None


T = TypeVar("T")


def filter_records_by_date(
    records: List[T],
    selection: DateRangeSelection,
    date_getter: Callable[[T], Optional[object]],
) -> List[T]:
    """Filter records to those within the DateRangeSelection.

    date_getter(record) should return a date, datetime, int/float epoch, or
    ISO string. Records where date_getter returns None/unparseable are:
      - included  when selection.is_all()
      - excluded  for all other ranges (silently, never crashes)

    Comparison uses ET calendar dates.
    """
    if selection.is_all():
        return list(records)

    start_date, end_date = calculate_date_range(selection)
    if start_date is None and end_date is None:
        return list(records)

    tz = _et_zone()
    result = []
    for rec in records:
        raw = date_getter(rec)
        if raw is None:
            continue
        dt = normalize_record_datetime(raw)
        if dt is None:
            continue
        rec_date = dt.astimezone(tz).date()
        if start_date is not None and rec_date < start_date:
            continue
        if end_date is not None and rec_date > end_date:
            continue
        result.append(rec)
    return result


# ── Convenience wrappers ──────────────────────────────────────────────────────

def filter_closed_by_selection(closed: list, selection: DateRangeSelection) -> list:
    """Filter ResolvedPosition list by a DateRangeSelection.

    For preset ranges delegates to filter_closed_by_range (preserving the
    existing 1D strict-equality rule). For custom ranges uses
    filter_records_by_date with the closed_at/resolved_date fields.
    """
    from app.services.pnl_today import filter_closed_by_range

    if selection.is_all():
        return closed
    if selection.is_preset():
        return filter_closed_by_range(closed, selection.preset)

    def _date_getter(p):
        return p.closed_at or p.resolved_date or None

    return filter_records_by_date(closed, selection, _date_getter)


def filter_activity_by_selection(activity: list, selection: DateRangeSelection) -> list:
    """Filter UserActivity list by a DateRangeSelection."""
    from app.services.pnl_today import filter_activity_by_range

    if selection.is_all():
        return list(activity)
    if selection.is_preset():
        return filter_activity_by_range(activity, selection.preset)

    def _date_getter(a):
        return getattr(a, "timestamp", None)

    return filter_records_by_date(activity, selection, _date_getter)


def filter_snapshots_by_selection(snapshots: list, selection: DateRangeSelection) -> list:
    """Filter snapshot dicts by a DateRangeSelection.

    Snapshot dicts have a 'captured_at' ISO string (UTC).
    For preset ranges delegates to filter_snapshots_by_range.
    """
    from app.services.chart_ranges import filter_snapshots_by_range

    if selection.is_all():
        return snapshots
    if selection.is_preset():
        return filter_snapshots_by_range(snapshots, selection.preset)

    def _date_getter(s):
        return s.get("captured_at")

    return filter_records_by_date(snapshots, selection, _date_getter)
