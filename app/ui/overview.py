from typing import List

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models import ActivePosition, ResolvedPosition
from app.ui.pnl_chart import PnlChartWidget

# ── Colours ────────────────────────────────────────────────────────────────────
_GREEN_C = QColor("#3fb950")
_RED_C   = QColor("#f85149")
_MUTED_C = QColor("#8b949e")

# ── Card style ─────────────────────────────────────────────────────────────────
_CARD_FRAME = """
QFrame {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 6px;
}
"""
_TITLE_S   = "color: #8b949e; font-size: 11px; font-weight: 600; letter-spacing: 0.8px;"
_NEUTRAL_S = "color: #c9d1d9; font-size: 20px; font-weight: 700;"
_GREEN_S   = "color: #3fb950; font-size: 20px; font-weight: 700;"
_RED_S     = "color: #f85149; font-size: 20px; font-weight: 700;"
_BLUE_S    = "color: #58a6ff; font-size: 20px; font-weight: 700;"
_HDR_S     = "color: #c9d1d9; font-size: 14px; font-weight: 600;"

_ACTIVE_COLS   = ["Market", "Outcome", "Quantity", "Avg Cost", "Current Price", "Current Value", "Unrealized P/L", "P/L %"]
_RESOLVED_COLS = ["Market", "Outcome Held", "Winning Outcome", "Qty", "Cost Basis", "Redeem Value", "Realized P/L", "P/L %", "Redeemed"]


# ── Card helpers ───────────────────────────────────────────────────────────────

def _pnl_style(val: float) -> str:
    return _GREEN_S if val > 0 else (_RED_S if val < 0 else _NEUTRAL_S)


def _card(title: str, value: str, val_style: str) -> QFrame:
    frame = QFrame()
    frame.setStyleSheet(_CARD_FRAME)
    vbox = QVBoxLayout(frame)
    vbox.setContentsMargins(14, 12, 14, 14)
    vbox.setSpacing(6)
    t = QLabel(title.upper())
    t.setStyleSheet(_TITLE_S)
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
    row1.addWidget(_card("Active Positions Value", f"${metrics['active_positions_value']:,.2f}", _BLUE_S))
    row1.addWidget(_card("Realized P/L",           f"${metrics['realized_pnl']:,.2f}",           _pnl_style(metrics["realized_pnl"])))

    row2 = QHBoxLayout()
    row2.setSpacing(10)
    row2.addWidget(_card("Win Count",      str(metrics["win_count"]),               _GREEN_S))
    row2.addWidget(_card("Loss Count",     str(metrics["loss_count"]),              _RED_S))
    row2.addWidget(_card("Unrealized P/L", f"${metrics['unrealized_pnl']:,.2f}",   _pnl_style(metrics["unrealized_pnl"])))

    vbox.addLayout(row1)
    vbox.addLayout(row2)
    return panel


# ── Table cell helpers ─────────────────────────────────────────────────────────

def _cell(text: str, align=Qt.AlignmentFlag.AlignLeft) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
    return item


def _pnl_cell(val: float, fmt: str = "${:,.2f}") -> QTableWidgetItem:
    item = _cell(fmt.format(val), Qt.AlignmentFlag.AlignRight)
    item.setForeground(_GREEN_C if val >= 0 else _RED_C)
    return item


def _flat_table(row_count: int, col_headers: list) -> QTableWidget:
    """
    A QTableWidget that expands to its full content height so the outer
    QScrollArea handles page scrolling rather than the table internally.
    """
    table = QTableWidget(row_count, len(col_headers))
    table.setHorizontalHeaderLabels(col_headers)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    # Grow to show all rows — outer scroll area scrolls the page
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
    table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return table


# ── Preview section builders ───────────────────────────────────────────────────

