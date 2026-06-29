"""
Event-based cumulative realized P/L series builder.

For 1D: intraday granularity using REDEEM activity timestamps.
  Each REDEEM is matched to a closed position by redeem_value (usdc_size ≈
  redeem_value) to obtain the realized P/L for that event.  Events with no
  matching closed position are skipped and data is marked partial.  Closed
  positions with no matching REDEEM (e.g. expired worthless) are also partial.

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

# USDC tolerance for matching a close event to a closed position.
# Slightly above 0.01 to absorb minor floating-point rounding in API responses.
_MATCH_TOL = 0.02


# ── Helpers ────────────────────────────────────────────────────────────────────

def _midnight(d: date, tz: ZoneInfo) -> datetime:
    return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=tz)


def _act_dt(a: UserActivity, tz: ZoneInfo) -> datetime:
    return datetime.fromtimestamp(a.timestamp, tz=tz)


def _cp_date_str(cp: ResolvedPosition) -> Optional[str]:
    return cp.resolved_date[:10] if cp.resolved_date else None


def _is_close_event(a: UserActivity) -> bool:
    """True if this activity event represents a fully-realized position exit.

    Covers three close paths on Polymarket:
      REDEEM  — market-resolution redemption (a.type == "REDEEM")
      SELL    — CLOB full-position sell (a.type == "SELL")
      TRADE   — some API responses use type="TRADE" with side="SELL"

    BUY / TRADE+BUY / SPLIT / MERGE etc. are NOT close events.
    """
    if a.type == "REDEEM":
        return True
    if a.type == "SELL":
        return True
    if a.type == "TRADE" and a.side == "SELL":
        return True
    return False


def _find_match(
    act: UserActivity,
    pool: List[ResolvedPosition],
) -> Optional[ResolvedPosition]:
    """Find the best-matching closed position for a close event.

    The pool is assumed to be pre-filtered to the relevant date range.

    Matching strategy (greedy, one-to-one):
      Primary  : market title == activity title  AND  usdc_size ≈ redeem_value
      Fallback : usdc_size ≈ redeem_value  (title absent or differs slightly)

    For REDEEM events: usdc_size = redemption proceeds = redeem_value ✓
    For SELL   events: usdc_size = sell proceeds      = cost_basis + realized_pnl
                                                      = redeem_value ✓

    Caller must remove the returned item from pool.
    """
    # Primary: title + value (reduces ambiguity when multiple positions have similar sizes)
    if act.title:
        for cp in pool:
            if cp.market == act.title and abs(cp.redeem_value - act.usdc_size) < _MATCH_TOL:
                return cp
    # Fallback: value only (handles minor title mismatches)
    for cp in pool:
        if abs(cp.redeem_value - act.usdc_size) < _MATCH_TOL:
            return cp
    return None


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

    # All position-close events today (REDEEM + SELL + TRADE/SELL), sorted chronologically
    close_events = sorted(
        [a for a in activity if _is_close_event(a) and _act_dt(a, tz).date() == today],
        key=lambda a: a.timestamp,
    )

    # All closed positions that resolved today (by resolved_date)
    today_closed = [cp for cp in closed if _cp_date_str(cp) == today_str]
    full_total = round(sum(cp.realized_pnl for cp in today_closed), 2)

    # Diagnostics — visible only when TRADELEDGER_DEBUG=1
    if close_events or today_closed:
        type_dist: Dict[str, int] = {}
        for a in activity:
            if _act_dt(a, tz).date() == today:
                key = f"{a.type}:{a.side}" if a.side else a.type
                type_dist[key] = type_dist.get(key, 0) + 1
        _dlog("chart1d",
              "range=1d | activity=%d total | today types: %s",
              len(activity), type_dist)
        _dlog("chart1d",
              "today close_events=%d | today_closed=%d | full_total=%.2f",
              len(close_events), len(today_closed), full_total)

    pool = list(today_closed)
    points: List[Dict[str, Any]] = [{"timestamp": midnight, "value": 0.0}]
    cumulative = 0.0
    matched = 0
    is_partial = False

    for act in close_events:
        match = _find_match(act, pool)
        if match is None:
            # Cannot determine cost basis for this event → skip, mark partial
            is_partial = True
            continue
        pool.remove(match)
        matched += 1
        cumulative = round(cumulative + match.realized_pnl, 2)
        points.append({"timestamp": _act_dt(act, tz), "value": cumulative})

    # Closed positions that couldn't be matched to any close event (expired worthless, etc.)
    if pool:
        is_partial = True

    _dlog("chart1d",
          "matched=%d | unmatched_events=%d | unmatched_closed=%d | "
          "cumulative=%.2f | full_total=%.2f | points=%d",
          matched,
          len(close_events) - matched,
          len(pool),
          cumulative, full_total,
          len(points) + 1)  # +1 for the "now" point we're about to add

    # Always end at "now" using the authoritative total from all closed positions
    points.append({"timestamp": now, "value": full_total})

    # If the matched running total diverges from the full closed-positions total,
    # the chart has a visible jump at "now" — flag this as partial
    if abs(cumulative - full_total) > _MATCH_TOL:
        is_partial = True

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
    activity        : full activity list (used for 1D intraday timestamps)
    closed_positions: closed positions list (source of P/L amounts)
    range_key       : "1d" | "1w" | "1m" | "1y" | "ytd" | "all"
    timezone        : IANA timezone name (default: America/New_York)

    Returns
    -------
    (points, is_partial)
      points      — list of {"timestamp": aware_datetime, "value": float}
                    • First point : range start at $0
                    • Middle points: P/L events in chronological order
                    • Last point  : "now" at final cumulative P/L
      is_partial  — True when some events could not be precisely timestamped
                    (1D only: unmatched REDEEM or unmatched closed positions)

    For 1D: uses REDEEM activity timestamps for intraday granularity.
    For 1W+: daily rollup from closed positions (partial detection via
             pnl_today.is_data_partial, not this function).
    """
    tz = ZoneInfo(timezone)
    if range_key == "1d":
        return _build_1d_points(activity, closed_positions, tz)
    return _build_range_points(closed_positions, range_key, tz)
