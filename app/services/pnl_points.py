"""
Event-based cumulative realized P/L series builder.

For 1D: intraday granularity using the closed_at timestamp embedded in each
  closed position (extracted from the API's ``timestamp`` field).  Each closed
  position whose close time falls within the current ET day contributes one
  cumulative step.  Positions that lack a ``closed_at`` value (older cache rows
  fetched before this field was added) are placed at "now" and the series is
  flagged partial.

  Activity events are NOT used for 1D timing.  This makes the chart robust to
  any close mechanism — market redemption, CLOB sell, CTF merge, or anything
  else — because all close types appear in the closed-positions endpoint.

For 1W / 1M / 1Y / YTD / All: daily rollup from closed positions.
  One cumulative step per calendar day with a "now" endpoint appended.

Returns:
  (List[{"timestamp": aware_datetime, "value": float}], is_partial: bool)

Timestamps in the returned list are always timezone-aware (America/New_York
by default).  "value" is the running cumulative realized P/L at that moment.
The first point is always the range start at $0; the last is always "now".
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from app.debug import _dlog
from app.models import ResolvedPosition, UserActivity
from app.services.pnl_today import filter_closed_by_range, range_cutoff_et


# ── Helpers ────────────────────────────────────────────────────────────────────

def _midnight(d: date, tz: ZoneInfo) -> datetime:
    return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=tz)


def _cp_date_str(cp: ResolvedPosition) -> Optional[str]:
    return cp.resolved_date[:10] if cp.resolved_date else None


# ── 1D intraday ────────────────────────────────────────────────────────────────

def _build_1d_points(
    activity: List[UserActivity],
    closed: List[ResolvedPosition],
    tz: ZoneInfo,
) -> Tuple[List[Dict[str, Any]], bool]:
    now = datetime.now(tz)
    today = now.date()
    today_str = today.isoformat()
    midnight = _midnight(today, tz)

    # Filter to positions whose close event falls on today in the given timezone.
    # Primary:  use closed_at epoch (the API's "timestamp" field for the close event).
    # Fallback: use resolved_date[:10] when closed_at is absent (legacy cache rows).
    today_closed: List[ResolvedPosition] = []
    for cp in closed:
        if cp.closed_at:
            if datetime.fromtimestamp(cp.closed_at, tz=tz).date() == today:
                today_closed.append(cp)
        elif _cp_date_str(cp) == today_str:
            today_closed.append(cp)

    # Sort ascending by close time; positions without closed_at sort last (placed at now)
    today_closed.sort(key=lambda cp: cp.closed_at or int(now.timestamp()) + 1)

    _dlog("chart1d",
          "today_closed=%d | with_closed_at=%d | fallback=%d",
          len(today_closed),
          sum(1 for cp in today_closed if cp.closed_at),
          sum(1 for cp in today_closed if not cp.closed_at))

    points: List[Dict[str, Any]] = [{"timestamp": midnight, "value": 0.0}]
    cumulative = 0.0
    is_partial = False

    for cp in today_closed:
        cumulative = round(cumulative + cp.realized_pnl, 2)
        if cp.closed_at:
            ts = datetime.fromtimestamp(cp.closed_at, tz=tz)
        else:
            # No timestamp available — approximate as "now" and flag as partial
            ts = now
            is_partial = True
        points.append({"timestamp": ts, "value": cumulative})

    # Always end at "now" so the line extends to the current moment
    points.append({"timestamp": now, "value": cumulative})

    _dlog("chart1d",
          "points=%d | cumulative=%.2f | is_partial=%s",
          len(points), cumulative, is_partial)

    return points, is_partial


# ── 1W / 1M / 1Y / YTD / All daily rollup ─────────────────────────────────────

def _build_range_points(
    closed: List[ResolvedPosition],
    range_: str,
    tz: ZoneInfo,
) -> Tuple[List[Dict[str, Any]], bool]:
    now = datetime.now(tz)
    filtered = filter_closed_by_range(closed, range_)

    # Aggregate realized P/L by calendar date
    daily: Dict[date, float] = {}
    for cp in filtered:
        d_str = _cp_date_str(cp)
        if not d_str:
            continue
        try:
            d = date.fromisoformat(d_str)
        except ValueError:
            continue
        daily[d] = round(daily.get(d, 0.0) + cp.realized_pnl, 6)

    sorted_days = sorted(daily.keys())

    # Anchor: range cutoff date (midnight) for fixed ranges; day before oldest for "all"
    cutoff = range_cutoff_et(range_)  # returns date or None
    if cutoff is not None:
        anchor_dt = _midnight(cutoff, tz)
    elif sorted_days:
        anchor_dt = _midnight(sorted_days[0] - timedelta(days=1), tz)
    else:
        return [], False  # "all" range with no data

    points: List[Dict[str, Any]] = [{"timestamp": anchor_dt, "value": 0.0}]
    cumulative = 0.0

    for d in sorted_days:
        cumulative = round(cumulative + daily[d], 2)
        points.append({"timestamp": _midnight(d, tz), "value": cumulative})

    # Append a "now" endpoint so the line extends to the current moment
    points.append({"timestamp": now, "value": cumulative})

    return points, False  # partial detection for 1W+ comes from pnl_today.is_data_partial


# ── Public API ─────────────────────────────────────────────────────────────────

def build_cumulative_pnl_points(
    activity: List[UserActivity],
    closed_positions: List[ResolvedPosition],
    range_key: str,
    timezone: str = "America/New_York",
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Build ordered cumulative realized P/L chart points for the given range.

    Parameters
    ----------
    activity        : reserved; not used for any range (kept for API compatibility)
    closed_positions: closed positions list (source of P/L amounts and timestamps)
    range_key       : "1d" | "1w" | "1m" | "1y" | "ytd" | "all"
    timezone        : IANA timezone name (default: America/New_York)

    Returns
    -------
    (points, is_partial)
      points      — list of {"timestamp": aware_datetime, "value": float}
                    • First point : range start at $0
                    • Middle points: one per close event in chronological order
                    • Last point  : "now" at final cumulative P/L
      is_partial  — True when some 1D positions lack a closed_at timestamp
                    (1D only; always False for 1W+)

    For 1D: uses closed_positions[i].closed_at for intraday timestamps.
            Works for any close type (REDEEM, SELL, MERGE, etc.).
    For 1W+: daily rollup from closed positions (partial detection via
             pnl_today.is_data_partial, not this function).
    """
    tz = ZoneInfo(timezone)
    if range_key == "1d":
        return _build_1d_points(activity, closed_positions, tz)
    return _build_range_points(closed_positions, range_key, tz)
