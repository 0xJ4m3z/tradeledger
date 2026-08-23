"""Web-app configuration.

Must be imported before anything that imports ``app.database`` — it sets the
``TRADELEDGER_DB`` environment variable so the shared database module (used by
both the desktop app and this web app) points at a *separate* SQLite file.
This avoids two processes (desktop + web) fighting over the same file lock,
while reusing 100% of the same schema, migrations, and query functions.
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

# Only set a default if the caller hasn't already set one (e.g. tests override it).
os.environ.setdefault("TRADELEDGER_DB", str(REPO_ROOT / "tradeledger_web.db"))

# Placeholder wallet address the sample fixtures are seeded under (web/bootstrap.py).
SAMPLE_WALLET = "sample"


def current_wallet() -> str:
    """The wallet the app is currently showing data for.

    Single-tenant, matching the desktop app's model: whichever address was
    most recently fetched (app.database.load_last_wallet, the same "remembered
    wallet" setting the desktop app uses) — or SAMPLE_WALLET if no real
    wallet has ever been fetched yet. web/bootstrap.py seeds sample data
    under SAMPLE_WALLET and sets it as the last wallet on first boot, so a
    fresh install starts in sample mode automatically; the first successful
    app.services.refresh.run_full_refresh() call flips this over to the real
    address by calling save_last_wallet(), and every route downstream (see
    web/data.py) picks that up on the next request with no other state to
    manage.
    """
    from app import database

    return database.load_last_wallet() or SAMPLE_WALLET


def is_sample_mode(wallet: str) -> bool:
    return wallet == SAMPLE_WALLET
