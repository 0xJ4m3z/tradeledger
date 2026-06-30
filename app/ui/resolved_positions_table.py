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

from app.models import ResolvedPosition

COLUMNS = [
    "Market", "Outcome Held", "Winning Outcome", "Qty",
    "Cost Basis", "Redeem Value", "Realized P/L", "P/L %", "Redeemed",
]

_GREEN = QColor("#3fb950")
_RED   = QColor("#f85149")
_MUTED = QColor("#8b949e")

_SCROLL_THRESHOLD_PX = 80


def _cell(text: str, align=Qt.AlignmentFlag.AlignLeft) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
    return item


def _pnl_cell(val: float, fmt: str = "${:,.2f}") -> QTableWidgetItem:
    item = _cell(fmt.format(val), Qt.AlignmentFlag.AlignRight)
    item.setForeground(_GREEN if val >= 0 else _RED)
    return item


def _populate_row(table: QTableWidget, row: int, p: ResolvedPosition) -> None:
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


class ResolvedPositionsTable(QWidget):
    refresh_requested  = Signal()
    load_more_requested = Signal(int)  # emits current row count as next offset

    def __init__(
        self,
        positions: List[ResolvedPosition],
        label: str = "Resolved Positions",
        show_refresh: bool = False,
    ):
        super().__init__()
        self._label          = label
        self._all_positions  = list(positions)
        self._has_more       = True
        self._loading        = False
        self._infinite_scroll = show_refresh  # only Closed Positions tab uses scroll-load

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header_row = QHBoxLayout()
        self._header = QLabel(f"{label}  ({len(positions)})")
        self._header.setStyleSheet("color: #c9d1d9; font-size: 14px; font-weight: 600;")
        header_row.addWidget(self._header)
        header_row.addStretch()
        self._load_status = QLabel("")
        self._load_status.setStyleSheet("color: #8b949e; font-size: 12px;")
        header_row.addWidget(self._load_status)
        if show_refresh:
            refresh_btn = QPushButton("Refresh")
            refresh_btn.setStyleSheet(
                "background-color: #21262d; border: 1px solid #30363d; border-radius: 4px;"
                " color: #c9d1d9; padding: 4px 14px; font-size: 12px;"
            )
            refresh_btn.clicked.connect(self.refresh_requested)
            header_row.addWidget(refresh_btn)
        layout.addLayout(header_row)

        search = QLineEdit()
        search.setPlaceholderText("Filter by market, outcome, result...")
        search.setMaximumWidth(480)
        layout.addWidget(search)

        self._table = QTableWidget(len(positions), len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        for row, p in enumerate(positions):
            _populate_row(self._table, row, p)

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(COLUMNS)):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

        if self._infinite_scroll:
            self._table.verticalScrollBar().valueChanged.connect(self._on_scroll)

        self._table = self._table
        search.textChanged.connect(self._apply_filter)
        layout.addWidget(self._table)

    def update_positions(self, positions: List[ResolvedPosition]) -> None:
        """Replace all positions (called on initial/refresh fetch)."""
        self._all_positions = list(positions)
        self._has_more      = len(positions) >= 100
        self._loading       = False
        self._load_status.setText("")
        self._header.setText(f"{self._label}  ({len(positions)})")
        self._table.setRowCount(len(positions))
        for row, p in enumerate(positions):
            _populate_row(self._table, row, p)

    def merge_positions(self, new_records: List[ResolvedPosition]) -> None:
        """Prepend any new records not already loaded (called on refresh, not first load)."""
        seen  = {(p.market, p.outcome_held, p.cost_basis) for p in self._all_positions}
        fresh = [p for p in new_records if (p.market, p.outcome_held, p.cost_basis) not in seen]
        if not fresh:
            return
        self._all_positions = fresh + self._all_positions
        self._header.setText(f"{self._label}  ({len(self._all_positions)})")
        for i, p in enumerate(fresh):
            self._table.insertRow(i)
            _populate_row(self._table, i, p)

    def append_positions(self, new_records: List[ResolvedPosition]) -> None:
        """Append a page of older positions (scroll-triggered load-more)."""
        self._loading = False
        if not new_records:
            self._has_more = False
            self._load_status.setText("All positions loaded")
            return

        # Deduplicate by (market, outcome_held, cost_basis) — same key as DB cache
        seen = {(p.market, p.outcome_held, p.cost_basis) for p in self._all_positions}
        fresh = [p for p in new_records if (p.market, p.outcome_held, p.cost_basis) not in seen]

        if not fresh:
            self._has_more = False
            self._load_status.setText("All positions loaded")
            return

        self._all_positions.extend(fresh)
        # Keep scrolling enabled as long as fresh rows arrived — partial cache pages
        # should not stop scroll; only an empty response ends it (handled above).
        self._has_more = True
        self._load_status.setText("")
        self._header.setText(f"{self._label}  ({len(self._all_positions)})")

        start_row = self._table.rowCount()
        self._table.setRowCount(start_row + len(fresh))
        for i, p in enumerate(fresh):
            _populate_row(self._table, start_row + i, p)

    def load_from_cache(self, positions: List[ResolvedPosition]) -> None:
        """Append cached rows not already in the table.

        Called after backfill completes so the table shows the full cached
        history without resetting scroll state or the infinite-scroll flag.
        Unlike append_positions, this does NOT modify _loading or _has_more.
        """
        seen  = {(p.market, p.outcome_held, p.cost_basis) for p in self._all_positions}
        fresh = [p for p in positions if (p.market, p.outcome_held, p.cost_basis) not in seen]
        if not fresh:
            return
        self._all_positions.extend(fresh)
        self._header.setText(f"{self._label}  ({len(self._all_positions)})")
        start_row = self._table.rowCount()
        self._table.setRowCount(start_row + len(fresh))
        for i, p in enumerate(fresh):
            _populate_row(self._table, start_row + i, p)

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
            self.load_more_requested.emit(len(self._all_positions))

    def _apply_filter(self, text: str) -> None:
        text = text.strip().lower()
        for row in range(self._table.rowCount()):
            visible = not text or any(
                text in (self._table.item(row, col).text().lower()
                         if self._table.item(row, col) else "")
                for col in range(self._table.columnCount())
            )
            self._table.setRowHidden(row, not visible)
