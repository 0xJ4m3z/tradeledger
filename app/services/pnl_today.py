"""
Range-aware realized P/L from closed positions.

Timezone: America/New_York (ET — handles EST/EDT automatically).

Range definitions:
  1d  = current calendar day from midnight ET to now
  1w  = trailing 7 days from now
  1m  = trailing 30 days from now
  1y  = trailing 365 days from now
  ytd = January 1 midnight ET to now
  all = all loaded data (never partial by definition)

Source of truth for P/L: closed positions (ResolvedPosition.realized_pnl).
Losses are correctly counted because losing redemptions have redeem_value=0,
so realized_pnl = redeem_value − cost_basis = −cost_basis.

Partial data: when the oldest loaded closed position falls within the range
window, there may be older records in that window not yet loaded. Cards show
a "~" prefix to signal the number may be understated.
"""

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from app.models import ResolvedPosition, UserActivity

_ET = "America/New_York"

_REBATE_TYPES = frozenset(
    {"REWARD", "MAKER_REBATE", "TAKER_REBATE", "REFERRAL_REWARD"}
)


def _et_zone():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(_ET)
    except Exception:
        from datetime import timezone, timedelta as td
        return timezone(td(hours=-5))


def today_date_et() -> date:
    """Return today's date in Eastern Time."""
    return datetime.now(_et_zone()).date()


def today_date_ct() -> date:
    """Deprecated alias for today_date_et() — kept for backward compatibility."""
    return today_date_et()


def range_cutoff_et(range_: str) -> Optional[date]:
    """Return the inclusive start date for a range key (ET calendar dates).

    Returns None for 'all' (no cutoff — include everything).
    """
    tz = _et_zone()
    today = datetime.now(tz).date()
    if range_ == "1d":
        return today
    if range_ == "1w":
        return today - timedelta(days=7)
    if range_ == "1m":
        return today - timedelta(days=30)
    if range_ == "1y":
        return today - timedelta(days=365)
    if range_ == "ytd":
        return date(today.year, 1, 1)
    return None  # "all"


def is_data_partial(closed: List[ResolvedPosition], range_: str) -> bool:
    """Return True if loaded closed positions may be incomplete for the range.

    Partial: the oldest loaded record still falls within the range window —
    there could be older records in the same window not yet fetched.
    'all' is never partial (it means all loaded data by definition).
    """
    if range_ == "all" or not closed:
        return False
    cutoff = range_cutoff_et(range_)
    if cutoff is None:
        return False
    valid_dates = [
        date.fromisoformat(p.resolved_date[:10])
        for p in closed
        if p.resolved_date
        and len(p.resolved_date) >= 10
    ]
    if not valid_dates:
        return False
    oldest = min(valid_dates)
    return oldest >= cutoff


def filter_closed_by_range(
    closed: List[ResolvedPosition], range_: str
) -> List[ResolvedPosition]:
    """Filter closed positions to those within the given range (ET calendar dates).

    Uses resolved_date (ISO date string) from each ResolvedPosition.
    Records with missing or unparseable resolved_date are excluded.
    """
    if range_ == "all":
        return closed
    cutoff = range_cutoff_et(range_)
    if cutoff is None:
        return closed
    result = []
    for p in closed:
        if not p.resolved_date:
            continue
        try:
            d = date.fromisoformat(p.resolved_date[:10])
            if d >= cutoff:
                result.append(p)
        except (ValueError, TypeError):
            pass
    return result


# ── Activity-based helpers (not used by UI cards; retained for tests) ──────────

def _build_buy_index(
    activity: List[UserActivity],
) -> Tuple[Dict, Dict, Dict, Dict]:
    qty_by_key:    Dict[tuple, float] = {}
    cost_by_key:   Dict[tuple, float] = {}
    qty_by_title:  Dict[str,   float] = {}
    cost_by_title: Dict[str,   float] = {}
    for a in activity:
        if a.side == "BUY":
            k = (a.title, a.outcome)
            qty_by_key[k]   = qty_by_key.get(k, 0.0)   + a.size
            cost_by_key[k]  = cost_by_key.get(k, 0.0)  + a.usdc_size
            qty_by_title[a.title]  = qty_by_title.get(a.title, 0.0)  + a.size
            cost_by_title[a.title] = cost_by_title.get(a.title, 0.0) + a.usdc_size
    return qty_by_key, cost_by_key, qty_by_title, cost_by_title


