from typing import List

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models import ResolvedPosition

COLUMNS = [
    "Market", "Outcome Held", "Winning Outcome", "Qty",
    "Cost Basis", "Redeem Value", "Realized P/L", "P/L %", "Redeemed",
]

_GREEN = QColor("#3fb950")
_RED   = QColor("#f85149")
_MUTED = QColor("#8b949e")


def _cell(text: str, align=Qt.AlignmentFlag.AlignLeft) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
    return item


def _pnl_cell(val: float, fmt: str = "${:,.2f}") -> QTableWidgetItem:
    item = _cell(fmt.format(val), Qt.AlignmentFlag.AlignRight)
    item.setForeground(_GREEN if val >= 0 else _RED)
    return item


class ResolvedPositionsTable(QWidget):
    def __init__(self, positions: List[ResolvedPosition]):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self._header = QLabel(f"Resolved Positions  ({len(positions)})")
        self._header.setStyleSheet("color: #c9d1d9; font-size: 14px; font-weight: 600;")
        layout.addWidget(self._header)

        search = QLineEdit()
        search.setPlaceholderText("Filter by market, outcome, redeemed status...")
        search.setMaximumWidth(480)
        layout.addWidget(search)

        table = QTableWidget(len(positions), len(COLUMNS))
        table.setHorizontalHeaderLabels(COLUMNS)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        for row, p in enumerate(positions):
            outcome_item = _cell(p.outcome_held)
            outcome_item.setForeground(_GREEN if p.is_win else _RED)

            table.setItem(row, 0, _cell(p.market))
            table.setItem(row, 1, outcome_item)
            table.setItem(row, 2, _cell(p.winning_outcome))
            table.setItem(row, 3, _cell(f"{p.quantity:,.0f}",       Qt.AlignmentFlag.AlignRight))
            table.setItem(row, 4, _cell(f"${p.cost_basis:,.2f}",    Qt.AlignmentFlag.AlignRight))
            table.setItem(row, 5, _cell(f"${p.redeem_value:,.2f}",  Qt.AlignmentFlag.AlignRight))
            table.setItem(row, 6, _pnl_cell(p.realized_pnl))
            table.setItem(row, 7, _pnl_cell(p.realized_pnl_pct, "{:+.1f}%"))

            status = _cell("Yes" if p.redeemed else "Pending")
            status.setForeground(_GREEN if p.redeemed else _MUTED)
            table.setItem(row, 8, status)

        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(COLUMNS)):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

        self._table = table
        search.textChanged.connect(self._apply_filter)

        layout.addWidget(table)

    def update_positions(self, positions: List[ResolvedPosition]) -> None:
        self._header.setText(f"Resolved Positions  ({len(positions)})")
        self._table.setRowCount(len(positions))
        for row, p in enumerate(positions):
            outcome_item = _cell(p.outcome_held)
            outcome_item.setForeground(_GREEN if p.is_win else _RED)
            self._table.setItem(row, 0, _cell(p.market))
            self._table.setItem(row, 1, outcome_item)
            self._table.setItem(row, 2, _cell(p.winning_outcome))
            self._table.setItem(row, 3, _cell(f"{p.quantity:,.0f}",       Qt.AlignmentFlag.AlignRight))
            self._table.setItem(row, 4, _cell(f"${p.cost_basis:,.2f}",    Qt.AlignmentFlag.AlignRight))
            self._table.setItem(row, 5, _cell(f"${p.redeem_value:,.2f}",  Qt.AlignmentFlag.AlignRight))
            self._table.setItem(row, 6, _pnl_cell(p.realized_pnl))
            self._table.setItem(row, 7, _pnl_cell(p.realized_pnl_pct, "{:+.1f}%"))
            status = _cell("Yes" if p.redeemed else "Pending")
            status.setForeground(_GREEN if p.redeemed else _MUTED)
            self._table.setItem(row, 8, status)

    def _apply_filter(self, text: str) -> None:
        text = text.strip().lower()
        for row in range(self._table.rowCount()):
            visible = not text or any(
                text in (self._table.item(row, col).text().lower()
                         if self._table.item(row, col) else "")
                for col in range(self._table.columnCount())
            )
            self._table.setRowHidden(row, not visible)
