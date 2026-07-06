from datetime import datetime
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
from app.models import ResolvedPosition
from app.services.daily_pnl import sort_closed_positions_newest_first
from app.ui.polymarket_menu import attach_table_links

try:
    from zoneinfo import ZoneInfo as _ZoneInfo
    _ET_ZONE = _ZoneInfo("America/New_York")
except Exception:
    from datetime import timezone, timedelta as _td
    _ET_ZONE = timezone(_td(hours=-5))

COLUMNS = [
    "Market", "Outcome Held", "Winning Outcome", "Qty",
    "Cost Basis", "Proceeds", "Realized P/L", "P/L %", "Status", "Closed Date",
]

_GREEN  = QColor("#3fb950")
_RED    = QColor("#f85149")
_MUTED  = QColor("#8b949e")
_YELLOW = QColor("#e3b341")

_SCROLL_THRESHOLD_PX = 80

_STATUS_TEXT = {
    "REDEEMED_WIN":  "Win",
    "SOLD":          "Sold",
    "RESOLVED_LOSS": "Loss",
}
_STATUS_COLOR = {
    "REDEEMED_WIN":  _GREEN,
    "SOLD":          _YELLOW,
    "RESOLVED_LOSS": _RED,
}


def _fmt_closed_date(p: ResolvedPosition) -> str:
    """Return close date in ET (from closed_at epoch), falling back to resolved_date."""
    if p.closed_at:
        try:
            return datetime.fromtimestamp(p.closed_at, tz=_ET_ZONE).strftime("%Y-%m-%d")
        except (OSError, OverflowError, ValueError):
            pass
    if p.resolved_date:
        return p.resolved_date[:10]
    return "—"


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

    mkt_item = _cell(p.market)
    if p.slug:
        mkt_item.setData(Qt.ItemDataRole.UserRole, p.slug)
        mkt_item.setToolTip("Ctrl+click or right-click to open on Polymarket")
    table.setItem(row, 0, mkt_item)
    table.setItem(row, 1, outcome_item)
    table.setItem(row, 2, _cell(p.winning_outcome))
    table.setItem(row, 3, _cell(f"{p.quantity:,.0f}",       Qt.AlignmentFlag.AlignRight))
    table.setItem(row, 4, _cell(f"${p.cost_basis:,.2f}",    Qt.AlignmentFlag.AlignRight))
    table.setItem(row, 5, _cell(f"${p.redeem_value:,.2f}",  Qt.AlignmentFlag.AlignRight))
    table.setItem(row, 6, _pnl_cell(p.realized_pnl))
    table.setItem(row, 7, _pnl_cell(p.realized_pnl_pct, "{:+.1f}%"))

    ct = getattr(p, "close_type", "UNKNOWN")
    status_item = _cell(_STATUS_TEXT.get(ct, "—"))
    status_item.setForeground(_STATUS_COLOR.get(ct, _MUTED))
    table.setItem(row, 8, status_item)

    date_item = _cell(_fmt_closed_date(p))
    date_item.setForeground(_MUTED)
    table.setItem(row, 9, date_item)


