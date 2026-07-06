"""Daily P/L aggregation and closed-position sorting utilities."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from app.models import ResolvedPosition
from app.services.pnl_today import filter_closed_by_range


def sort_closed_positions_newest_first(
    positions: List[ResolvedPosition],
) -> List[ResolvedPosition]:
    """Return a new list sorted newest-first.

    Sort priority:
    1. closed_at descending (epoch seconds — covers REDEEM, SELL, MERGE, any close type)
    2. resolved_date descending (ISO date string fallback for older cache rows)
    3. stable (relative order preserved for rows missing both fields)
    """
    def _key(p: ResolvedPosition):
        ca = p.closed_at or 0
        rd = p.resolved_date[:10] if p.resolved_date else ""
        return (ca, rd)

    return sorted(positions, key=_key, reverse=True)


def build_daily_pnl_rows(
    closed_positions: List[ResolvedPosition],
    range_: str,
    timezone: str = "America/New_York",
) -> List[Dict[str, Any]]:
    """Build one row per calendar day from closed positions in the given range.

    Returns a list of dicts (newest date first):
    {
        "date":       date,
        "pnl":        float,   # net realized P/L for the day
        "count":      int,     # number of closed positions on this day
        "wins":       int,
        "losses":     int,
        "cumulative": float,   # running total from oldest day through this day
    }

    Positions without a date (no closed_at or resolved_date) are excluded.
    """
    tz = ZoneInfo(timezone)
    filtered = filter_closed_by_range(closed_positions, range_)

    daily: Dict[date, Dict[str, Any]] = {}
    for p in filtered:
        d = _close_date(p, tz)
        if d is None:
            continue
        if d not in daily:
            daily[d] = {"pnl": 0.0, "count": 0, "wins": 0, "losses": 0}
        daily[d]["pnl"] += p.realized_pnl
        daily[d]["count"] += 1
        if p.realized_pnl > 0:
            daily[d]["wins"] += 1
        else:
            daily[d]["losses"] += 1

    if not daily:
        return []

    sorted_days = sorted(daily.keys())  # oldest → newest for cumulative calculation
    cumulative = 0.0
    rows = []
    for d in sorted_days:
        cumulative = round(cumulative + daily[d]["pnl"], 2)
        rows.append({
            "date":       d,
            "pnl":        round(daily[d]["pnl"], 2),
            "count":      daily[d]["count"],
            "wins":       daily[d]["wins"],
            "losses":     daily[d]["losses"],
            "cumulative": cumulative,
        })

    rows.reverse()  # newest first for display
    return rows


def get_positions_for_date(
    positions: List[ResolvedPosition],
    target_date: date,
    timezone: str = "America/New_York",
) -> List[ResolvedPosition]:
    """Return positions whose close date matches target_date, sorted newest-first.

    Date matching mirrors build_daily_pnl_rows: closed_at epoch converted to
    ET calendar date first, resolved_date string fallback for legacy rows.
    """
    tz = ZoneInfo(timezone)
    matched = [p for p in positions if _close_date(p, tz) == target_date]
    return sort_closed_positions_newest_first(matched)


def _close_date(p: ResolvedPosition, tz: ZoneInfo) -> Optional[date]:
    """Extract the close date, preferring closed_at epoch over resolved_date string."""
    if p.closed_at:
        try:
            return datetime.fromtimestamp(p.closed_at, tz=tz).date()
        except (OSError, OverflowError, ValueError):
            pass
    if p.resolved_date:
        try:
            return date.fromisoformat(p.resolved_date[:10])
        except (ValueError, TypeError):
            pass
    return None
