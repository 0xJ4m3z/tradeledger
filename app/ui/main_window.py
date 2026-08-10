from PySide6.QtWidgets import QMainWindow, QStatusBar, QTabWidget, QVBoxLayout, QWidget

from app.adapters.sample_adapter import load_all
from app.debug import _dlog
from app.services import notes as _notes
from app.database import (
    load_active_positions_cache,
    load_all_activity_for_wallet,
    load_all_closed_for_wallet,
    load_last_wallet,
    load_wallet_snapshots,
    save_snapshot,
    upsert_activity_derived_closed_positions,
)
from app.services.pnl_today import derive_closed_from_activity
from app.services.metrics import compute_dashboard_metrics
from app.ui.activity_table import ActivityTable
from app.ui.loss_watch_tab import LossWatchTab
from app.ui.overview import OverviewWidget
from app.ui.pnl_tab import PnlTab
from app.ui.resolved_positions_table import ResolvedPositionsTable
from app.ui.settings_tab import SettingsTab
from app.ui.total_value_chart import TotalValueChartWidget
from app.ui.wallet_panel import WalletPanel

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
        _init_wallet    = load_last_wallet()
        _notes.load_for_wallet(_init_wallet or "")
        cached_active   = load_active_positions_cache(_init_wallet)    if _init_wallet else []
        cached_activity = load_all_activity_for_wallet(_init_wallet)   if _init_wallet else []

        # Derive closed positions from REDEEM events in the activity feed and persist
        # to SQLite before loading the closed tab.  This fills the gap when the
        # /closed-positions API only returns the most-recent ~100 records: the activity
        # feed already contains REDEEM events going back to the start of history.
        # Records are only inserted when no API-sourced record exists for the same
        # (market, outcome_held), so API data is never overwritten.
        if _init_wallet and cached_activity:
            _derived = derive_closed_from_activity(cached_activity)
            _n_derived = upsert_activity_derived_closed_positions(_derived, _init_wallet)
            _dlog("startup", "derived %d new closed positions from activity feed "
                  "(%d total REDEEM-derived candidates)", _n_derived, len(_derived))

        cached_closed   = load_all_closed_for_wallet(_init_wallet)     if _init_wallet else []

        _dlog("startup",
              "wallet=%s | active=%d | closed=%d | activity=%d",
              (_init_wallet[:10] + "...") if _init_wallet else "(none)",
              len(cached_active), len(cached_closed), len(cached_activity))
        # Fall back to sample data only when no cache exists (first run / new wallet)
        if not cached_active:
            active, resolved = load_all()
            save_snapshot("sample", active, resolved)
            _from_cache = False
        else:
            active, resolved = cached_active, []
            _from_cache = True

        metrics = compute_dashboard_metrics(active, resolved)

        # WalletPanel lives in the Settings tab; OverviewWidget holds only a reference.
        wallet_panel           = WalletPanel()
        self._wallet_panel     = wallet_panel   # kept for closeEvent cleanup
        overview               = OverviewWidget(active, resolved, metrics, wallet_panel)
        self._overview         = overview       # kept for closeEvent cleanup
        self._loss_watch_tab   = LossWatchTab()
        self._closed_tab       = ResolvedPositionsTable(
            cached_closed, label="Closed Positions", show_refresh=True, show_date_filter=True
        )
        self._activity_tab     = ActivityTable(cached_activity)
        self._pnl_tab          = PnlTab(cached_closed)

        # Seed slug maps for all tabs that show Polymarket links.
        # Many DB-cached positions have slug=None (cached before slug support was added);
        # this seeds from whatever slugs ARE available at startup so links work immediately.
        if cached_closed:
            _startup_slug_map = {p.market: p.slug for p in cached_closed if p.slug}
            if _startup_slug_map:
                self._activity_tab.update_slug_map(_startup_slug_map)
                self._closed_tab.update_slug_map(_startup_slug_map)

        # Seed activity into the Closed tab immediately so double-click works
        # from the first render (before any live fetch).
        if cached_activity:
            self._closed_tab.set_activity(cached_activity)

        # ── Signal wiring ───────────────────────────────────────────────────────
        overview.positions_changed.connect(self._on_positions_changed)
        overview.activity_changed.connect(self._activity_tab.update_activity)
        overview.activity_changed.connect(self._closed_tab.set_activity)
        self._closed_tab.refresh_requested.connect(overview.request_refresh)
        self._activity_tab.refresh_requested.connect(overview.request_refresh)

        # Loss Watch tab ↔ Overview card stay in sync via DB
        self._loss_watch_tab.acknowledged_changed.connect(overview.reload_acknowledged)

        # Closed positions: backfill pages arrive incrementally → push to Closed tab + P/L tab
        overview.closed_cache_updated.connect(self._on_closed_cache_updated)
        overview.closed_cache_updated.connect(self._pnl_tab.update_positions)

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

        # ── Settings tab ────────────────────────────────────────────────────────
        self._settings_tab = SettingsTab(wallet_panel)
        self._settings_tab.chart_settings_changed.connect(overview.apply_chart_style)
        # Apply persisted chart style on startup
        _sm, _lw, _fa = self._settings_tab.initial_chart_style()
        overview.apply_chart_style(_sm, _lw, _fa)

        # ── User stream (authenticated WebSocket) ───────────────────────────────
        # Give Overview a reference to SettingsTab so it can update the status label.
        overview.set_settings_tab(self._settings_tab)
        # Wire file-picker changes in Settings → start/stop user stream
        self._settings_tab.credentials_file_changed.connect(overview.on_credentials_file_changed)
        # Start stream immediately if a credentials file was saved from a previous session
        _creds_path = self._settings_tab.initial_credentials_file()
        if _creds_path:
            overview.on_credentials_file_changed(_creds_path)

        # ── Tabs ────────────────────────────────────────────────────────────────
        tabs = QTabWidget()
        tabs.addTab(overview,                  "Overview")
        tabs.addTab(self._pnl_tab,             "P/L")
        tabs.addTab(self._loss_watch_tab,      "Loss Watch")
        tabs.addTab(self._closed_tab,          "Closed Positions")
        tabs.addTab(self._activity_tab,        "Activity")
        tabs.addTab(tv_tab,                    "Total Tracked Value")
        tabs.addTab(self._settings_tab,        "Settings")
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

    # ── App close ──────────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        """Gracefully stop all background threads before the window closes."""
        # Stop WebSocket streams owned by overview
        self._overview._stop_stream()
        self._overview._stop_user_stream()
        # Stop wallet fetch / backfill threads (waits up to ~2 s per thread, then terminates)
        self._wallet_panel.stop_all_threads()
        super().closeEvent(event)

    def _on_positions_changed(self, active: list, resolved: list, closed: list) -> None:
        before = len(self._closed_tab._all_positions)
        if not self._closed_tab._all_positions:
            self._closed_tab.update_positions(closed)   # first load
        else:
            self._closed_tab.merge_positions(closed)    # refresh — prepend new only
        after = len(self._closed_tab._all_positions)
        _dlog("fetch", "closed_tab: %d → %d rows after live fetch (%d API rows)",
              before, after, len(closed))
        self._pnl_tab.update_positions(closed)
        self._loss_watch_tab.update_positions(active)
        # Push fresh slug map to all tabs so right-click links appear everywhere.
        _slug_map = {p.market: p.slug for p in self._closed_tab._all_positions if p.slug}
        self._activity_tab.update_slug_map(_slug_map)
        self._closed_tab.update_slug_map(_slug_map)
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
            # Backfill slugs for any rows that gained them via this cache update.
            _slug_map = {p.market: p.slug for p in self._closed_tab._all_positions if p.slug}
            if _slug_map:
                self._closed_tab.update_slug_map(_slug_map)
                self._activity_tab.update_slug_map(_slug_map)
        self._status_bar.showMessage(
            f"Live Polymarket data  •  {len(all_closed)} closed positions cached"
        )