def _lookup_buy(
    title: str,
    outcome: str,
    qty_by_key:    Dict[tuple, float],
    cost_by_key:   Dict[tuple, float],
    qty_by_title:  Dict[str,   float],
    cost_by_title: Dict[str,   float],
) -> Tuple[float, float]:
    if outcome:
        k = (title, outcome)
        return qty_by_key.get(k, 0.0), cost_by_key.get(k, 0.0)
    return qty_by_title.get(title, 0.0), cost_by_title.get(title, 0.0)


def compute_pnl_today(
    activity: List[UserActivity],
    tz_name: str = _ET,
) -> float:
    """Realized P/L for the current calendar day in ET (activity-based)."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        from datetime import timezone, timedelta as td
        tz = timezone(td(hours=-5))
    today = datetime.now(tz).date()
    qty_by_key, cost_by_key, qty_by_title, cost_by_title = _build_buy_index(activity)
    total = 0.0
    for a in activity:
        ts_local = datetime.fromtimestamp(a.timestamp, tz=tz)
        if ts_local.date() != today:
            continue
        if a.side == "SELL" or a.type == "REDEEM":
            q_bought, c_bought = _lookup_buy(
                a.title, a.outcome,
                qty_by_key, cost_by_key, qty_by_title, cost_by_title,
            )
            q_close = a.size
            if q_bought > 0 and q_close > 0:
                avg_price      = c_bought / q_bought
                allocated_cost = min(q_close, q_bought) * avg_price
                total += a.usdc_size - allocated_cost
        elif a.type in _REBATE_TYPES:
            total += a.usdc_size
    return round(total, 2)


def count_trades_today(
    activity: List[UserActivity],
    tz_name: str = _ET,
) -> int:
    """Count distinct market titles with any activity today (ET)."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        from datetime import timezone, timedelta as td
        tz = timezone(td(hours=-5))
    today = datetime.now(tz).date()
    return len({
        a.title for a in activity
        if a.title and datetime.fromtimestamp(a.timestamp, tz=tz).date() == today
    })


def compute_pnl_range(
    activity: List[UserActivity],
    cutoff_date=None,
    tz_name: str = _ET,
) -> float:
    """Realized P/L for close events on or after cutoff_date in ET (activity-based).

    cutoff_date=None means all time.
    """
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        from datetime import timezone, timedelta as td
        tz = timezone(td(hours=-5))
    qty_by_key, cost_by_key, qty_by_title, cost_by_title = _build_buy_index(activity)
    total = 0.0
    for a in activity:
        if cutoff_date is not None:
            ts_local = datetime.fromtimestamp(a.timestamp, tz=tz)
            if ts_local.date() < cutoff_date:
                continue
        if a.side == "SELL" or a.type == "REDEEM":
            q_bought, c_bought = _lookup_buy(
                a.title, a.outcome,
                qty_by_key, cost_by_key, qty_by_title, cost_by_title,
            )
            q_close = a.size
            if q_bought > 0 and q_close > 0:
                avg_price      = c_bought / q_bought
                allocated_cost = min(q_close, q_bought) * avg_price
                total += a.usdc_size - allocated_cost
        elif a.type in _REBATE_TYPES:
            if cutoff_date is not None:
                ts_local = datetime.fromtimestamp(a.timestamp, tz=tz)
                if ts_local.date() < cutoff_date:
                    continue
            total += a.usdc_size
    return round(total, 2)


def count_trades_range(
    activity: List[UserActivity],
    cutoff_date=None,
    tz_name: str = _ET,
) -> int:
    """Count distinct market titles with activity on or after cutoff_date (ET)."""
    if cutoff_date is None:
        return len({a.title for a in activity if a.title})
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        from datetime import timezone, timedelta as td
        tz = timezone(td(hours=-5))
    return len({
        a.title for a in activity
        if a.title and datetime.fromtimestamp(a.timestamp, tz=tz).date() >= cutoff_date
    })
