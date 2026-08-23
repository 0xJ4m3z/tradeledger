"""FastAPI entrypoint for the TradeLedger web app.

Phase 1 (sample-data mode): reuses app.database / app.services / app.models
exactly as the desktop app does — see web/data.py and web/bootstrap.py for
how the two are wired together.
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

import web.config  # noqa: F401  (must run first — sets TRADELEDGER_DB)
from app.database import init_db
from web.bootstrap import seed_sample_data_if_needed
from web.routers import dashboard, pnl, positions, total_value, wallet
from web.templating import templates

BASE_DIR = Path(__file__).parent

app = FastAPI(title="TradeLedger")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

app.include_router(dashboard.router)
app.include_router(positions.router)
app.include_router(pnl.router)
app.include_router(total_value.router)
app.include_router(wallet.router)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    seed_sample_data_if_needed()


@app.exception_handler(HTTPException)
async def not_found_handler(request: Request, exc: HTTPException):
    if exc.status_code == 404:
        return templates.TemplateResponse(
            request, "404.html", {"detail": exc.detail}, status_code=404
        )
    raise exc
