from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.models import ActivePosition, ResolvedPosition
from app.ui.active_positions_table import ActivePositionsTable
from app.ui.pnl_chart import PnlChartWidget
from app.ui.resolved_positions_table import ResolvedPositionsTable

_CARD = """
QFrame {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 6px;
}
"""
_TITLE   = "color: #8b949e; font-size: 11px; font-weight: 600; letter-spacing: 0.8px;"
_NEUTRAL = "color: #c9d1d9; font-size: 20px; font-weight: 700;"
_GREEN   = "color: #3fb950; font-size: 20px; font-weight: 700;"
_RED     = "color: #f85149; font-size: 20px; font-weight: 700;"
_BLUE    = "color: #58a6ff; font-size: 20px; font-weight: 700;"


def _pnl_style(val: float) -> str:
    return _GREEN if val > 0 else (_RED if val < 0 else _NEUTRAL)


def _card(title: str, value: str, val_style: str) -> QFrame:
    frame = QFrame()
    frame.setStyleSheet(_CARD)
    vbox = QVBoxLayout(frame)
    vbox.setContentsMargins(14, 12, 14, 14)
    vbox.setSpacing(6)
    t = QLabel(title.upper())
    t.setStyleSheet(_TITLE)
    v = QLabel(value)
    v.setStyleSheet(val_style)
    v.setAlignment(Qt.AlignmentFlag.AlignLeft)
    vbox.addWidget(t)
    vbox.addWidget(v)
    return frame


def _cards_panel(metrics: dict) -> QWidget:
    panel = QWidget()
    vbox = QVBoxLayout(panel)
    vbox.setContentsMargins(0, 0, 0, 0)
    vbox.setSpacing(10)

    row1 = QHBoxLayout()
    row1.setSpacing(10)
    row1.addWidget(_card("Active Positions Value", f"${metrics['active_positions_value']:,.2f}", _BLUE))
    row1.addWidget(_card("Realized P/L",           f"${metrics['realized_pnl']:,.2f}",           _pnl_style(metrics["realized_pnl"])))

    row2 = QHBoxLayout()
    row2.setSpacing(10)
    row2.addWidget(_card("Win Count",      str(metrics["win_count"]),                  _GREEN))
    row2.addWidget(_card("Loss Count",     str(metrics["loss_count"]),                 _RED))
    row2.addWidget(_card("Unrealized P/L", f"${metrics['unrealized_pnl']:,.2f}",      _pnl_style(metrics["unrealized_pnl"])))

    vbox.addLayout(row1)
    vbox.addLayout(row2)
    return panel


def _divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet("background-color: #21262d; border: none; max-height: 1px;")
    return line


class OverviewWidget(QWidget):
    def __init__(
        self,
        active: List[ActivePosition],
        resolved: List[ResolvedPosition],
        metrics: dict,
    ):
        super().__init__()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        main = QVBoxLayout(content)
        main.setContentsMargins(16, 16, 16, 20)
        main.setSpacing(0)

        # ── Top row: metric cards (left) + P/L chart (right) ──────
        top = QWidget()
        top.setMinimumHeight(280)
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(14)
        top_layout.addWidget(_cards_panel(metrics), 42)
        top_layout.addWidget(PnlChartWidget(resolved), 58)
        main.addWidget(top)

        main.addSpacing(14)
        main.addWidget(_divider())
        main.addSpacing(14)

        # ── Active positions ───────────────────────────────────────
        main.addWidget(ActivePositionsTable(active))

        main.addSpacing(14)
        main.addWidget(_divider())
        main.addSpacing(14)

        # ── Resolved positions ─────────────────────────────────────
        main.addWidget(ResolvedPositionsTable(resolved))

        main.addStretch(1)

        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
