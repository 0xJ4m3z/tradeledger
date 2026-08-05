"""Market window end-time helpers.

Parses the closing time of a Polymarket "Up or Down" style market from its
title string, and determines whether the window has already passed.

Used by the Overview's Sold section to decide whether a CLOB-sold position
should still be shown as "pending" or has graduated to the Closed section.

No Qt dependency — pure Python, fully testable.
"""
import re
from datetime import datetime, timezone
from typing import Optional

try:
    from zoneinfo import ZoneInfo as _ZoneInfo
    _ET_ZONE = _ZoneInfo("America/New_York")
except Exception:
    from datetime import timedelta
    _ET_ZONE = timezone(timedelta(hours=-5))

# Matches the time range at the end of a market title, e.g.:
#   "4:55PM-5:00PM ET"   → start=4:55PM, end=5:00PM
#   "4:45-5:00PM ET"     → start=4:45 (no suffix), end=5:00PM
#   "10:40-10:45AM ET"   → start=10:40, end=10:45AM
# Group 1 captures the end time including AM/PM (always present).
_WINDOW_END_RE = re.compile(
    r'(?:\d{1,2}:\d{2}(?:[AP]M)?)-(\d{1,2}:\d{2}[AP]M)\s+ET\b',
    re.IGNORECASE,
)


def window_end_et(market: str, resolved_date: Optional[str], closed_at: Optional[int]) -> Optional[datetime]:
    """Return the market window's end time as a tz-aware ET datetime.

    Priority:
      1. resolved_date if it includes time (e.g. "2026-08-05T21:00:00Z" from endDate).
      2. End time parsed from the market title + date from resolved_date.
      3. End time parsed from the market title + date derived from closed_at.

    Returns None if the end time cannot be determined (no regex match, no date).
    """
    # 1. Full ISO datetime in resolved_date
    rd = resolved_date or ""
    if len(rd) > 10:
        try:
            return datetime.fromisoformat(rd.replace("Z", "+00:00")).astimezone(_ET_ZONE)
        except ValueError:
            pass

    # 2 & 3: parse end time from title, get date from resolved_date or closed_at
    m = _WINDOW_END_RE.search(market)
    if not m:
        return None

    end_time_str = m.group(1).upper()   # e.g. "5:00PM"

    date_str = rd[:10]   # "YYYY-MM-DD" from resolved_date, or ""
    if not date_str and closed_at:
        try:
            date_str = datetime.fromtimestamp(closed_at, tz=_ET_ZONE).strftime("%Y-%m-%d")
        except Exception:
            return None
    if not date_str:
        return None

    try:
        naive = datetime.strptime(f"{date_str} {end_time_str}", "%Y-%m-%d %I:%M%p")
        return naive.replace(tzinfo=_ET_ZONE)
    except ValueError:
        return None


def window_closed(market: str, resolved_date: Optional[str], closed_at: Optional[int]) -> bool:
    """True when the market's window end time is in the past.

    Returns False when the end time cannot be parsed — safe fallback keeps
    the position visible in the Sold section rather than silently dropping it.
    """
    end = window_end_et(market, resolved_date, closed_at)
    if end is None:
        return False
    return datetime.now(tz=timezone.utc) >= end.astimezone(timezone.utc)
