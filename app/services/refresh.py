"""Framework-agnostic "do a full wallet refresh" orchestration.

This is a straight extraction of the fetch sequence that has lived inside
Qt's `_FetchThread.run()` (app/ui/wallet_panel.py) and the `_on_positions_fetched`
handler (app/ui/overview.py): fetch wallet USD value, fetch active/resolved/
closed positions (deduping active against resolved), fetch recent activity,
persist everything to the shared SQLite cache, and snapshot Total Tracked
Value. Extracting it here means the web app (and, if the desktop app is ever
refactored to route through it too) both drive the exact same logic — no
business rules live in either UI layer.

Scope note: this fetches the same *initial* page of data the desktop app
shows before its background `_BackfillThread` kicks in (up to 100 closed
positions, up to 100 activity events) — deep history backfill is a natural
next increment, not implemented here yet.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from app import database
from app.adapters.polymarket_adapter import (
    PolymarketLookupError,
    fetch_activity,
    fetch_active_positions,
    fetch_closed_positions,
    fetch_resolved_positions,
)
from app.adapters.wallet_adapter import WalletLookupError, fetch_wallet_usd_value
from app.services.metrics import compute_dashboard_metrics


@dataclass
class RefreshResult:
    address: str
    wallet_usd_value: Optional[float] = None
    wallet_error: Optional[str] = None

    active_count: int = 0
    resolved_count: int = 0
    closed_count: int = 0
    positions_error: Optional[str] = None

    activity_count: int = 0
    activity_error: Optional[str] = None

    errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True if every phase succeeded."""
        return not self.errors

    @property
    def has_any_data(self) -> bool:
        """True if at least one phase returned something usable."""
        return bool(
            self.wallet_usd_value is not None
            or self.active_count
            or self.resolved_count
            or self.closed_count
        )


def run_full_refresh(address: str) -> RefreshResult:
    """Fetch + cache everything for `address`. Never raises — failures are
    recorded on the returned RefreshResult so callers can show a partial
    success (mirrors _FetchThread: wallet/positions/activity fail independently).
    """
    address = address.strip()
    result = RefreshResult(address=address)

    # Step 1: wallet USD value
    try:
        result.wallet_usd_value = fetch_wallet_usd_value(address)
    except WalletLookupError as exc:
        result.wallet_error = str(exc)
        result.errors.append(f"Wallet balance: {exc}")
    except Exception as exc:  # noqa: BLE001 — surfaced to the caller, not swallowed
        result.wallet_error = f"Unexpected error: {exc}"
        result.errors.append(f"Wallet balance: {exc}")

    # Step 2: Polymarket positions
    try:
        active = fetch_active_positions(address)
        resolved = fetch_resolved_positions(address)
        closed = fetch_closed_positions(address)

        # A market is either active or resolved — strip resolved markets from
        # active so the same position never appears in both lists at once
        # (matches _FetchThread.run()'s dedupe rule exactly).
        resolved_titles = {p.market for p in resolved}
        active = [p for p in active if p.market not in resolved_titles]

        database.save_active_positions_cache(address, active)
        database.save_resolved_positions_cache(address, resolved)
        database.upsert_closed_positions_cache(closed, address)

        result.active_count = len(active)
        result.resolved_count = len(resolved)
        result.closed_count = len(closed)
    except PolymarketLookupError as exc:
        result.positions_error = str(exc)
        result.errors.append(f"Positions: {exc}")
    except Exception as exc:  # noqa: BLE001
        result.positions_error = f"Unexpected error: {exc}"
        result.errors.append(f"Positions: {exc}")

    # Step 3: activity feed (non-fatal — positions already saved above)
    try:
        activity = fetch_activity(address)
        database.upsert_activity_cache(address, activity)
        result.activity_count = len(activity)
    except PolymarketLookupError as exc:
        result.activity_error = str(exc)
        result.errors.append(f"Activity: {exc}")
    except Exception as exc:  # noqa: BLE001
        result.activity_error = f"Unexpected error: {exc}"
        result.errors.append(f"Activity: {exc}")

    # Remember the wallet regardless of partial failure, so a retry (or the
    # next page load) picks up right where this attempt left off — matches
    # the desktop app's "remembered wallet" behavior.
    database.save_last_wallet(address)

    # Snapshot Total Tracked Value whenever we have at least positions data.
    # Unlike the desktop app (which clears *today's* snapshots once per
    # session to wipe out a stale sample-data point saved before the first
    # live fetch completes), the web app never writes a snapshot under a real
    # wallet's address until a real fetch succeeds — there's no stale point
    # to correct, so every refresh simply appends, giving the Total Tracked
    # Value chart intraday granularity across repeated refreshes.
    if result.positions_error is None:
        active_cached = database.load_active_positions_cache(address)
        resolved_cached = database.load_resolved_positions_cache(address)
        metrics = compute_dashboard_metrics(active_cached, resolved_cached)
        database.save_wallet_snapshot(
            wallet_address=address,
            active_positions_value=metrics["active_positions_value"],
            wallet_usd_value=result.wallet_usd_value or 0.0,
            unrealized_pnl=metrics["unrealized_pnl"],
            realized_pnl=metrics["realized_pnl"],
        )

    return result
