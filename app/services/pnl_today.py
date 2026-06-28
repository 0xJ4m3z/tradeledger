"""
Realized P/L Today — net USDC flow for the current calendar day in Central Time.

"Today" resets at midnight CT (America/Chicago), which handles both CST (UTC-6)
and CDT (UTC-5) automatically via the system timezone database.

Calculation:
  + SELL trade proceeds   (usdcSize where side == SELL)
  + REDEEM proceeds       (usdcSize where type == REDEEM)
  + Rewards / rebates     (usdcSize where type in REWARD, MAKER_REBATE, TAKER_REBATE, REFERRAL_REWARD)
  − BUY costs             (usdcSize where side == BUY)

This is net USDC cash flow for the day, which approximates realized P/L for
daily monitoring purposes.  Cost-basis accounting per position is left for v0.4.
"""

from datetime import datetime
from typing import List

from app.models import UserActivity

_CREDIT_TYPES = frozenset(
    {"REDEEM", "REWARD", "MAKER_REBATE", "TAKER_REBATE", "REFERRAL_REWARD"}
)


def compute_pnl_today(
    activity: List[UserActivity],
    tz_name: str = "America/Chicago",
) -> float:
    """Return net USDC flow for today (CT by default).

    Falls back to UTC-6 fixed offset if zoneinfo is unavailable.
    Returns 0.0 when there is no activity today.
    """
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        from datetime import timezone, timedelta
        tz = timezone(timedelta(hours=-6))  # CST fallback (no DST)

    today = datetime.now(tz).date()
    total = 0.0
    for a in activity:
        ts_local = datetime.fromtimestamp(a.timestamp, tz=tz)
        if ts_local.date() != today:
            continue
        if a.side == "SELL" or a.type in _CREDIT_TYPES:
            total += a.usdc_size
        elif a.side == "BUY":
            total -= a.usdc_size
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
