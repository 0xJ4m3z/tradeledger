from fastapi import APIRouter, Request

from app.services.chart_ranges import RANGE_LABELS
from web import charts, data
from web.templating import templates

router = APIRouter()

_VALID_RANGES = set(RANGE_LABELS.keys())


@router.get("/pnl")
def pnl_page(request: Request, range: str = "all"):
    range_key = range.lower() if range.lower() in _VALID_RANGES else "all"
    pnl_data = data.get_pnl_range_data(range_key)
    points = charts.pnl_chart_points(data.get_closed_positions(), range_key)

    return templates.TemplateResponse(
        request,
        "pnl.html",
        {
            "range_labels": RANGE_LABELS,
            "selected_range": range_key,
            "pnl": pnl_data,
            "chart_points": points,
        },
    )
