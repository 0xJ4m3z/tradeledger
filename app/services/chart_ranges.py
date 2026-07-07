from datetime import datetime, timedelta, timezone
from typing import List

RANGE_LABELS = {
    "1d":  "1D",
    "1w":  "1W",
    "1m":  "1M",
    "1y":  "1Y",
    "ytd": "YTD",
    "all": "All",
}

_DEFAULT_RANGE = "all"

_DELTA = {
    "1d": timedelta(days=1),
    "1w": timedelta(weeks=1),
    "1m": timedelta(days=30),
    "1y": timedelta(days=365),
}


def filter_snapshots_by_range(snapshots: List[dict], range_key: str) -> List[dict]:
    """Return snapshots within the selected time range.

    Accepts uppercase or lowercase range keys (1D/1d, 1W/1w, 1M/1m, 1Y/1y, YTD/ytd, All/all).
    Snapshots without a valid 'captured_at' timestamp are excluded for any range
    other than 'all'. Timestamps are treated as UTC.
    """
    key = (range_key or "all").lower()
    now = datetime.now(timezone.utc)

    if key == "ytd":
        cutoff = datetime(now.year, 1, 1, tzinfo=timezone.utc)
    elif key in _DELTA:
        cutoff = now - _DELTA[key]
    else:
        return snapshots  # "all" or unknown → return everything

    result = []
    for s in snapshots:
        try:
            ts = datetime.fromisoformat(s["captured_at"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                result.append(s)
        except (KeyError, ValueError):
            pass
    return result
