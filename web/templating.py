"""Shared Jinja2 environment + formatting filters used across all routers.

Formatting rules match the desktop app's conventions (see README "P/L
calculation rules" and v0.3.2 release notes): positive values have no `+`
prefix, negative values get a leading `-$`; color (not a sign glyph) conveys
direction.
"""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.services.polymarket_links import polymarket_url_for_slug
from app.services.wallet_display import mask_wallet_address
from web import data as web_data
from web.config import current_wallet, is_sample_mode

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def usd(value) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "—"
    if value < 0:
        return f"-${abs(value):,.2f}"
    return f"${value:,.2f}"


def pct(value) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{value:,.1f}%"


def pnl_class(value) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return ""
    return "pnl-pos" if value >= 0 else "pnl-neg"


templates.env.filters["usd"] = usd
templates.env.filters["pct"] = pct
templates.env.filters["pnl_class"] = pnl_class
templates.env.filters["mask_wallet"] = mask_wallet_address

# Globals (callable from any template, e.g. base.html's wallet bar) so every
# router doesn't need to thread wallet state through its own context dict.
templates.env.globals["current_wallet"] = current_wallet
templates.env.globals["is_sample_mode"] = is_sample_mode
templates.env.globals["last_refreshed_at"] = web_data.get_last_refreshed_at
templates.env.globals["polymarket_url_for_slug"] = polymarket_url_for_slug
