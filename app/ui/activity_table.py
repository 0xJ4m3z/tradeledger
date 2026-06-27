from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models import UserActivity

COLUMNS = ["Time (UTC)", "Type", "Market", "Outcome", "Side", "Tokens", "USDC", "Price"]

_GREEN  = QColor("#3fb950")
_RED    = QColor("#f85149")
_MUTED  = QColor("#8b949e")
_BLUE   = QColor("#58a6ff")
_YELLOW = QColor("#e3b341")

_TYPE_COLORS = {
    "TRADE":          None,
    "REDEEM":         _GREEN,
    "REWARD":         _YELLOW,
    "MAKER_REBATE":   _YELLOW,
    "TAKER_REBATE":   _YELLOW,
    "REFERRAL_REWARD": _YELLOW,
    "SPLIT":          _BLUE,
    "MERGE":          _BLUE,
    "DEPOSIT":        _GREEN,
    "WITHDRAWAL":     _RED,
}


def _cell(text: str, align=Qt.AlignmentFlag.AlignLeft) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
    return item


def _populate_row(table: QTableWidget, row: int, a: UserActivity) -> None:
    side_color = _GREEN if a.side == "BUY" else (_RED if a.side == "SELL" else _MUTED)
    type_color = _TYPE_COLORS.get(a.type, _MUTED)

    type_item = _cell(a.type)
    if type_color:
        type_item.setForeground(type_color)

    side_item = _cell(a.side or "—")
    side_item.setForeground(side_color)

    table.setItem(row, 0, _cell(a.datetime_utc))
    table.setItem(row, 1, type_item)
    table.setItem(row, 2, _cell(a.title or "—"))
    table.setItem(row, 3, _cell(a.outcome or "—"))
    table.setItem(row, 4, side_item)
    table.setItem(row, 5, _cell(f"{a.size:,.2f}"      if a.size      else "—", Qt.AlignmentFlag.AlignRight))
    table.setItem(row, 6, _cell(f"${a.usdc_size:,.2f}" if a.usdc_size else "—", Qt.AlignmentFlag.AlignRight))
    table.setItem(row, 7, _cell(f"{a.price:.4f}"       if a.price     else "—", Qt.AlignmentFlag.AlignRight))


class ActivityTable(QWidget):
    refresh_requested = Signal()

    def __init__(self, activity: List[UserActivity]):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Header row with Refresh button
        header_row = QHBoxLayout()
        self._header = QLabel(f"Activity  ({len(activity)})")
        self._header.setStyleSheet("color: #c9d1d9; font-size: 14px; font-weight: 600;")
        header_row.addWidget(self._header)
        header_row.addStretch()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setStyleSheet(
            "background-color: #21262d; border: 1px solid #30363d; border-radius: 4px;"
            " color: #c9d1d9; padding: 4px 14px; font-size: 12px;"
        )
        refresh_btn.clicked.connect(self.refresh_requested)
        header_row.addWidget(refresh_btn)
        layout.addLayout(header_row)

        search = QLineEdit()
        search.setPlaceholderText("Filter by market, type, outcome, side…")
        search.setMaximumWidth(480)
        layout.addWidget(search)

        self._table = QTableWidget(len(activity), len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        for row, a in enumerate(activity):
            _populate_row(self._table, row, a)

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)   # Market column stretches
        for col in [0, 1, 3, 4, 5, 6, 7]:
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

        search.textChanged.connect(self._apply_filter)
        layout.addWidget(self._table)

    def update_activity(self, activity: List[UserActivity]) -> None:
        self._header.setText(f"Activity  ({len(activity)})")
        self._table.setRowCount(len(activity))
        for row, a in enumerate(activity):
            _populate_row(self._table, row, a)

    def _apply_filter(self, text: str) -> None:
        text = text.strip().lower()
        for row in range(self._table.rowCount()):
            visible = not text or any(
                text in (self._table.item(row, col).text().lower()
                         if self._table.item(row, col) else "")
                for col in range(self._table.columnCount())
            )
            self._table.setRowHidden(row, not visible)
