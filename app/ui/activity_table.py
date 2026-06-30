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

from app.debug import _dlog
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

_SCROLL_THRESHOLD_PX = 80

# Show first 2000 rows immediately; scroll extends from _all_activity before
# requesting additional data from the API/DB.
_INITIAL_DISPLAY = 2000


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
    refresh_requested   = Signal()
    load_more_requested = Signal(int)  # emits the current row count as the next offset

    def __init__(self, activity: List[UserActivity]):
        super().__init__()
        self._all_activity: List[UserActivity] = list(activity)
        self._displayed_count = min(_INITIAL_DISPLAY, len(activity))
        self._has_more  = True
        self._loading   = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

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

        display_slice = self._all_activity[:self._displayed_count]
        self._table = QTableWidget(len(display_slice), len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        for row, a in enumerate(display_slice):
            _populate_row(self._table, row, a)

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for col in [0, 1, 3, 4, 5, 6, 7]:
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

        self._table.verticalScrollBar().valueChanged.connect(self._on_scroll)

        search.textChanged.connect(self._apply_filter)
        layout.addWidget(self._table)

    def update_activity(self, activity: List[UserActivity]) -> None:
        """Merge fresh activity: first call sets the list; subsequent calls prepend new records."""
        old_all = len(self._all_activity)
        if not self._all_activity:
            # First load — populate from scratch
            self._all_activity    = list(activity)
            self._displayed_count = min(_INITIAL_DISPLAY, len(activity))
            self._has_more        = len(activity) >= 100
            self._loading         = False
            self._load_status.setText("")
            self._header.setText(f"Activity  ({len(activity)})")
            display_slice = self._all_activity[:self._displayed_count]
            self._table.setRowCount(len(display_slice))
            for row, a in enumerate(display_slice):
                _populate_row(self._table, row, a)
            _dlog("activity_table",
                  "update_activity(REPLACE): incoming=%d  all=%d  displayed=%d",
                  len(activity), len(self._all_activity), self._displayed_count)
            return

        # Refresh — prepend any records newer than what we already have
        seen  = {(a.timestamp, a.type, a.side, a.size) for a in self._all_activity}
        fresh = [a for a in activity if (a.timestamp, a.type, a.side, a.size) not in seen]
        if not fresh:
            _dlog("activity_table",
                  "update_activity(MERGE): incoming=%d  0 new  all=%d  displayed=%d",
                  len(activity), old_all, self._displayed_count)
            return
        self._all_activity    = fresh + self._all_activity
        self._displayed_count += len(fresh)
        self._header.setText(f"Activity  ({len(self._all_activity)})")
        for i, a in enumerate(fresh):
            self._table.insertRow(i)
            _populate_row(self._table, i, a)
        _dlog("activity_table",
              "update_activity(MERGE): incoming=%d  +%d new  all=%d→%d  displayed=%d",
              len(activity), len(fresh), old_all, len(self._all_activity), self._displayed_count)

    def reset_activity(self) -> None:
        """Clear all loaded activity (called on wallet change)."""
        self._all_activity    = []
        self._displayed_count = 0
        self._has_more        = True
        self._loading         = False
        self._load_status.setText("")
        self._header.setText("Activity  (0)")
        self._table.setRowCount(0)

    def append_activity(self, new_records: List[UserActivity]) -> None:
        """Append a page of older activity records (called on scroll-triggered load-more)."""
        old_all = len(self._all_activity)
        self._loading = False
        if not new_records:
            self._has_more = False
            self._load_status.setText("All activity loaded")
            _dlog("activity_table", "append_activity: empty page — done, all=%d", old_all)
            return

        # Deduplicate by (timestamp, type, side, size) — the API can overlap
        seen = {(a.timestamp, a.type, a.side, a.size) for a in self._all_activity}
        fresh = [a for a in new_records if (a.timestamp, a.type, a.side, a.size) not in seen]

        if not fresh:
            self._has_more = False
            self._load_status.setText("All activity loaded")
            _dlog("activity_table",
                  "append_activity: %d incoming all dupes — done, all=%d", len(new_records), old_all)
            return

        self._all_activity.extend(fresh)
        self._has_more = True
        self._load_status.setText("")
        self._header.setText(f"Activity  ({len(self._all_activity)})")

        start_row = self._table.rowCount()
        self._table.setRowCount(start_row + len(fresh))
        for i, a in enumerate(fresh):
            _populate_row(self._table, start_row + i, a)
        self._displayed_count += len(fresh)
        _dlog("activity_table",
              "append_activity: incoming=%d  +%d new  all=%d→%d  displayed=%d",
              len(new_records), len(fresh), old_all, len(self._all_activity), self._displayed_count)

    def _on_scroll(self, value: int) -> None:
        sb = self._table.verticalScrollBar()
        if sb.maximum() <= 0 or value < sb.maximum() - _SCROLL_THRESHOLD_PX:
            return
        if self._loading:
            return
        # Extend the table from in-memory _all_activity before requesting from API/DB
        if self._displayed_count < len(self._all_activity):
            start = self._displayed_count
            end   = min(start + 100, len(self._all_activity))
            current_rows = self._table.rowCount()
            self._table.setRowCount(current_rows + (end - start))
            for i, a in enumerate(self._all_activity[start:end]):
                _populate_row(self._table, current_rows + i, a)
            self._displayed_count = end
            _dlog("activity_table",
                  "_on_scroll: rendered in-memory rows %d→%d  (total in-memory=%d)",
                  start, end, len(self._all_activity))
            return
        # All in-memory rows shown — request older data from API/DB
        if self._has_more:
            self._loading = True
            self._load_status.setText("Loading…")
            _dlog("activity_table",
                  "_on_scroll: in-memory exhausted at %d rows — requesting API offset=%d",
                  self._displayed_count, len(self._all_activity))
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
