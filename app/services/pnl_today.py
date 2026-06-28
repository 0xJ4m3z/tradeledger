"""
Realized P/L Today — net realized profit for the current calendar day in Central Time.

"Today" resets at midnight CT (America/Chicago), which handles both CST (UTC-6)
and CDT (UTC-5) automatically via the system timezone database.

For each SELL or REDEEM event today:
  realized_pnl = proceeds − (qty_closed × avg_buy_price_for_that_market+outcome)

avg_buy_price is derived from ALL BUY events in the activity feed (any date),
weighted by quantity:  avg = total_buy_usdc / total_buy_qty.

Matching strategy:
  - SELL events include an outcome field → matched by (title, outcome)
  - REDEEM events often have an empty outcome in the API response → matched by
    title alone (you can only redeem the winning side, so aggregating all BUYs
    for the market is correct)
  - Fallback: if (title, outcome) has no matching BUY, retry with title only

If no matching BUY is found in the feed at all (position opened outside the
100-event window), that close is skipped — showing partial data is more honest
than adding gross proceeds as if cost were zero.

Rebates and rewards (MAKER_REBATE, TAKER_REBATE, REWARD, REFERRAL_REWARD) have no
matching BUY and are added as direct credits.
"""

from datetime import datetime
from typing import Dict, List, Tuple

from app.models import UserActivity

# Credited directly — no cost-basis matching needed
_REBATE_TYPES = frozenset(
    {"REWARD", "MAKER_REBATE", "TAKER_REBATE", "REFERRAL_REWARD"}
)


def _build_buy_index(
    activity: List[UserActivity],
) -> Tuple[Dict, Dict, Dict, Dict]:
    """Aggregate all BUY events in the feed (any date) into two indexes.

    Returns:
      qty_by_key   — (title, outcome) → total tokens bought
      cost_by_key  — (title, outcome) → total USDC spent
      qty_by_title — title → total tokens bought (all outcomes combined)
      cost_by_title— title → total USDC spent   (all outcomes combined)
    """
    qty_by_key:    Dict[tuple, float] = {}
    cost_by_key:   Dict[tuple, float] = {}
    qty_by_title:  Dict[str,   float] = {}
    cost_by_title: Dict[str,   float] = {}

    for a in activity:
        if a.side == "BUY":
            k = (a.title, a.outcome)
            qty_by_key[k]    = qty_by_key.get(k, 0.0)    + a.size
            cost_by_key[k]   = cost_by_key.get(k, 0.0)   + a.usdc_size
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
    """Return (qty_bought, cost_bought) for a close event.

    - Non-empty outcome (SELL): match exactly on (title, outcome); no fallback.
      If the BUY isn't in the feed, return (0, 0) so the close is skipped.
    - Empty outcome (REDEEM from Polymarket API): match by title only, aggregating
      all outcomes — you can only redeem the winning side, so this is safe.
    """
    if outcome:
        k = (title, outcome)
        return qty_by_key.get(k, 0.0), cost_by_key.get(k, 0.0)
    # Empty outcome → title-only (REDEEM events have no outcome in the API response)
    return qty_by_title.get(title, 0.0), cost_by_title.get(title, 0.0)


def compute_pnl_today(
    activity: List[UserActivity],
    tz_name: str = "America/Chicago",
) -> float:
    """Return realized P/L for today (CT by default).

    Falls back to UTC-6 fixed offset if zoneinfo is unavailable.
    Returns 0.0 when no closes with known cost basis occurred today.
    Retroactively calculates from whatever activity is in the feed, so
    starting the app mid-day still gives the correct day-so-far figure.
    """
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        from datetime import timezone, timedelta
        tz = timezone(timedelta(hours=-6))

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
                qty_by_key, cost_by_key,
                qty_by_title, cost_by_title,
            )
            q_close = a.size

            if q_bought > 0 and q_close > 0:
                avg_price      = c_bought / q_bought
                allocated_cost = min(q_close, q_bought) * avg_price
                total += a.usdc_size - allocated_cost
            # else: BUY not in feed or size unknown — skip to avoid counting raw volume

        elif a.type in _REBATE_TYPES:
            total += a.usdc_size

    return round(total, 2)


def count_trades_today(
    activity: List[UserActivity],
    tz_name: str = "America/Chicago",
) -> int:
    """Count distinct markets traded today (CT by default).

    All activity for "Bitcoin Up or Down - June 28, 1:50PM-1:55PM ET" —
    whether BUY, SELL, or REDEEM — counts as one trade for that window.
    """
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        from datetime import timezone, timedelta
        tz = timezone(timedelta(hours=-6))
    today = datetime.now(tz).date()
    return len({
        a.title for a in activity
        if datetime.fromtimestamp(a.timestamp, tz=tz).date() == today
        and a.title  # skip events with no market title
    })


def today_date_ct() -> "datetime.date":
    """Return today's date in Central Time (for testing/display)."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Chicago")
    except Exception:
        from datetime import timezone, timedelta
        tz = timezone(timedelta(hours=-6))
    return datetime.now(tz).date()
