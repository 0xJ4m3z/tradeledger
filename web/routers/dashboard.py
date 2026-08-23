from fastapi import APIRouter, Request

from app.services.chart_ranges import RANGE_LABELS
from web import charts, data
from web.templating import templates

router = APIRouter()

_VALID_RANGES = set(RANGE_LABELS.keys())


@router.get("/")
def dashboard(request: Request, range: str = "all"):
    range_key = range.lower() if range.lower() in _VALID_RANGES else "all"

    metrics = data.get_dashboard_metrics()
    active = data.get_active_positions()
    closed = data.get_closed_positions()
    pnl = data.get_pnl_range_data(range_key, closed=closed)
    chart_points = charts.pnl_chart_points(closed, range_key)

    # pnl["positions"] is a range-filtered subset of `closed` (matching the
    # desktop Overview's closed-positions grid — range buttons "control all
    # of these at once"), but /positions/closed/{idx} indexes into the FULL
    # unfiltered list. Map each preview row back to its real index there,
    # by identity (not equality — two structurally-identical closed
    # positions must still resolve to their own, correct index).
    index_by_id = {id(p): i for i, p in enumerate(closed)}
    closed_preview = [
        {"position": p, "index": index_by_id[id(p)]}
        for p in pnl["positions"][:5]
    ]

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "metrics": metrics,
            "active_preview": active[:5],
            "active_total": len(active),
            "closed_preview": closed_preview,
            "closed_range_count": len(pnl["positions"]),
            "closed_total": len(closed),
            "chart_points": chart_points,
            "range_labels": RANGE_LABELS,
            "selected_range": range_key,
            "pnl": pnl,
        },
    )
