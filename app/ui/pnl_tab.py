"""Dedicated P/L tab: cumulative chart + daily P/L breakdown table with day drilldown."""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
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
from app.services.daily_pnl import build_daily_pnl_rows, get_positions_for_date
from app.services.date_range import DateRangeSelection, filter_closed_by_selection
from app.ui.date_range_control import DateRangeControl
from app.ui.pnl_chart import PnlChartWidget
from app.ui.polymarket_menu import attach_table_links

_BG     = "#0d1117"
_CARD   = "#161b22"
_MUTED  = "#8b949e"
_GREEN  = "#3fb950"
_RED    = "#f85149"
_BLUE   = "#58a6ff"
_BORDER = "#30363d"
_TEXT   = "#c9d1d9"
_ET     = ZoneInfo("America/New_York")

_BTN_ACTIVE = (
    f"background-color: #1f2937; border: 1px solid {_BLUE}; border-radius: 4px;"
    f" color: {_BLUE}; padding: 3px 14px; font-size: 12px; font-weight: 600;"
)
_BTN_IDLE = (
    f"background-color: #21262d; border: 1px solid {_BORDER}; border-radius: 4px;"
    f" color: {_MUTED}; padding: 3px 14px; font-size: 12px;"
)
_BTN_ACTION = (
    f"background-color: #21262d; border: 1px solid {_BORDER}; border-radius: 4px;"
    f" color: {_TEXT}; padding: 3px 14px; font-size: 12px;"
)
_BTN_ACTION_DISABLED = (
    f"background-color: #161b22; border: 1px solid {_BORDER}; border-radius: 4px;"
    f" color: {_MUTED}; padding: 3px 14px; font-size: 12px;"
)

_DAILY_COLS   = ["Date", "Realized P/L", "Closed Positions", "Wins", "Losses", "Cumulative P/L"]
_DETAIL_COLS  = ["Market", "Outcome", "Result", "Cost Basis", "Redeem / Sell Value",
                 "Realized P/L", "Closed Time"]

_STATUS_TEXT = {
    "REDEEMED_WIN":  "Win",
    "SOLD":          "Sold",
    "RESOLVED_LOSS": "Loss",
}

_Q_GREEN = QColor(_GREEN)
_Q_RED   = QColor(_RED)
_Q_MUTED = QColor(_MUTED)
_Q_TEXT  = QColor(_TEXT)


# ── Shared cell helpers ────────────────────────────────────────────────────────

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


def _fmt_close_time(p: ResolvedPosition) -> str:
    if p.closed_at:
        try:
            return datetime.fromtimestamp(p.closed_at, tz=_ET).strftime("%H:%M ET")
        except (OSError, OverflowError, ValueError):
            pass
    if p.resolved_date:
        return p.resolved_date[:10]
    return "—"


# ── Day detail dialog ──────────────────────────────────────────────────────────

_DIALOG_STYLE = f"""
QDialog, QWidget {{
    background-color: {_BG};
    color: {_TEXT};
    font-size: 13px;
}}
QTableWidget {{
    background-color: {_BG};
    alternate-background-color: {_BG};
    gridline-color: #21262d;
    color: {_TEXT};
    border: 1px solid {_BORDER};
    border-radius: 4px;
}}
QTableWidget QTableCornerButton::section {{
    background-color: {_CARD};
    border: none;
}}
QHeaderView::section {{
    background-color: {_CARD};
    color: {_MUTED};
    padding: 7px 12px;
    border: none;
    border-bottom: 1px solid {_BORDER};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.5px;
}}
QTableWidget::item {{
    padding: 6px 12px;
    border-bottom: 1px solid #21262d;
}}
QTableWidget::item:selected {{
    background-color: #1f2937;
    color: {_TEXT};
}}
QScrollBar:vertical {{
    background: {_BG};
    width: 8px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {_BORDER};
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QPushButton {{
    background-color: #21262d;
    border: 1px solid {_BORDER};
    border-radius: 4px;
    color: {_TEXT};
    padding: 6px 20px;
    font-size: 13px;
}}
QPushButton:hover {{ border-color: {_BLUE}; color: {_BLUE}; }}
"""


