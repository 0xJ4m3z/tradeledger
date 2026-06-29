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
    "TRADE":           None,
    "REDEEM":          _GREEN,
    "REWARD":          _GREEN,
    "MAKER_REBATE":    _YELLOW,
    "TAKER_REBATE":    _YELLOW,
    "REFERRAL_REWARD": _YELLOW,
    "SPLIT":           _BLUE,
    "MERGE":           _BLUE,
    "DEPOSIT":         _GREEN,
    "WITHDRAWAL":      _RED,
}

# Trigger a load when this many pixels remain before the very bottom of the scroll
_SCROLL_THRESHOLD_PX = 80


def _cell(text: str, align=Qt.AlignmentFlag.AlignLeft) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
    return item


def _populate_row(table: QTableWidget, row: int, a: UserActivity) -> None:
    is_redeem = a.type == "REDEEM"
    side_color = _GREEN if a.side == "BUY" else (_RED if a.side == "SELL" else _MUTED)
    type_color = _TYPE_COLORS.get(a.type, _MUTED)

    type_item = _cell(a.type)
    if type_color:
        type_item.setForeground(type_color)

    # For REDEEM events: side column shows "REDEEM"; outcome shows Win/Loss
    if is_redeem:
        side_item = _cell("REDEEM")
        side_item.setForeground(_MUTED)
        if a.usdc_size > 0:
            outcome_text = "Win"
            outcome_color = _GREEN
        else:
            outcome_text = "Loss"
            outcome_color = _RED
        outcome_item = _cell(outcome_text)
        outcome_item.setForeground(outcome_color)
    else:
        side_item = _cell(a.side or "—")
        side_item.setForeground(side_color)
        outcome_item = _cell(a.outcome or "—")

    table.setItem(row, 0, _cell(a.datetime_utc))
    table.setItem(row, 1, type_item)
    table.setItem(row, 2, _cell(a.title or "—"))
    table.setItem(row, 3, outcome_item)
    table.setItem(row, 4, side_item)
    table.setItem(row, 5, _cell(f"{a.size:,.2f}"       if a.size      else "—", Qt.AlignmentFlag.AlignRight))
    table.setItem(row, 6, _cell(f"${a.usdc_size:,.2f}" if a.usdc_size else "—", Qt.AlignmentFlag.AlignRight))
    table.setItem(row, 7, _cell(f"{a.price:.4f}"       if a.price     else "—", Qt.AlignmentFlag.AlignRight))


class ActivityTable(QWidget):
    refresh_requested  = Signal()
    load_more_requested = Signal(int)   # emits the current row count as the next offset

    def __init__(self, activity: List[UserActivity]):
        super().__init__()
        self._all_activity: List[UserActivity] = list(activity)
        self._has_more  = True   # assume there might be more until proven otherwise
        self._loading   = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Header row
        header_row = QHBoxLayout()
        self._header = QLabel(f"Activity  ({len(activity)})")
        self._header.setStyleSheet("color: #c9d1d9; font-size: 14px; font-weight: 600;")
        header_row.addWidget(self._header)
        header_row.addStretch()
        self._load_status = QLabel("")
        self._load_status.setStyleSheet("color: #8b949e; font-size: 12px;")
        header_row.addWidget(self._load_status)
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
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for col in [0, 1, 3, 4, 5, 6, 7]:
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

        # Scroll-to-bottom detection
        self._table.verticalScrollBar().valueChanged.connect(self._on_scroll)

        search.textChanged.connect(self._apply_filter)
        layout.addWidget(self._table)

    def update_activity(self, activity: List[UserActivity]) -> None:
        """Replace the full activity list (called on initial/refresh fetch)."""
        self._all_activity = list(activity)
        self._has_more     = len(activity) >= 100   # full page → probably more
        self._loading      = False
        self._load_status.setText("")
        self._header.setText(f"Activity  ({len(activity)})")
        self._table.setRowCount(len(activity))
        for row, a in enumerate(activity):
            _populate_row(self._table, row, a)

    def append_activity(self, new_records: List[UserActivity]) -> None:
        """Append a page of older activity records (called on scroll-triggered load-more)."""
        self._loading = False
        if not new_records:
            self._has_more = False
            self._load_status.setText("All activity loaded")
            return

        # Deduplicate by (timestamp, type, side, size) — the API can overlap
        seen = {(a.timestamp, a.type, a.side, a.size) for a in self._all_activity}
        fresh = [a for a in new_records if (a.timestamp, a.type, a.side, a.size) not in seen]

        if not fresh:
            self._has_more = False
            self._load_status.setText("All activity loaded")
            return

        self._all_activity.extend(fresh)
        self._has_more = len(new_records) >= 100
        self._load_status.setText("" if self._has_more else "All activity loaded")
        self._header.setText(f"Activity  ({len(self._all_activity)})")

        start_row = self._table.rowCount()
        self._table.setRowCount(start_row + len(fresh))
        for i, a in enumerate(fresh):
            _populate_row(self._table, start_row + i, a)

    def _on_scroll(self, value: int) -> None:
        sb = self._table.verticalScrollBar()
        if (
            self._has_more
            and not self._loading
            and sb.maximum() > 0
            and value >= sb.maximum() - _SCROLL_THRESHOLD_PX
        ):
            self._loading = True
            self._load_status.setText("Loading…")
            self.load_more_requested.emit(len(self._all_activity))

    def _apply_filter(self, text: str) -> None:
        text = text.strip().lower()
        for row in range(self._table.rowCount()):
            visible = not text or any(
                text in (self._table.item(row, col).text().lower()
                         if self._table.item(row, col) else "")
                for col in range(self._table.columnCount())
            )
            self._table.setRowHidden(row, not visible)