class ResolvedPositionsTable(QWidget):
    refresh_requested   = Signal()
    load_more_requested = Signal(int)  # emits current row count as next offset

    def __init__(
        self,
        positions: List[ResolvedPosition],
        label: str = "Resolved Positions",
        show_refresh: bool = False,
    ):
        super().__init__()
        self._label           = label
        self._all_positions   = list(positions)   # complete in-memory dataset
        self._displayed_count = len(positions)    # render ALL rows at startup — no cap
        self._has_more        = True
        self._loading         = False
        self._infinite_scroll = show_refresh  # only Closed Positions tab uses API scroll-load

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
        hdr.setSectionResizeMode(9, QHeaderView.ResizeMode.Fixed)
        hdr.resizeSection(9, 90)

        attach_table_links(self._table)
        self._table.verticalScrollBar().valueChanged.connect(self._on_scroll)

        search.textChanged.connect(self._apply_filter)
        layout.addWidget(self._table)

    def _rebuild_table(self) -> None:
        """Sort _all_positions newest-first and re-render the table widget."""
        self._all_positions = sort_closed_positions_newest_first(self._all_positions)
        n = len(self._all_positions)
        self._table.setRowCount(n)
        for row, p in enumerate(self._all_positions):
            _populate_row(self._table, row, p)
        self._displayed_count = n
        self._header.setText(f"{self._label}  ({n})")

    def update_positions(self, positions: List[ResolvedPosition]) -> None:
        """Replace all positions (called on initial/refresh fetch)."""
        old_all = len(self._all_positions)
        self._all_positions   = list(positions)
        self._has_more        = len(positions) >= 100
        self._loading         = False
        self._load_status.setText("")
        self._rebuild_table()
        _dlog("closed_tab",
              "update_positions(REPLACE): incoming=%d  old_all=%d  new_all=%d  displayed=%d",
              len(positions), old_all, len(self._all_positions), self._displayed_count)

    def merge_positions(self, new_records: List[ResolvedPosition]) -> None:
        """Merge new records into the table, re-sorting newest-first (called on refresh)."""
        old_all = len(self._all_positions)
        seen  = {(p.market, p.outcome_held) for p in self._all_positions}
        fresh = [p for p in new_records if (p.market, p.outcome_held) not in seen]
        if not fresh:
            _dlog("closed_tab",
                  "merge_positions: incoming=%d  0 new  all=%d  displayed=%d",
                  len(new_records), old_all, self._displayed_count)
            return
        self._all_positions = fresh + self._all_positions
        self._rebuild_table()
        _dlog("closed_tab",
              "merge_positions: incoming=%d  +%d new  all=%d→%d  displayed=%d",
              len(new_records), len(fresh), old_all, len(self._all_positions), self._displayed_count)

    def append_positions(self, new_records: List[ResolvedPosition]) -> None:
        """Append a page of older positions (scroll-triggered load-more from API/DB)."""
        old_all = len(self._all_positions)
        self._loading = False
        if not new_records:
            self._has_more = False
            self._load_status.setText("All positions loaded")
            _dlog("closed_tab", "append_positions: empty page — done, all=%d", old_all)
            return

        seen = {(p.market, p.outcome_held, p.cost_basis) for p in self._all_positions}
        fresh = [p for p in new_records if (p.market, p.outcome_held, p.cost_basis) not in seen]

        if not fresh:
            self._has_more = False
            self._load_status.setText("All positions loaded")
            _dlog("closed_tab",
                  "append_positions: %d incoming all dupes — done, all=%d", len(new_records), old_all)
            return

        self._all_positions.extend(fresh)
        self._has_more = True
        self._load_status.setText("")
        self._rebuild_table()
        _dlog("closed_tab",
              "append_positions: incoming=%d  +%d new  all=%d→%d  displayed=%d",
              len(new_records), len(fresh), old_all, len(self._all_positions), self._displayed_count)

    def load_from_cache(self, positions: List[ResolvedPosition]) -> None:
        """Extend the dataset with newly cached rows from backfill and render them.

        Does NOT modify _loading or _has_more so infinite-scroll stays functional.
        Re-sorts and re-renders the full table so newly-discovered rows appear
        in the correct newest-first position.
        """
        old_all = len(self._all_positions)
        seen  = {(p.market, p.outcome_held, p.cost_basis) for p in self._all_positions}
        fresh = [p for p in positions if (p.market, p.outcome_held, p.cost_basis) not in seen]
        if not fresh:
            _dlog("closed_tab",
                  "load_from_cache: %d incoming all dupes — all=%d  displayed=%d",
                  len(positions), old_all, self._displayed_count)
            return
        self._all_positions.extend(fresh)
        self._rebuild_table()
        _dlog("closed_tab",
              "load_from_cache: incoming=%d  +%d new  all=%d→%d  displayed=%d",
              len(positions), len(fresh), old_all, len(self._all_positions), self._displayed_count)

    def _on_scroll(self, value: int) -> None:
        sb = self._table.verticalScrollBar()
        if sb.maximum() <= 0 or value < sb.maximum() - _SCROLL_THRESHOLD_PX:
            return
        if self._loading:
            return
        # Extend the table from in-memory _all_positions before requesting from API/DB
        if self._displayed_count < len(self._all_positions):
            start = self._displayed_count
            end   = min(start + 100, len(self._all_positions))
            current_rows = self._table.rowCount()
            self._table.setRowCount(current_rows + (end - start))
            for i, p in enumerate(self._all_positions[start:end]):
                _populate_row(self._table, current_rows + i, p)
            self._displayed_count = end
            _dlog("closed_tab",
                  "_on_scroll: rendered in-memory rows %d→%d  (total in-memory=%d)",
                  start, end, len(self._all_positions))
            return
        # In-memory exhausted — request older data from API/DB
        if self._has_more and self._infinite_scroll:
            self._loading = True
            self._load_status.setText("Loading…")
            _dlog("closed_tab",
                  "_on_scroll: in-memory exhausted at %d rows — requesting API offset=%d",
                  self._displayed_count, len(self._all_positions))
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