def _active_section(positions: List[ActivePosition]) -> QWidget:
    container = QWidget()
    vbox = QVBoxLayout(container)
    vbox.setContentsMargins(0, 0, 0, 0)
    vbox.setSpacing(8)

    vbox.addWidget(QLabel(f"Active Positions  ({len(positions)})",
                          styleSheet=_HDR_S))

    table = _flat_table(len(positions), _ACTIVE_COLS)

    for row, p in enumerate(positions):
        table.setItem(row, 0, _cell(p.market))
        table.setItem(row, 1, _cell(p.outcome))
        table.setItem(row, 2, _cell(f"{p.quantity:,.0f}",       Qt.AlignmentFlag.AlignRight))
        table.setItem(row, 3, _cell(f"${p.avg_cost:.4f}",       Qt.AlignmentFlag.AlignRight))
        table.setItem(row, 4, _cell(f"${p.current_price:.4f}",  Qt.AlignmentFlag.AlignRight))
        table.setItem(row, 5, _cell(f"${p.current_value:,.2f}", Qt.AlignmentFlag.AlignRight))
        table.setItem(row, 6, _pnl_cell(p.unrealized_pnl))
        table.setItem(row, 7, _pnl_cell(p.unrealized_pnl_pct, "{:+.1f}%"))

    hdr = table.horizontalHeader()
    hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    for col in range(1, len(_ACTIVE_COLS)):
        hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

    vbox.addWidget(table)
    return container


def _resolved_section(positions: List[ResolvedPosition]) -> QWidget:
    container = QWidget()
    vbox = QVBoxLayout(container)
    vbox.setContentsMargins(0, 0, 0, 0)
    vbox.setSpacing(8)

    vbox.addWidget(QLabel(f"Resolved Positions  ({len(positions)})",
                          styleSheet=_HDR_S))

    table = _flat_table(len(positions), _RESOLVED_COLS)

    for row, p in enumerate(positions):
        outcome_item = _cell(p.outcome_held)
        outcome_item.setForeground(_GREEN_C if p.is_win else _RED_C)

        table.setItem(row, 0, _cell(p.market))
        table.setItem(row, 1, outcome_item)
        table.setItem(row, 2, _cell(p.winning_outcome))
        table.setItem(row, 3, _cell(f"{p.quantity:,.0f}",        Qt.AlignmentFlag.AlignRight))
        table.setItem(row, 4, _cell(f"${p.cost_basis:,.2f}",     Qt.AlignmentFlag.AlignRight))
        table.setItem(row, 5, _cell(f"${p.redeem_value:,.2f}",   Qt.AlignmentFlag.AlignRight))
        table.setItem(row, 6, _pnl_cell(p.realized_pnl))
        table.setItem(row, 7, _pnl_cell(p.realized_pnl_pct, "{:+.1f}%"))

        status = _cell("Yes" if p.redeemed else "Pending")
        status.setForeground(_GREEN_C if p.redeemed else _MUTED_C)
        table.setItem(row, 8, status)

    hdr = table.horizontalHeader()
    hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    for col in range(1, len(_RESOLVED_COLS)):
        hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

    vbox.addWidget(table)
    return container


def _divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet("background-color: #21262d; border: none; max-height: 1px;")
    return line


# ── Overview widget ────────────────────────────────────────────────────────────

class OverviewWidget(QWidget):
    def __init__(
        self,
        active: List[ActivePosition],
        resolved: List[ResolvedPosition],
        metrics: dict,
    ):
        super().__init__()

        # One scroll area wraps the entire page
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        main = QVBoxLayout(content)
        main.setContentsMargins(16, 16, 16, 20)
        main.setSpacing(0)

        # ── Top: metric cards (left) + P/L chart (right) ──────────
        top = QWidget()
        top.setMinimumHeight(280)
        top_row = QHBoxLayout(top)
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(14)
        top_row.addWidget(_cards_panel(metrics), 42)
        top_row.addWidget(PnlChartWidget(resolved), 58)
        main.addWidget(top)

        main.addSpacing(16)
        main.addWidget(_divider())
        main.addSpacing(16)

        # ── Active positions ───────────────────────────────────────
        main.addWidget(_active_section(active))

        main.addSpacing(16)
        main.addWidget(_divider())
        main.addSpacing(16)

        # ── Resolved positions ─────────────────────────────────────
        main.addWidget(_resolved_section(resolved))

        # Absorbs leftover space when content is shorter than viewport
        main.addStretch(1)

        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
