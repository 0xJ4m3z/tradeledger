from datetime import datetime, timedelta, timezone
from typing import List

_RANGES = {
    "1D":  timedelta(days=1),
    "1W":  timedelta(weeks=1),
    "1M":  timedelta(days=30),
    "All": None,
}

_DEFAULT_RANGE = "All"


def filter_snapshots_by_range(snapshots: List[dict], range_key: str) -> List[dict]:
    """Return the subset of snapshots that fall within the selected time range.

    Timestamps are stored as naive UTC ISO strings; they are treated as UTC for
    comparison.  Unknown range_key returns all snapshots.
    """
    delta = _RANGES.get(range_key)
    if delta is None:
        return snapshots
    cutoff = datetime.now(timezone.utc) - delta
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
