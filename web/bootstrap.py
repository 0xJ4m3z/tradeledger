"""One-time seeding of sample data into the shared SQLite cache tables.

Phase 1 of the web app runs in sample-data mode (no live Polymarket/Polygon
fetch yet — see project plan). Rather than inventing a parallel in-memory data
path, we persist the bundled sample fixtures into the *same* cache tables
`app.database` already defines, under a placeholder wallet address
(`SAMPLE_WALLET`). This means every route in the web app reads through the
exact same `app.database.load_*` functions a live wallet would use — no
sample-mode special-casing anywhere except this one seed step.

`sample_data/sample_resolved_positions.json` predates the Active/Resolved/
Closed three-way split introduced later in the desktop app's terminology: its
positions all carry a `resolved_date` and are either redeemed-for-value (wins)
or resolved to $0 (losses) — i.e. they are fully settled. That maps onto
today's "Closed Positions" concept, not "Resolved" (won, pending redemption).
So we seed it into `closed_positions_cache`, and leave `resolved_positions_cache`
empty for the sample wallet — which doubles as a real, honest empty state for
Playwright to exercise later, rather than fabricated filler data.
"""

from app import database
from app.adapters import sample_adapter
from web.config import SAMPLE_WALLET


def seed_sample_data_if_needed() -> None:
    """Populate the sample-wallet caches on first run. Idempotent — a no-op
    once the active-positions cache for SAMPLE_WALLET is non-empty."""
    if database.load_active_positions_cache(SAMPLE_WALLET):
        return

    active = sample_adapter.load_active_positions()
    closed = sample_adapter.load_resolved_positions()  # see module docstring

    database.save_active_positions_cache(SAMPLE_WALLET, active)
    database.upsert_closed_positions_cache(closed, SAMPLE_WALLET)
    database.save_last_wallet(SAMPLE_WALLET)

    # Seed a single Total Tracked Value snapshot so the dashboard card and the
    # historical chart have at least one real, non-fabricated data point,
    # matching what a first-time live user would see after their first fetch.
    from app.services.metrics import compute_dashboard_metrics

    metrics = compute_dashboard_metrics(active, [])
    database.save_wallet_snapshot(
        wallet_address=SAMPLE_WALLET,
        active_positions_value=metrics["active_positions_value"],
        wallet_usd_value=0.0,
        unrealized_pnl=metrics["unrealized_pnl"],
        realized_pnl=0.0,
    )