class _StatLabel(QFrame):
    """A small summary stat (label + value) for the dialog header."""

    def __init__(self, title: str, value: str, color: str = _TEXT):
        super().__init__()
        self.setStyleSheet(
            f"QFrame {{ background-color: {_CARD}; border: 1px solid {_BORDER};"
            f" border-radius: 6px; padding: 8px 16px; }}"
        )
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(2)

        lbl = QLabel(title.upper())
        lbl.setStyleSheet(f"color: {_MUTED}; font-size: 10px; font-weight: 600;"
                          " letter-spacing: 0.5px; border: none;")
        vbox.addWidget(lbl)

        val = QLabel(value)
        val.setStyleSheet(f"color: {color}; font-size: 16px; font-weight: 700; border: none;")
        vbox.addWidget(val)


class DayDetailDialog(QDialog):
    """Modal showing all closed positions for a single calendar day."""

    def __init__(
        self,
        target_date: date,
        positions: List[ResolvedPosition],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Closed Positions — {target_date.strftime('%Y-%m-%d')}")
        self.setMinimumSize(920, 500)
        self.resize(1060, 600)
        self.setStyleSheet(_DIALOG_STYLE)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        pnl   = sum(p.realized_pnl for p in positions)
        wins  = sum(1 for p in positions if p.realized_pnl > 0)
        losses = len(positions) - wins

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # ── Summary row ────────────────────────────────────────────────────────
        pnl_color = _GREEN if pnl > 0 else (_RED if pnl < 0 else _MUTED)
        pnl_text  = f"${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"

        summary_row = QHBoxLayout()
        summary_row.setSpacing(10)
        summary_row.addWidget(_StatLabel("Realized P/L",      pnl_text,           pnl_color))
        summary_row.addWidget(_StatLabel("Closed Positions",  str(len(positions)), _TEXT))
        summary_row.addWidget(_StatLabel("Wins",              str(wins),           _GREEN if wins  else _MUTED))
        summary_row.addWidget(_StatLabel("Losses",            str(losses),         _RED   if losses else _MUTED))
        summary_row.addStretch(1)
        layout.addLayout(summary_row)

        # ── Positions table ────────────────────────────────────────────────────
        self._table = QTableWidget(len(positions), len(_DETAIL_COLS))
        self._table.setHorizontalHeaderLabels(_DETAIL_COLS)
        self._table.setAlternatingRowColors(False)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        attach_table_links(self._table)

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(_DETAIL_COLS)):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

        for row, p in enumerate(positions):
            ct = getattr(p, "close_type", "UNKNOWN")
            result_text  = _STATUS_TEXT.get(ct, "—")
            result_color = _Q_GREEN if ct == "REDEEMED_WIN" else (
                           _Q_RED   if ct == "RESOLVED_LOSS" else _Q_MUTED)

            outcome_item = _cell(p.outcome_held)
            outcome_item.setForeground(_Q_GREEN if p.is_win else _Q_RED)

            result_item = _cell(result_text)
            result_item.setForeground(result_color)

            time_item = _cell(_fmt_close_time(p))
            time_item.setForeground(_Q_MUTED)

            mkt_item = _cell(p.market)
            if p.slug:
                mkt_item.setData(Qt.ItemDataRole.UserRole, p.slug)
                mkt_item.setToolTip("Ctrl+click or right-click to open on Polymarket")

            self._table.setItem(row, 0, mkt_item)
            self._table.setItem(row, 1, outcome_item)
            self._table.setItem(row, 2, result_item)
            self._table.setItem(row, 3, _cell(f"${p.cost_basis:,.2f}",   Qt.AlignmentFlag.AlignRight))
            self._table.setItem(row, 4, _cell(f"${p.redeem_value:,.2f}", Qt.AlignmentFlag.AlignRight))
            self._table.setItem(row, 5, _pnl_cell(p.realized_pnl))
            self._table.setItem(row, 6, time_item)

        layout.addWidget(self._table, 1)

        # ── Close button ───────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)


# ── Main P/L tab ───────────────────────────────────────────────────────────────

