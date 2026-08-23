from fastapi import APIRouter, Request

from app.services.chart_ranges import RANGE_LABELS
from web import charts, data
from web.templating import templates

router = APIRouter()

_VALID_RANGES = set(RANGE_LABELS.keys())


@router.get("/total-tracked-value")
def total_tracked_value_page(request: Request, range: str = "all"):
    range_key = range.lower() if range.lower() in _VALID_RANGES else "all"
    snapshots = data.get_total_tracked_value_series(range_key)
    points = charts.total_tracked_value_points(snapshots)

    return templates.TemplateResponse(
        request,
        "total_value.html",
        {
            "range_labels": RANGE_LABELS,
            "selected_range": range_key,
            "snapshots": snapshots,
            "chart_points": points,
        },
    )
