"""
Loss Watch tab — shows all active positions with negative unrealized P/L.

Acknowledged positions stay visible but are shown in muted colour so the user
can review them alongside new unacknowledged losses.  Clicking "Acknowledge All"
marks all current losers as known, updates the DB, and emits acknowledged_changed
so the Overview card syncs immediately.
"""

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

from app.database import load_loss_watch_acknowledged, save_loss_watch_acknowledged
from app.models import ActivePosition
from app.ui.polymarket_menu import attach_table_links

_GREEN = QColor("#3fb950")
_RED   = QColor("#f85149")
_MUTED = QColor("#8b949e")
_TEXT  = QColor("#c9d1d9")

COLUMNS = [
    "Market", "Outcome", "Qty", "Avg Cost",
    "Current Price", "Unrealized P/L", "P/L %", "Status",
]

_R = Qt.AlignmentFlag.AlignRight
_L = Qt.AlignmentFlag.AlignLeft
_V = Qt.AlignmentFlag.AlignVCenter


def _cell(text: str, align=_L) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    item.setTextAlignment(align | _V)
    return item


class LossWatchTab(QWidget):
    """Tab showing all active positions with negative unrealized P/L."""

    acknowledged_changed = Signal()   # emitted after DB write; overview card syncs

    def __init__(self):
        super().__init__()
        self._active: List[ActivePosition] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Header row: title + Acknowledge button
        hrow = QHBoxLayout()
        self._header = QLabel("Loss Watch  (no data yet)")
        self._header.setStyleSheet("color: #c9d1d9; font-size: 14px; font-weight: 600;")
        self._ack_btn = QPushButton("Acknowledge All")
        self._ack_btn.setStyleSheet(
            "background-color: #21262d; border: 1px solid #30363d; border-radius: 4px;"
            " color: #8b949e; padding: 4px 14px; font-size: 12px;"
        )
        self._ack_btn.setEnabled(False)
        self._ack_btn.clicked.connect(self._on_acknowledge)
        hrow.addWidget(self._header)
        hrow.addStretch()
        hrow.addWidget(self._ack_btn)
        layout.addLayout(hrow)

        sub = QLabel(
            "Active positions with negative unrealized P/L, sorted worst-first.  "
            "Acknowledged positions are kept for review (shown muted)."
        )
        sub.setStyleSheet("color: #8b949e; font-size: 12px;")
        layout.addWidget(sub)

        search = QLineEdit()
        search.setPlaceholderText("Filter by market or outcome…")
        search.setMaximumWidth(400)
        layout.addWidget(search)

        self._table = QTableWidget(0, len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(False)

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(COLUMNS)):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

        attach_table_links(self._table)
        search.textChanged.connect(self._apply_filter)
        layout.addWidget(self._table)

    # ── Public API ─────────────────────────────────────────────────────────────

    def update_positions(self, active: List[ActivePosition]) -> None:
        """Called by main_window whenever live positions are refreshed."""
        self._active = list(active)
        self._refresh()

    # ── Internal ───────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        acknowledged_set = set(load_loss_watch_acknowledged())
        losers = sorted(
            (p for p in self._active if p.unrealized_pnl < 0),
            key=lambda p: p.unrealized_pnl,  # worst first
        )
        new_count = sum(1 for p in losers if p.market not in acknowledged_set)
        ack_count = len(losers) - new_count

        # Header text
        if not losers:
            self._header.setText("Loss Watch  (no losing positions)")
        else:
            parts = []
            if new_count:
                parts.append(f"{new_count} new")
            if ack_count:
                parts.append(f"{ack_count} acknowledged")
            self._header.setText(f"Loss Watch  ({',  '.join(parts)})")

        self._ack_btn.setEnabled(new_count > 0)

        self._table.setRowCount(len(losers))
        for row, p in enumerate(losers):
            is_ack   = p.market in acknowledged_set
            colour   = _MUTED if is_ack else _RED
            status   = "Acknowledged" if is_ack else "New"

            row_data = [
                (p.market,                          _L),
                (p.outcome,                         _L),
                (f"{p.quantity:,.0f}",              _R),
                (f"${p.avg_cost:.4f}",              _R),
                (f"${p.current_price:.4f}",         _R),
                (f"${p.unrealized_pnl:,.2f}",       _R),
                (f"{p.unrealized_pnl_pct:+.1f}%",   _R),
                (status,                            _L),
            ]
            for col, (text, align) in enumerate(row_data):
                item = _cell(text, align)
                item.setForeground(colour)
                self._table.setItem(row, col, item)

            # Store slug on market cell for right-click Polymarket link
            slug = getattr(p, "slug", None)
            if slug:
                mkt = self._table.item(row, 0)
                if mkt:
                    mkt.setData(Qt.ItemDataRole.UserRole, slug)
                    mkt.setToolTip("Right-click to open on Polymarket")

    def _on_acknowledge(self) -> None:
        losing_markets = [p.market for p in self._active if p.unrealized_pnl < 0]
        save_loss_watch_acknowledged(losing_markets)
        self.acknowledged_changed.emit()
        self._refresh()

    def _apply_filter(self, text: str) -> None:
        text = text.strip().lower()
        for row in range(self._table.rowCount()):
            visible = not text or any(
                text in (self._table.item(row, col).text().lower()
                         if self._table.item(row, col) else "")
                for col in range(self._table.columnCount())
            )
            self._table.setRowHidden(row, not visible)
