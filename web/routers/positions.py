from fastapi import APIRouter, HTTPException, Request

from web import data
from web.templating import templates

router = APIRouter(prefix="/positions")

_GETTERS = {
    "active": data.get_active_positions,
    "resolved": data.get_resolved_positions,
    "closed": data.get_closed_positions,
}

_TITLES = {
    "active": "Active Positions",
    "resolved": "Resolved Positions",
    "closed": "Closed Positions",
}

_SUBTITLES = {
    "active": "Open positions still exposed to market movement.",
    "resolved": "Won markets pending redemption — still counted in Positions Value.",
    "closed": "Fully settled trades (redeemed or resolved to $0).",
}


def _get_kind_or_404(kind: str):
    if kind not in _GETTERS:
        raise HTTPException(status_code=404, detail=f"Unknown position list: {kind}")
    return _GETTERS[kind]()


@router.get("/{kind}")
def position_list(request: Request, kind: str):
    positions = _get_kind_or_404(kind)
    return templates.TemplateResponse(
        request,
        "positions_list.html",
        {
            "kind": kind,
            "title": _TITLES[kind],
            "subtitle": _SUBTITLES[kind],
            "positions": positions,
        },
    )


@router.get("/{kind}/{idx}")
def position_detail(request: Request, kind: str, idx: int):
    positions = _get_kind_or_404(kind)
    if idx < 0 or idx >= len(positions):
        raise HTTPException(status_code=404, detail="Position not found")
    return templates.TemplateResponse(
        request,
        "position_detail.html",
        {
            "kind": kind,
            "title": _TITLES[kind],
            "idx": idx,
            "position": positions[idx],
        },
    )
