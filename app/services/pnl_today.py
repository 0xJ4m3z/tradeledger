"""
Realized P/L Today — net realized profit for the current calendar day in Central Time.

"Today" resets at midnight CT (America/Chicago), which handles both CST (UTC-6)
and CDT (UTC-5) automatically via the system timezone database.

For each SELL or REDEEM event today:
  realized_pnl = proceeds − (qty_closed × avg_buy_price_for_that_market+outcome)

avg_buy_price is derived from ALL BUY events in the activity feed (any date),
weighted by quantity:  avg = total_buy_usdc / total_buy_qty.

If no matching BUY is found in the feed (position opened outside the 100-event window),
that close is skipped — showing partial data is more honest than adding gross proceeds
as if cost were zero.

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
) -> Tuple[Dict, Dict]:
    """Aggregate all BUY events in the feed (any date) by (title, outcome).

    Returns (qty_by_key, cost_by_key).  Used to compute avg cost basis for closes.
    """
    qty: Dict[tuple, float]  = {}
    cost: Dict[tuple, float] = {}
    for a in activity:
        if a.side == "BUY":
            k = (a.title, a.outcome)
            qty[k]  = qty.get(k, 0.0)  + a.size
            cost[k] = cost.get(k, 0.0) + a.usdc_size
    return qty, cost


def compute_pnl_today(
    activity: List[UserActivity],
    tz_name: str = "America/Chicago",
) -> float:
    """Return realized P/L for today (CT by default).

    Falls back to UTC-6 fixed offset if zoneinfo is unavailable.
    Returns 0.0 when no closes with known cost basis occurred today.
    """
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        from datetime import timezone, timedelta
        tz = timezone(timedelta(hours=-6))

    today = datetime.now(tz).date()
    buy_qty, buy_cost = _build_buy_index(activity)

    total = 0.0
    for a in activity:
        ts_local = datetime.fromtimestamp(a.timestamp, tz=tz)
        if ts_local.date() != today:
            continue

        if a.side == "SELL" or a.type == "REDEEM":
            k = (a.title, a.outcome)
            q_bought = buy_qty.get(k, 0.0)
            c_bought = buy_cost.get(k, 0.0)
            q_close  = a.size

            if q_bought > 0 and q_close > 0:
                avg_price      = c_bought / q_bought
                allocated_cost = min(q_close, q_bought) * avg_price
                total += a.usdc_size - allocated_cost
            # else: BUY not in feed or size unknown — skip to avoid counting raw volume

        elif a.type in _REBATE_TYPES:
            total += a.usdc_size

    return round(total, 2)


def today_date_ct() -> "datetime.date":
    """Return today's date in Central Time (for testing/display)."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Chicago")
    except Exception:
        from datetime import timezone, timedelta
        tz = timezone(timedelta(hours=-6))
    return datetime.now(tz).date()
