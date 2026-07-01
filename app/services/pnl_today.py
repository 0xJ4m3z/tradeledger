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

    Prefers closed_at (actual close epoch) over resolved_date (market end date).
    Using resolved_date caused the 1D view to include positions closed on a different
    day whose market happened to resolve today, or vice versa.

    For 1D: closed_at date must equal today ET (strict equality — not >= so future
    dates can't accidentally appear). Falls back to resolved_date for legacy rows
    without closed_at.
    """
    if range_ == "all":
        return closed
    cutoff = range_cutoff_et(range_)
    if cutoff is None:
        return closed

    tz = _et_zone()
    result = []
    for p in closed:
        if p.closed_at:
            try:
                close_date = datetime.fromtimestamp(p.closed_at, tz=tz).date()
            except (OSError, OverflowError, ValueError):
                continue
        elif p.resolved_date:
            try:
                close_date = date.fromisoformat(p.resolved_date[:10])
            except (ValueError, TypeError):
                continue
        else:
            continue

        if range_ == "1d":
            if close_date == cutoff:
                result.append(p)
        else:
            if close_date >= cutoff:
                result.append(p)
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


# ── New authoritative helpers (v0.3.1) ────────────────────────────────────────

def filter_activity_by_range(
    activity: List[UserActivity], range_: str
) -> List[UserActivity]:
    """Filter activity to events within the given range using ET calendar dates.

    1D uses strict equality (date == today); other ranges use >= cutoff.
    """
    if range_ == "all" or not activity:
        return list(activity)
    tz = _et_zone()
    today = datetime.now(tz).date()
    cutoff = range_cutoff_et(range_)
    if cutoff is None:
        return list(activity)
    result = []
    for a in activity:
        try:
            a_date = datetime.fromtimestamp(a.timestamp, tz=tz).date()
        except (OSError, OverflowError, ValueError):
            continue
        if range_ == "1d":
            if a_date == today:
                result.append(a)
        else:
            if a_date >= cutoff:
                result.append(a)
    return result


def count_trades(activity: List[UserActivity], range_: str) -> int:
    """Count distinct market titles with any activity in the given range (ET).

    This is the canonical Trades metric: one trade per market window regardless
    of how many BUY/SELL/REDEEM rows that market generated.
    """
    filtered = filter_activity_by_range(activity, range_)
    return len({a.title for a in filtered if a.title})


def derive_closed_from_activity(
    activity: List[UserActivity],
) -> List[ResolvedPosition]:
    """Derive ResolvedPositions from REDEEM events in the activity feed.

    Used as a supplementary data source when the /closed-positions API only returns
    the most-recent N records.  Each REDEEM event with usdc_size > 0 represents a
    winning closed position.  Cost basis is approximated by summing all BUY USDC
    for the same (title, outcome) pair.

    Only WIN positions are derivable this way.  Loss positions (resolved to $0)
    generate no REDEEM event and are left to the API's closed-positions data.
    """
    from collections import defaultdict

    cost_by_pos: dict = defaultdict(float)
    cost_by_title: dict = defaultdict(float)
    # Track the bought outcome per title so REDEEM events with outcome=""
    # can be matched to the correct side.
    bought_outcome: dict = {}
    for a in activity:
        if a.type == "TRADE" and a.side == "BUY" and a.title:
            cost_by_pos[(a.title, a.outcome)] += a.usdc_size
            cost_by_title[a.title] += a.usdc_size
            if a.title not in bought_outcome and a.outcome:
                bought_outcome[a.title] = a.outcome

    latest_redeem: dict = {}
    for a in activity:
        if a.type == "REDEEM" and a.title and a.usdc_size > 0:
            key = (a.title, a.outcome)
            if key not in latest_redeem or a.timestamp > latest_redeem[key].timestamp:
                latest_redeem[key] = a

    positions: List[ResolvedPosition] = []
    for (market, outcome), ev in latest_redeem.items():
        # REDEEM events often have outcome="" while BUY events have "Yes"/"No".
        # Fall back to per-title total cost when the exact (title, outcome) key gives 0,
        # and infer the actual outcome held from the BUY events for that title.
        cost = cost_by_pos.get((market, outcome)) or cost_by_title.get(market, 0.0)
        actual_outcome = outcome or bought_outcome.get(market, outcome)
        positions.append(
            ResolvedPosition(
                market=market,
                outcome_held=actual_outcome,
                winning_outcome=actual_outcome,
                quantity=ev.size,
                cost_basis=cost,
                redeem_value=ev.usdc_size,
                redeemed=True,
                resolved_date=None,
                closed_at=ev.timestamp,
            )
        )
    return positions


def classify_closed_positions(
    closed: List[ResolvedPosition],
    activity: List[UserActivity],
) -> None:
    """Set close_type on each position in-place using Activity SELL cross-reference.

    Priority order:
      1. Activity contains a SELL for (market, outcome) → SOLD
      2. realized_pnl > 0                               → REDEEMED_WIN
      3. redeem_value ≈ 0                               → RESOLVED_LOSS
      4. realized_pnl < 0 with partial recovery         → SOLD
      5. Otherwise                                       → UNKNOWN
    """
    sell_keys = {(a.title, a.outcome) for a in activity if a.side == "SELL"}
    for p in closed:
        if (p.market, p.outcome_held) in sell_keys:
            p.close_type = "SOLD"
        elif p.realized_pnl > 0:
            p.close_type = "REDEEMED_WIN"
        elif p.redeem_value < 0.005:
            p.close_type = "RESOLVED_LOSS"
        elif p.realized_pnl < 0:
            p.close_type = "SOLD"
        else:
            p.close_type = "UNKNOWN"
