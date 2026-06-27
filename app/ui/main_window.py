from PySide6.QtWidgets import QMainWindow, QStatusBar, QTabWidget

from app.adapters.sample_adapter import load_all
from app.database import save_snapshot
from app.services.metrics import compute_dashboard_metrics
from app.ui.active_positions_table import ActivePositionsTable
from app.ui.dashboard import DashboardWidget
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
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TradeLedger")
        self.setMinimumSize(1200, 780)
        self.setStyleSheet(_STYLE)

        active, resolved = load_all()
        save_snapshot("sample", active, resolved)
        metrics = compute_dashboard_metrics(active, resolved)

        tabs = QTabWidget()
        tabs.addTab(DashboardWidget(metrics),            "Dashboard")
        tabs.addTab(ActivePositionsTable(active),        "Active Positions")
        tabs.addTab(ResolvedPositionsTable(resolved),    "Resolved Positions")
        tabs.addTab(PnlChartWidget(resolved),            "P/L Chart")
        self.setCentralWidget(tabs)

        status = QStatusBar()
        status.showMessage(
            f"Sample data mode  •  {len(active)} active positions  •  {len(resolved)} resolved positions"
        )
        self.setStatusBar(status)
