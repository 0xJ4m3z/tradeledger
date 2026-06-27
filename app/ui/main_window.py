from PySide6.QtWidgets import QMainWindow, QStatusBar, QTabWidget

from app.adapters.sample_adapter import load_all
from app.database import save_snapshot
from app.services.metrics import compute_dashboard_metrics
from app.ui.active_positions_table import ActivePositionsTable
from app.ui.overview import OverviewWidget
from app.ui.pnl_chart import PnlChartWidget
from app.ui.resolved_positions_table import ResolvedPositionsTable

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

        active, resolved = load_all()
        save_snapshot("sample", active, resolved)
        metrics = compute_dashboard_metrics(active, resolved)

        overview           = OverviewWidget(active, resolved, metrics)
        self._active_tab   = ActivePositionsTable(active)
        self._resolved_tab = ResolvedPositionsTable(resolved, label="Redeemable Positions")
        self._closed_tab   = ResolvedPositionsTable([], label="Closed Positions — most recent 100")

        overview.positions_changed.connect(self._on_positions_changed)

        tabs = QTabWidget()
        tabs.addTab(overview,                 "Overview")
        tabs.addTab(self._active_tab,         "Active Positions")
        tabs.addTab(self._resolved_tab,       "Redeemable Positions")
        tabs.addTab(self._closed_tab,         "Closed Positions")
        tabs.addTab(PnlChartWidget(resolved), "P/L Chart")
        self.setCentralWidget(tabs)

        self._status_bar = QStatusBar()
        self._status_bar.showMessage(
            f"Sample data mode  •  {len(active)} active positions  •  {len(resolved)} resolved positions"
        )
        self.setStatusBar(self._status_bar)

    def _on_positions_changed(self, active: list, redeemable: list, closed: list) -> None:
        self._active_tab.update_positions(active)
        self._resolved_tab.update_positions(redeemable)
        self._closed_tab.update_positions(closed)
        self._status_bar.showMessage(
            f"Live Polymarket data  •  {len(active)} active"
            f"  •  {len(redeemable)} redeemable  •  {len(closed)} closed"
        )
