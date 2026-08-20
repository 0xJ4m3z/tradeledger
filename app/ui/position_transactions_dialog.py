"""Position transaction drilldown dialog.

Shows every BUY / SELL / REDEEM activity row that matches a market title.
Opened by double-clicking any closed position row in the Overview or the
Closed Positions tab.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models import UserActivity

# ── Palette ────────────────────────────────────────────────────────────────────
_BG     = "#0d1117"
_CARD   = "#161b22"
_MUTED  = "#8b949e"
_GREEN  = "#3fb950"
_RED    = "#f85149"
_BLUE   = "#58a6ff"
_BORDER = "#30363d"
_TEXT   = "#c9d1d9"

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:
    from datetime import timezone, timedelta as _td
    _ET = timezone(_td(hours=-5))

_Q_GREEN = QColor(_GREEN)
_Q_RED   = QColor(_RED)
_Q_MUTED = QColor(_MUTED)
_Q_TEXT  = QColor(_TEXT)
_Q_BLUE  = QColor(_BLUE)

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

_COLS  = ["Time (ET)", "Side", "Outcome", "Tokens", "Price", "USDC"]
_ALIGN = [
    Qt.AlignmentFlag.AlignLeft,
    Qt.AlignmentFlag.AlignLeft,
    Qt.AlignmentFlag.AlignLeft,
    Qt.AlignmentFlag.AlignRight,
    Qt.AlignmentFlag.AlignRight,
    Qt.AlignmentFlag.AlignRight,
]


def _cell(text: str, align=Qt.AlignmentFlag.AlignLeft) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
    return item


def _fmt_time(ts: int) -> str:
    try:
        return datetime.fromtimestamp(ts, tz=_ET).strftime("%m-%d %H:%M:%S")
    except Exception:
        return "—"


class _StatLabel(QWidget):
    """Compact stat card: label above, value below."""

    def __init__(self, title: str, value: str, color: str = _TEXT):
        super().__init__()
        self.setStyleSheet(
            f"QWidget {{ background-color: {_CARD}; border: 1px solid {_BORDER};"
            f" border-radius: 6px; padding: 8px 16px; }}"
        )
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(2)
        lbl = QLabel(title.upper())
        lbl.setStyleSheet(
            f"color: {_MUTED}; font-size: 10px; font-weight: 600;"
            " letter-spacing: 0.5px; background: none; border: none;"
        )
        val = QLabel(value)
        val.setStyleSheet(
            f"color: {color}; font-size: 16px; font-weight: 700;"
            " background: none; border: none;"
        )
        vbox.addWidget(lbl)
        vbox.addWidget(val)


class PositionTransactionsDialog(QDialog):
    """All BUY / SELL / REDEEM transactions for a single market window."""

    def __init__(
        self,
        market: str,
        activity: List[UserActivity],
        position=None,          # ResolvedPosition — for outcome_held / winning_outcome
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.setStyleSheet(_DIALOG_STYLE)
        self.setMinimumSize(820, 380)
        self.resize(960, 500)

        short = market if len(market) <= 60 else market[:57] + "…"
        self.setWindowTitle(f"Transactions — {short}")

        # All BUY / SELL trades + REDEEM events for this market, oldest first
        rows: List[UserActivity] = sorted(
            [a for a in activity
             if a.title == market and a.type in ("TRADE", "REDEEM")],
            key=lambda a: a.timestamp,
        )

        bought   = sum(a.usdc_size for a in rows if a.side == "BUY")
        received = sum(
            a.usdc_size for a in rows
            if a.side == "SELL" or a.type == "REDEEM"
        )
        net = received - bought

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Market title
        title_lbl = QLabel(market)
        title_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 13px; font-weight: 600; padding-bottom: 2px;"
        )
        title_lbl.setWordWrap(True)
        layout.addWidget(title_lbl)

        # Summary stats
        net_color = _GREEN if net > 0 else (_RED if net < 0 else _MUTED)
        net_text  = f"${net:,.2f}" if net >= 0 else f"-${abs(net):,.2f}"
        summary_row = QHBoxLayout()
        summary_row.setSpacing(10)
        summary_row.addWidget(_StatLabel("Total Invested",  f"${bought:,.2f}",   _MUTED))
        summary_row.addWidget(_StatLabel("Total Received",  f"${received:,.2f}", _MUTED))
        summary_row.addWidget(_StatLabel("Net",             net_text,            net_color))
        summary_row.addWidget(_StatLabel("Transactions",    str(len(rows)),      _TEXT))

        # Outcome held + winning outcome tiles (when position data is available)
        if position is not None:
            held   = getattr(position, "outcome_held",    None) or "—"
            won    = getattr(position, "winning_outcome", None) or "—"
            is_win = getattr(position, "is_win",          False)
            held_color = _GREEN if is_win else _RED
            summary_row.addWidget(_StatLabel("Outcome Held",    held, held_color))
            summary_row.addWidget(_StatLabel("Winning Outcome", won,  _TEXT))

        summary_row.addStretch(1)
        layout.addLayout(summary_row)

        # Transactions table
        tbl = QTableWidget(len(rows), len(_COLS))
        tbl.setHorizontalHeaderLabels(_COLS)
        tbl.setAlternatingRowColors(False)
        tbl.setShowGrid(False)
        tbl.verticalHeader().setVisible(False)
        tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        hdr = tbl.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # Time
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # Side
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)           # Outcome
        for col in range(3, len(_COLS)):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

        for r, a in enumerate(rows):
            # Normalise side display
            if a.type == "REDEEM":
                side_str   = "REDEEM"
                side_color = _Q_GREEN
            elif a.side == "BUY":
                side_str   = "BUY"
                side_color = _Q_BLUE
            elif a.side == "SELL":
                side_str   = "SELL"
                side_color = _Q_GREEN
            else:
                side_str   = a.side or "—"
                side_color = _Q_MUTED

            time_item = _cell(_fmt_time(a.timestamp), _ALIGN[0])
            time_item.setForeground(_Q_MUTED)

            side_item = _cell(side_str, _ALIGN[1])
            side_item.setForeground(side_color)

            usdc_item = _cell(f"${a.usdc_size:,.2f}", _ALIGN[5])
            usdc_item.setForeground(side_color)

            tbl.setItem(r, 0, time_item)
            tbl.setItem(r, 1, side_item)
            tbl.setItem(r, 2, _cell(a.outcome or "—",    _ALIGN[2]))
            tbl.setItem(r, 3, _cell(f"{a.size:,.2f}",   _ALIGN[3]))
            tbl.setItem(r, 4, _cell(f"${a.price:.4f}",  _ALIGN[4]))
            tbl.setItem(r, 5, usdc_item)

        layout.addWidget(tbl, 1)

        if not rows:
            no_data = QLabel("No transaction history found for this position.")
            no_data.setStyleSheet(f"color: {_MUTED}; font-style: italic; padding: 8px 0;")
            layout.addWidget(no_data)

        # Close button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)
