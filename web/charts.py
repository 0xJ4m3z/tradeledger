"""JSON-shaping helpers for the two charts on the web app.

Both wrap existing, already-tested pure functions in `app.services` — the
only thing added here is converting `date` objects to ISO strings and lists
of tuples into a shape that's convenient to `json.dumps()` into a `<script>`
tag for the vanilla-JS SVG line chart (see static/js/linechart.js).
"""

from typing import List

from app.models import ResolvedPosition
from app.services.pnl_series import build_pnl_series


def pnl_chart_points(closed: List[ResolvedPosition], range_key: str) -> List[dict]:
    x_dates, y_values = build_pnl_series(closed, range_key)
    return [
        {"date": d.isoformat(), "value": v}
        for d, v in zip(x_dates, y_values)
    ]


def total_tracked_value_points(snapshots: List[dict]) -> List[dict]:
    """snapshots: list of dicts from database.load_wallet_snapshots (already
    range-filtered by the caller via chart_ranges.filter_snapshots_by_range)."""
    return [
        {"date": s["captured_at"], "value": s["total_tracked_value"]}
        for s in snapshots
    ]
