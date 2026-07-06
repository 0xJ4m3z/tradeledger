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

from app.models import ActivePosition
from app.ui.polymarket_menu import attach_table_links

COLUMNS = [
    "Market", "Outcome", "Quantity", "Avg Cost",
    "Current Price", "Current Value", "Unrealized P/L", "P/L %",
]

_GREEN = QColor("#3fb950")
_RED   = QColor("#f85149")


def _cell(text: str, align=Qt.AlignmentFlag.AlignLeft) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
    return item


def _pnl_cell(val: float, fmt: str = "${:,.2f}") -> QTableWidgetItem:
    item = _cell(fmt.format(val), Qt.AlignmentFlag.AlignRight)
    item.setForeground(_GREEN if val >= 0 else _RED)
    return item


def _market_cell(p: ActivePosition) -> QTableWidgetItem:
    item = _cell(p.market)
    if p.slug:
        item.setData(Qt.ItemDataRole.UserRole, p.slug)
        item.setToolTip("Right-click to open on Polymarket")
    return item


class ActivePositionsTable(QWidget):
    def __init__(self, positions: List[ActivePosition]):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self._header = QLabel(f"Active Positions  ({len(positions)})")
        self._header.setStyleSheet("color: #c9d1d9; font-size: 14px; font-weight: 600;")
        layout.addWidget(self._header)

        search = QLineEdit()
        search.setPlaceholderText("Filter by market, outcome...")
        search.setMaximumWidth(420)
        layout.addWidget(search)

        table = QTableWidget(len(positions), len(COLUMNS))
        table.setHorizontalHeaderLabels(COLUMNS)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        for row, p in enumerate(positions):
            table.setItem(row, 0, _market_cell(p))
            table.setItem(row, 1, _cell(p.outcome))
            table.setItem(row, 2, _cell(f"{p.quantity:,.0f}",       Qt.AlignmentFlag.AlignRight))
            table.setItem(row, 3, _cell(f"${p.avg_cost:.4f}",       Qt.AlignmentFlag.AlignRight))
            table.setItem(row, 4, _cell(f"${p.current_price:.4f}",  Qt.AlignmentFlag.AlignRight))
            table.setItem(row, 5, _cell(f"${p.current_value:,.2f}", Qt.AlignmentFlag.AlignRight))
            table.setItem(row, 6, _pnl_cell(p.unrealized_pnl))
            table.setItem(row, 7, _pnl_cell(p.unrealized_pnl_pct, "{:+.1f}%"))

        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(COLUMNS)):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

        self._table = table
        attach_table_links(self._table)
        search.textChanged.connect(self._apply_filter)

        layout.addWidget(table)

    def update_positions(self, positions: List[ActivePosition]) -> None:
        self._header.setText(f"Active Positions  ({len(positions)})")
        self._table.setRowCount(len(positions))
        for row, p in enumerate(positions):
            self._table.setItem(row, 0, _market_cell(p))
            self._table.setItem(row, 1, _cell(p.outcome))
            self._table.setItem(row, 2, _cell(f"{p.quantity:,.0f}",       Qt.AlignmentFlag.AlignRight))
            self._table.setItem(row, 3, _cell(f"${p.avg_cost:.4f}",       Qt.AlignmentFlag.AlignRight))
            self._table.setItem(row, 4, _cell(f"${p.current_price:.4f}",  Qt.AlignmentFlag.AlignRight))
            self._table.setItem(row, 5, _cell(f"${p.current_value:,.2f}", Qt.AlignmentFlag.AlignRight))
            self._table.setItem(row, 6, _pnl_cell(p.unrealized_pnl))
            self._table.setItem(row, 7, _pnl_cell(p.unrealized_pnl_pct, "{:+.1f}%"))

    def _apply_filter(self, text: str) -> None:
        text = text.strip().lower()
        for row in range(self._table.rowCount()):
            visible = not text or any(
                text in (self._table.item(row, col).text().lower()
                         if self._table.item(row, col) else "")
                for col in range(self._table.columnCount())
            )
            self._table.setRowHidden(row, not visible)
