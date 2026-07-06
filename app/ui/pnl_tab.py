"""Dedicated P/L tab: cumulative chart + daily P/L breakdown table."""
from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models import ResolvedPosition
from app.services.daily_pnl import build_daily_pnl_rows
from app.ui.pnl_chart import PnlChartWidget

_BG     = "#0d1117"
_MUTED  = "#8b949e"
_GREEN  = "#3fb950"
_RED    = "#f85149"
_BLUE   = "#58a6ff"
_BORDER = "#30363d"
_TEXT   = "#c9d1d9"

_RANGE_LABELS = {
    "1d":  "1D",
    "1w":  "1W",
    "1m":  "1M",
    "1y":  "1Y",
    "ytd": "YTD",
    "all": "All",
}

_BTN_ACTIVE = (
    f"background-color: #1f2937; border: 1px solid {_BLUE}; border-radius: 4px;"
    f" color: {_BLUE}; padding: 3px 14px; font-size: 12px; font-weight: 600;"
)
_BTN_IDLE = (
    f"background-color: #21262d; border: 1px solid {_BORDER}; border-radius: 4px;"
    f" color: {_MUTED}; padding: 3px 14px; font-size: 12px;"
)

_TABLE_COLS = ["Date", "Realized P/L", "Closed Positions", "Wins", "Losses", "Cumulative P/L"]

_Q_GREEN = QColor(_GREEN)
_Q_RED   = QColor(_RED)
_Q_MUTED = QColor(_MUTED)


def _cell(text: str, align=Qt.AlignmentFlag.AlignLeft) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
    return item


def _pnl_cell(val: float) -> QTableWidgetItem:
    text = f"${val:,.2f}" if val >= 0 else f"-${abs(val):,.2f}"
    item = _cell(text, Qt.AlignmentFlag.AlignRight)
    item.setForeground(_Q_GREEN if val > 0 else (_Q_RED if val < 0 else _Q_MUTED))
    return item


class PnlTab(QWidget):
    """Top-level P/L tab: range buttons, cumulative chart, daily breakdown table."""

    def __init__(self, closed_positions: List[ResolvedPosition] = None):
        super().__init__()
        self._closed: List[ResolvedPosition] = list(closed_positions or [])
        self._range = "1m"  # default

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        outer.addWidget(self._build_range_bar())

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setStyleSheet("QSplitter::handle { background: #21262d; height: 4px; }")

        # ── Chart ──────────────────────────────────────────────────────────────
        chart_wrap = QWidget()
        chart_wrap.setStyleSheet(f"background-color: {_BG};")
        chart_layout = QVBoxLayout(chart_wrap)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        self._chart = PnlChartWidget([], self._closed, self._range, figsize=(10, 3.5))
        chart_layout.addWidget(self._chart)
        splitter.addWidget(chart_wrap)

        # ── Daily table ────────────────────────────────────────────────────────
        table_wrap = QWidget()
        table_layout = QVBoxLayout(table_wrap)
        table_layout.setContentsMargins(0, 8, 0, 0)
        table_layout.setSpacing(6)

        tbl_header = QLabel("Daily P/L")
        tbl_header.setStyleSheet(
            f"color: {_TEXT}; font-size: 13px; font-weight: 600;"
        )
        table_layout.addWidget(tbl_header)

        self._table = QTableWidget(0, len(_TABLE_COLS))
        self._table.setHorizontalHeaderLabels(_TABLE_COLS)
        self._table.setAlternatingRowColors(False)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.resizeSection(0, 100)
        for col in range(1, len(_TABLE_COLS)):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

        table_layout.addWidget(self._table)
        splitter.addWidget(table_wrap)

        splitter.setStretchFactor(0, 58)
        splitter.setStretchFactor(1, 42)
        splitter.setSizes([420, 300])

        outer.addWidget(splitter, 1)

        # Render initial data if provided
        if self._closed:
            self._refresh()

    # ── Public API ─────────────────────────────────────────────────────────────

    def update_positions(self, closed_positions: List[ResolvedPosition]) -> None:
        """Called when new closed positions data is available (live fetch or backfill)."""
        self._closed = list(closed_positions)
        self._refresh()

    # ── Internal ───────────────────────────────────────────────────────────────

    def _build_range_bar(self) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self._range_btns: dict[str, QPushButton] = {}
        for key, label in _RANGE_LABELS.items():
            btn = QPushButton(label)
            btn.setFixedHeight(26)
            btn.setCheckable(False)
            btn.setStyleSheet(_BTN_ACTIVE if key == self._range else _BTN_IDLE)
            btn.clicked.connect(lambda _checked, k=key: self._on_range_changed(k))
            self._range_btns[key] = btn
            row.addWidget(btn)
        row.addStretch(1)
        return bar

    def _on_range_changed(self, range_: str) -> None:
        self._range = range_
        for key, btn in self._range_btns.items():
            btn.setStyleSheet(_BTN_ACTIVE if key == range_ else _BTN_IDLE)
        self._refresh()

    def _refresh(self) -> None:
        """Update the chart and daily table for the current range and data."""
        self._chart.update([], self._closed, self._range)
        self._populate_table(build_daily_pnl_rows(self._closed, self._range))

    def _populate_table(self, rows: list) -> None:
        self._table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            date_str = row["date"].strftime("%Y-%m-%d")
            self._table.setItem(r, 0, _cell(date_str, Qt.AlignmentFlag.AlignLeft))
            self._table.setItem(r, 1, _pnl_cell(row["pnl"]))
            count_item = _cell(str(row["count"]), Qt.AlignmentFlag.AlignRight)
            count_item.setForeground(_Q_MUTED)
            self._table.setItem(r, 2, count_item)
            win_item = _cell(str(row["wins"]), Qt.AlignmentFlag.AlignRight)
            win_item.setForeground(_Q_GREEN if row["wins"] else _Q_MUTED)
            self._table.setItem(r, 3, win_item)
            loss_item = _cell(str(row["losses"]), Qt.AlignmentFlag.AlignRight)
            loss_item.setForeground(_Q_RED if row["losses"] else _Q_MUTED)
            self._table.setItem(r, 4, loss_item)
            self._table.setItem(r, 5, _pnl_cell(row["cumulative"]))
