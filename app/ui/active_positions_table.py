from typing import List

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models import ActivePosition

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


class ActivePositionsTable(QWidget):
    def __init__(self, positions: List[ActivePosition]):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QLabel(f"Active Positions  ({len(positions)})")
        header.setStyleSheet("color: #c9d1d9; font-size: 14px; font-weight: 600;")
        layout.addWidget(header)

        table = QTableWidget(len(positions), len(COLUMNS))
        table.setHorizontalHeaderLabels(COLUMNS)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        for row, p in enumerate(positions):
            table.setItem(row, 0, _cell(p.market))
            table.setItem(row, 1, _cell(p.outcome))
            table.setItem(row, 2, _cell(f"{p.quantity:,.0f}", Qt.AlignmentFlag.AlignRight))
            table.setItem(row, 3, _cell(f"${p.avg_cost:.4f}", Qt.AlignmentFlag.AlignRight))
            table.setItem(row, 4, _cell(f"${p.current_price:.4f}", Qt.AlignmentFlag.AlignRight))
            table.setItem(row, 5, _cell(f"${p.current_value:,.2f}", Qt.AlignmentFlag.AlignRight))
            table.setItem(row, 6, _pnl_cell(p.unrealized_pnl))
            table.setItem(row, 7, _pnl_cell(p.unrealized_pnl_pct, "{:+.1f}%"))

        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(COLUMNS)):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(table)
