"""Thin read layer between FastAPI routes and the shared business logic.

Every function here is a straight composition of `app.database` loaders and
`app.services.*` pure functions — no new business rules are introduced here.
This module exists only to give the routers a single, convenient place to ask
for "the current wallet's X", the same role `WalletPanel`/`MainWindow` play
in the desktop app's Qt layer.
"""

from typing import List, Optional

from app import database
from app.models import ActivePosition, ResolvedPosition
from app.services.chart_ranges import filter_snapshots_by_range
from app.services.daily_pnl import build_daily_pnl_rows, sort_closed_positions_newest_first
from app.services.loss_watch import compute_loss_watch_count, get_loss_watch_positions
from app.services.metrics import compute_dashboard_metrics, compute_total_tracked_value
from app.services.pnl_today import filter_closed_by_range, is_data_partial
from app.services.positions import sort_by_realized_pnl, sort_by_unrealized_pnl
from web.config import current_wallet


def get_active_positions() -> List[ActivePosition]:
    positions = database.load_active_positions_cache(current_wallet())
    return sort_by_unrealized_pnl(positions)


def get_resolved_positions() -> List[ResolvedPosition]:
    positions = database.load_resolved_positions_cache(current_wallet())
    return sort_by_realized_pnl(positions)


def get_closed_positions() -> List[ResolvedPosition]:
    positions = database.load_all_closed_for_wallet(current_wallet())
    return sort_closed_positions_newest_first(positions)


def get_wallet_usd_value() -> float:
    """Last known wallet USD balance for the current wallet.

    Persisted, not in-memory (unlike the desktop app's self._wallet_usd_value)
    since the web app is stateless per-request — the most recent
    wallet_snapshots row (written by app.services.refresh.run_full_refresh)
    is the durable source of truth. 0.0 before any live fetch (sample mode).
    """
    snapshots = database.load_wallet_snapshots(current_wallet())
    return snapshots[-1]["wallet_usd_value"] if snapshots else 0.0


def get_dashboard_metrics() -> dict:
    """Range-independent Overview metric cards: Total Tracked Value, Wallet USD
    Value, Positions Value, Loss Watch. Range-dependent cards (Realized P/L,
    Trades, Win/Loss) come from get_pnl_range_data — see web/routers/dashboard.py,
    matching the desktop Overview's "range buttons control cards + chart + grid
    all at once" behavior (README: "P/L calculation rules")."""
    active = get_active_positions()
    resolved = get_resolved_positions()

    metrics = compute_dashboard_metrics(active, resolved)
    metrics["wallet_usd_value"] = get_wallet_usd_value()
    metrics["total_tracked_value"] = compute_total_tracked_value(
        metrics["active_positions_value"], metrics["wallet_usd_value"]
    )

    acknowledged = database.load_loss_watch_acknowledged()
    loss_watch_positions = get_loss_watch_positions(active)
    metrics["loss_watch_count"] = compute_loss_watch_count(active, acknowledged)
    metrics["loss_watch_positions"] = loss_watch_positions

    return metrics


def get_pnl_range_data(range_key: str, closed: Optional[List[ResolvedPosition]] = None) -> dict:
    """Range-filtered realized P/L + win/loss + daily breakdown, mirroring the
    desktop P/L tab and Overview cards. Used by both /pnl and the dashboard.

    Pass `closed` (from a caller's own get_closed_positions() call) when the
    caller also needs to map filtered positions back to indices in that same
    list — e.g. the dashboard preview linking to /positions/closed/{idx}.
    Each get_closed_positions() call re-queries the DB and builds fresh
    ResolvedPosition objects, so two separate calls never share object
    identity; skipping the second fetch here keeps them as the same objects.
    """
    if closed is None:
        closed = get_closed_positions()
    filtered = filter_closed_by_range(closed, range_key)
    partial = is_data_partial(closed, range_key)
    daily_rows = build_daily_pnl_rows(closed, range_key)
    return {
        "range": range_key,
        "positions": filtered,
        "realized_pnl": round(sum(p.realized_pnl for p in filtered), 2),
        "trade_count": len(filtered),
        "win_count": sum(1 for p in filtered if p.is_win),
        "loss_count": sum(1 for p in filtered if not p.is_win),
        "partial": partial,
        "daily_rows": daily_rows,
    }


def get_total_tracked_value_series(range_key: str) -> List[dict]:
    snapshots = database.load_wallet_snapshots(current_wallet())
    return filter_snapshots_by_range(snapshots, range_key)


def get_last_refreshed_at() -> Optional[str]:
    """captured_at of the most recent wallet_snapshot for the current wallet,
    or None if there isn't one — used to show "Last updated" in the wallet bar
    and to drive client-side auto-refresh (see static/js/auto_refresh.js)."""
    snapshots = database.load_wallet_snapshots(current_wallet())
    return snapshots[-1]["captured_at"] if snapshots else None
