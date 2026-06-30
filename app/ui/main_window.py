from PySide6.QtWidgets import QMainWindow, QStatusBar, QTabWidget, QVBoxLayout, QWidget

from app.adapters.sample_adapter import load_all
from app.debug import _dlog
from app.database import (
    load_active_positions_cache,
    load_activity_cache,
    load_closed_positions_cache,
    load_last_wallet,
    load_resolved_positions_cache,
    load_wallet_snapshots,
    save_snapshot,
)
from app.services.metrics import compute_dashboard_metrics
from app.ui.active_positions_table import ActivePositionsTable
from app.ui.activity_table import ActivityTable
from app.ui.loss_watch_tab import LossWatchTab
from app.ui.overview import OverviewWidget
from app.ui.resolved_positions_table import ResolvedPositionsTable
from app.ui.total_value_chart import TotalValueChartWidget

_STYLE = """
QMainWindow, QWidget {
    background-color: #0d1117;
    color: #c9d1d9;
    font-size: 13px;
}
QTabWidget::pane {
    border: 1px solid #30363d;
    background-color: #0d1117;
}
QTabBar::tab {
    background-color: #161b22;
    color: #8b949e;
    padding: 8px 20px;
    border: 1px solid #30363d;
    border-bottom: none;
    margin-right: 2px;
    font-size: 13px;
}
QTabBar::tab:selected {
    background-color: #0d1117;
    color: #c9d1d9;
    border-bottom: 2px solid #58a6ff;
}
QTabBar::tab:hover {
    color: #c9d1d9;
}
QTableWidget {
    background-color: #0d1117;
    alternate-background-color: #0d1117;
    gridline-color: #21262d;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 4px;
}
QTableWidget QTableCornerButton::section {
    background-color: #161b22;
    border: none;
}
QHeaderView::section {
    background-color: #161b22;
    color: #8b949e;
    padding: 7px 12px;
    border: none;
    border-bottom: 1px solid #30363d;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.5px;
}
QTableWidget::item {
    padding: 6px 12px;
    border-bottom: 1px solid #21262d;
}
QTableWidget::item:selected {
    background-color: #1f2937;
    color: #c9d1d9;
}
QScrollBar:vertical {
    background: #0d1117;
    width: 8px;
    border: none;
}
QScrollBar::handle:vertical {
    background: #30363d;
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QStatusBar {
    background-color: #161b22;
    color: #8b949e;
    border-top: 1px solid #30363d;
    font-size: 12px;
    padding: 2px 8px;
}
QLineEdit {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 4px;
    color: #c9d1d9;
    padding: 6px 10px;
    font-size: 13px;
}
QLineEdit:focus {
    border-color: #58a6ff;
}
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TradeLedger")
        self.setMinimumSize(1100, 700)
        self.resize(1440, 940)
        self.setStyleSheet(_STYLE)

        # Try to load cached data for the remembered wallet to populate tabs immediately.
        # The WalletPanel auto-triggers a live refresh in the background; cached data
        # provides instant display while the fetch completes.
        _init_wallet  = load_last_wallet()
        cached_active   = load_active_positions_cache(_init_wallet)              if _init_wallet else []
        cached_resolved = load_resolved_positions_cache(_init_wallet)            if _init_wallet else []
        cached_closed   = load_closed_positions_cache(_init_wallet, limit=2000)  if _init_wallet else []
        cached_activity = load_activity_cache(_init_wallet, limit=2000)          if _init_wallet else []

        _dlog("startup",
              "wallet=%s | active=%d | resolved=%d | closed=%d | activity=%d",
              (_init_wallet[:10] + "...") if _init_wallet else "(none)",
              len(cached_active), len(cached_resolved),
              len(cached_closed), len(cached_activity))

        # Fall back to sample data only when no cache exists (first run / new wallet)
        if not cached_active and not cached_resolved:
            active, resolved = load_all()
            save_snapshot("sample", active, resolved)
            _from_cache = False
        else:
            active, resolved = cached_active, cached_resolved
            _from_cache = True

        metrics = compute_dashboard_metrics(active, resolved)

        overview               = OverviewWidget(active, resolved, metrics)
        self._loss_watch_tab   = LossWatchTab()
        self._active_tab       = ActivePositionsTable(active)
        self._resolved_tab     = ResolvedPositionsTable(resolved, label="Resolved Positions")
        self._closed_tab       = ResolvedPositionsTable(
            cached_closed, label="Closed Positions", show_refresh=True
        )
        self._activity_tab     = ActivityTable(cached_activity)

        # ── Signal wiring ───────────────────────────────────────────────────────
        overview.positions_changed.connect(self._on_positions_changed)
        overview.activity_changed.connect(self._activity_tab.update_activity)
        self._closed_tab.refresh_requested.connect(overview.request_refresh)
        self._activity_tab.refresh_requested.connect(overview.request_refresh)

        # Loss Watch tab ↔ Overview card stay in sync via DB
        self._loss_watch_tab.acknowledged_changed.connect(overview.reload_acknowledged)

        # Closed positions: backfill pages arrive incrementally → push to Closed tab
        overview.closed_cache_updated.connect(self._on_closed_cache_updated)

        # Activity: scroll-to-bottom → fetch next page → append rows
        self._activity_tab.load_more_requested.connect(overview.on_load_more_activity)
        overview.more_activity.connect(self._activity_tab.append_activity)

        # Closed positions: scroll-to-bottom → fetch next page → append rows
        self._closed_tab.load_more_requested.connect(overview.on_load_more_closed)
        overview.more_closed.connect(self._closed_tab.append_positions)

        # ── Total Tracked Value full-size chart tab ─────────────────────────────
        initial_wallet = load_last_wallet()
        self._tv_tab_chart = TotalValueChartWidget(load_wallet_snapshots(initial_wallet), figsize=(10, 5))
        overview.snapshots_changed.connect(self._tv_tab_chart.update_snapshots)
        tv_tab = QWidget()
        tv_layout = QVBoxLayout(tv_tab)
        tv_layout.setContentsMargins(20, 20, 20, 20)
        tv_layout.addWidget(self._tv_tab_chart)

        # ── Tabs ────────────────────────────────────────────────────────────────
        tabs = QTabWidget()
        tabs.addTab(overview,                  "Overview")
        tabs.addTab(self._loss_watch_tab,      "Loss Watch")
        tabs.addTab(self._active_tab,          "Active Positions")
        tabs.addTab(self._resolved_tab,        "Resolved Positions")
        tabs.addTab(self._closed_tab,          "Closed Positions")
        tabs.addTab(self._activity_tab,        "Activity")
        tabs.addTab(tv_tab,                    "Total Tracked Value")
        self.setCentralWidget(tabs)

        # Pre-populate Overview with cached closed positions so metric cards and
        # P/L chart render immediately before the live fetch completes.
        if cached_closed:
            overview.seed_from_cache(cached_closed, cached_activity)

        _dlog("startup",
              "closed_tab initialized with %d rows | activity_tab initialized with %d rows",
              len(self._closed_tab._all_positions),
              len(self._activity_tab._all_activity))

        self._status_bar = QStatusBar()
        if _from_cache:
            self._status_bar.showMessage(
                f"Loaded from cache  •  {len(active)} active"
                f"  •  {len(resolved)} resolved  •  {len(cached_closed)} closed  •  Refreshing…"
            )
        else:
            self._status_bar.showMessage(
                f"Sample data mode  •  {len(active)} active  •  {len(resolved)} resolved"
            )
        self.setStatusBar(self._status_bar)

    def _on_positions_changed(self, active: list, resolved: list, closed: list) -> None:
        self._active_tab.update_positions(active)
        self._resolved_tab.update_positions(resolved)
        before = len(self._closed_tab._all_positions)
        if not self._closed_tab._all_positions:
            self._closed_tab.update_positions(closed)   # first load
        else:
            self._closed_tab.merge_positions(closed)    # refresh — prepend new only
        after = len(self._closed_tab._all_positions)
        _dlog("fetch", "closed_tab: %d → %d rows after live fetch (%d API rows)",
              before, after, len(closed))
        self._loss_watch_tab.update_positions(active)
        self._status_bar.showMessage(
            f"Live Polymarket data  •  {len(active)} active"
            f"  •  {len(resolved)} resolved  •  {len(self._closed_tab._all_positions)} closed"
        )

    def _on_closed_cache_updated(self, all_closed: list) -> None:
        # Backfill complete: inject any newly-cached rows into the Closed tab.
        # load_from_cache deduplicates and appends without touching _loading or _has_more,
        # so infinite-scroll stays functional and the user's scroll position is preserved.
        if all_closed:
            before = len(self._closed_tab._all_positions)
            self._closed_tab.load_from_cache(all_closed)
            after  = len(self._closed_tab._all_positions)
            _dlog("backfill", "closed_tab: %d → %d rows after cache injection", before, after)
        self._status_bar.showMessage(
            f"Live Polymarket data  •  {len(all_closed)} closed positions cached"
        )
