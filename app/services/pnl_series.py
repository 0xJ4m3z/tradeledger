"""
Build cumulative P/L time series data from closed positions.

Used by PnlChartWidget to draw the cumulative realized P/L line chart.
Pure data function — no Qt, no matplotlib — fully testable.

Returns (x_points, y_cumulative) where:
  x_points     — list of date objects, ascending, starting with a $0 anchor
  y_cumulative — running sum of realized_pnl matching each x_point

The first point is always (range_start, 0.0) so the line always starts at $0.
For the 'all' range there is no fixed cutoff; the anchor is one day before
the oldest loaded event so the line has visible space at the left edge.

If there are no events in the range, returns ([anchor], [0.0]) so the chart
can safely render an empty-looking (but honest) zero baseline.
"""

from datetime import date, timedelta
from typing import List, Tuple

from app.models import ResolvedPosition
from app.services.pnl_today import filter_closed_by_range, range_cutoff_et


def _parse_date(resolved_date: str | None) -> date | None:
    """Extract a date from a resolved_date string. Returns None on failure."""
    if not resolved_date:
        return None
    s = resolved_date.strip()
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


def build_pnl_series(
    closed: List[ResolvedPosition],
    range_: str,
) -> Tuple[List[date], List[float]]:
    """Return (x_points, y_cumulative) for the cumulative P/L line chart.

    x_points[0] is always the range anchor at $0.
    Each subsequent point reflects the running P/L after that day's positions.
    Multiple positions on the same date are aggregated to a single net value
    for that date, then accumulated.

    Edge cases:
      - No events in range: returns ([anchor], [0.0])
      - All positions have unparseable dates: same as no events
      - 'all' range with no cutoff: anchor is one day before the oldest event
    """
    filtered = filter_closed_by_range(closed, range_)

    # Aggregate P/L by date
    daily: dict[date, float] = {}
    for p in filtered:
        d = _parse_date(p.resolved_date)
        if d is None:
            continue
        daily[d] = round(daily.get(d, 0.0) + p.realized_pnl, 6)

    sorted_days = sorted(daily.keys())

    # Determine anchor
    cutoff = range_cutoff_et(range_)
    if cutoff is not None:
        anchor = cutoff
    elif sorted_days:
        anchor = sorted_days[0] - timedelta(days=1)
    else:
        return [], []

    # Build series: anchor at $0, then accumulate
    x: List[date] = [anchor]
    y: List[float] = [0.0]

    cumulative = 0.0
    for d in sorted_days:
        cumulative += daily[d]
        x.append(d)
        y.append(round(cumulative, 2))

    return x, y
