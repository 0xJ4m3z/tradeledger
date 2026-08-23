import re
from urllib.parse import quote

from fastapi import APIRouter, Form
from fastapi.responses import RedirectResponse

from app.services.refresh import run_full_refresh
from web.config import current_wallet, is_sample_mode

router = APIRouter()

# Polygon/EVM address: 0x + 40 hex chars. Same shape the desktop app expects
# (app/adapters/wallet_adapter.py's balanceOf calls assume this format).
_ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


def _redirect(param: str, message: str) -> RedirectResponse:
    return RedirectResponse(url=f"/?{param}={quote(message)}", status_code=303)


@router.post("/wallet/refresh")
def wallet_refresh(address: str = Form("")):
    """Fetch (or re-fetch) live wallet + position data. See
    app.services.refresh.run_full_refresh for the actual orchestration —
    this route is just form handling + flash-message redirects."""
    address = address.strip()

    if not address:
        # Bare "Refresh" button — reuse the already-loaded wallet.
        existing = current_wallet()
        if is_sample_mode(existing):
            return _redirect("wallet_error", "Enter a wallet address first.")
        address = existing

    if not _ADDR_RE.match(address):
        return _redirect(
            "wallet_error",
            "That doesn't look like a Polygon wallet address "
            "(expected 0x followed by 40 hex characters).",
        )

    result = run_full_refresh(address)

    if result.ok:
        return _redirect(
            "wallet_ok",
            f"Refreshed — {result.active_count} active, "
            f"{result.resolved_count} resolved, {result.closed_count} closed.",
        )
    if result.has_any_data:
        return _redirect("wallet_error", "Partial refresh: " + "; ".join(result.errors))
    return _redirect("wallet_error", "Refresh failed: " + "; ".join(result.errors))