class PnlTab(QWidget):
    """Top-level P/L tab: range buttons, cumulative chart, daily breakdown table."""

    def __init__(self, closed_positions: List[ResolvedPosition] = None):
        super().__init__()
        self._closed: List[ResolvedPosition] = list(closed_positions or [])
        self._selection = DateRangeSelection.preset_range("1m")
        self._daily_rows: list = []   # mirrors table rows for drilldown

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        self._range_ctrl = DateRangeControl(default="1m", align="left")
        self._range_ctrl.range_changed.connect(self._on_range_changed)
        outer.addWidget(self._range_ctrl)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setStyleSheet("QSplitter::handle { background: #21262d; height: 4px; }")

        # ── Chart ──────────────────────────────────────────────────────────────
        chart_wrap = QWidget()
        chart_wrap.setStyleSheet(f"background-color: {_BG};")
        chart_layout = QVBoxLayout(chart_wrap)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        self._chart = PnlChartWidget([], self._closed, self._selection.preset or "1m", figsize=(10, 3.5))
        chart_layout.addWidget(self._chart)
        splitter.addWidget(chart_wrap)

        # ── Daily table ────────────────────────────────────────────────────────
        table_wrap = QWidget()
        table_layout = QVBoxLayout(table_wrap)
        table_layout.setContentsMargins(0, 8, 0, 0)
        table_layout.setSpacing(6)

        tbl_hdr_row = QHBoxLayout()
        tbl_label = QLabel("Daily P/L")
        tbl_label.setStyleSheet(f"color: {_TEXT}; font-size: 13px; font-weight: 600;")
        tbl_hdr_row.addWidget(tbl_label)
        tbl_hdr_row.addStretch()
        self._detail_btn = QPushButton("View Details")
        self._detail_btn.setFixedHeight(26)
        self._detail_btn.setEnabled(False)
        self._detail_btn.setStyleSheet(_BTN_ACTION_DISABLED)
        self._detail_btn.clicked.connect(self._open_selected_day)
        tbl_hdr_row.addWidget(self._detail_btn)
        table_layout.addLayout(tbl_hdr_row)

        self._table = QTableWidget(0, len(_DAILY_COLS))
        self._table.setHorizontalHeaderLabels(_DAILY_COLS)
        self._table.setAlternatingRowColors(False)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.resizeSection(0, 100)
        for col in range(1, len(_DAILY_COLS)):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

        self._table.doubleClicked.connect(lambda idx: self._open_day_detail(idx.row()))
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

        table_layout.addWidget(self._table)
        splitter.addWidget(table_wrap)

        splitter.setStretchFactor(0, 58)
        splitter.setStretchFactor(1, 42)
        splitter.setSizes([420, 300])

        outer.addWidget(splitter, 1)

        if self._closed:
            self._refresh()

    # ── Public API ─────────────────────────────────────────────────────────────

    def update_positions(self, closed_positions: List[ResolvedPosition]) -> None:
        """Called when new closed positions data is available (live fetch or backfill)."""
        self._closed = list(closed_positions)
        self._refresh()

    # ── Internal ───────────────────────────────────────────────────────────────

    def _on_range_changed(self, selection: DateRangeSelection) -> None:
        self._selection = selection
        self._refresh()

    def _refresh(self) -> None:
        """Update the chart and daily table for the current selection and data."""
        if self._selection.is_preset():
            range_str = self._selection.preset
            self._chart.update([], self._closed, range_str)
            self._daily_rows = build_daily_pnl_rows(self._closed, range_str)
        else:
            # Custom range: pre-filter, pass "all" so internals don't re-filter
            filtered = filter_closed_by_selection(self._closed, self._selection)
            self._chart.update([], filtered, "all")
            self._daily_rows = build_daily_pnl_rows(filtered, "all")
        self._populate_table(self._daily_rows)

    def _populate_table(self, rows: list) -> None:
        self._table.clearSelection()
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

    def _on_selection_changed(self) -> None:
        selected = bool(self._table.selectedItems())
        self._detail_btn.setEnabled(selected)
        self._detail_btn.setStyleSheet(_BTN_ACTION if selected else _BTN_ACTION_DISABLED)

    def _open_selected_day(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if rows:
            self._open_day_detail(rows[0].row())

    def _open_day_detail(self, row_index: int) -> None:
        if row_index < 0 or row_index >= len(self._daily_rows):
            return
        target_date = self._daily_rows[row_index]["date"]
        positions   = get_positions_for_date(self._closed, target_date)
        dlg = DayDetailDialog(target_date, positions, parent=self)
        dlg.exec()
