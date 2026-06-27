from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.models import ActivePosition, ResolvedPosition
from app.ui.pnl_chart import PnlChartWidget

# ── Palette ────────────────────────────────────────────────────────────────────
_GREEN  = "#3fb950"
_RED    = "#f85149"
_MUTED  = "#8b949e"
_TEXT   = "#c9d1d9"
_BLUE   = "#58a6ff"
_BG     = "#0d1117"
_CARD   = "#161b22"
_BORDER = "#30363d"
_ROWLINE = "#21262d"

# ── Reusable style fragments ───────────────────────────────────────────────────
_CARD_FRAME_S = (
    f"QFrame {{ background-color: {_CARD}; border: 1px solid {_BORDER}; border-radius: 6px; }}"
)
_METRIC_TITLE_S = f"color: {_MUTED}; font-size: 11px; font-weight: 600; letter-spacing: 0.8px;"
_SECTION_HDR_S  = f"color: {_TEXT}; font-size: 14px; font-weight: 600;"

_COL_HDR_S = (
    f"color: {_MUTED}; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; "
    f"padding: 7px 12px; background-color: {_CARD}; border-bottom: 1px solid {_BORDER};"
)

_L = Qt.AlignmentFlag.AlignLeft
_R = Qt.AlignmentFlag.AlignRight
_V = Qt.AlignmentFlag.AlignVCenter


# ── Metric cards ───────────────────────────────────────────────────────────────

def _pnl_color(val: float) -> str:
    return _GREEN if val > 0 else (_RED if val < 0 else _TEXT)


def _card(title: str, value: str, color: str) -> QFrame:
    frame = QFrame()
    frame.setStyleSheet(_CARD_FRAME_S)
    vbox = QVBoxLayout(frame)
    vbox.setContentsMargins(14, 12, 14, 14)
    vbox.setSpacing(6)
    t = QLabel(title.upper())
    t.setStyleSheet(_METRIC_TITLE_S)
    v = QLabel(value)
    v.setStyleSheet(f"color: {color}; font-size: 20px; font-weight: 700;")
    v.setAlignment(_L)
    vbox.addWidget(t)
    vbox.addWidget(v)
    return frame


def _cards_panel(m: dict) -> QWidget:
    panel = QWidget()
    vbox = QVBoxLayout(panel)
    vbox.setContentsMargins(0, 0, 0, 0)
    vbox.setSpacing(10)

    row1 = QHBoxLayout()
    row1.setSpacing(10)
    row1.addWidget(_card("Active Positions Value", f"${m['active_positions_value']:,.2f}", _BLUE))
    row1.addWidget(_card("Realized P/L",           f"${m['realized_pnl']:,.2f}",           _pnl_color(m["realized_pnl"])))

    row2 = QHBoxLayout()
    row2.setSpacing(10)
    row2.addWidget(_card("Win Count",      str(m["win_count"]),               _GREEN))
    row2.addWidget(_card("Loss Count",     str(m["loss_count"]),              _RED))
    row2.addWidget(_card("Unrealized P/L", f"${m['unrealized_pnl']:,.2f}",   _pnl_color(m["unrealized_pnl"])))

    vbox.addLayout(row1)
    vbox.addLayout(row2)
    return panel


# ── Grid-based flat table (no scroll container) ────────────────────────────────

def _col_hdr(text: str, align=_L) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(_COL_HDR_S)
    lbl.setAlignment(align | _V)
    return lbl


def _row_cell(text: str, align=_L, color: str = _TEXT) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"padding: 6px 12px; background-color: {_BG}; "
        f"border-bottom: 1px solid {_ROWLINE}; color: {color};"
    )
    lbl.setAlignment(align | _V)
    return lbl


def _divider() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"background-color: {_ROWLINE}; border: none; max-height: 1px;")
    return f


# ── Active positions section ───────────────────────────────────────────────────

_ACT_HDRS = ["Market", "Outcome", "Quantity", "Avg Cost", "Current Price", "Current Value", "Unrealized P/L", "P/L %"]
_ACT_ALIGN = [_L, _L, _R, _R, _R, _R, _R, _R]


def _active_section(positions: List[ActivePosition]) -> QWidget:
    outer = QWidget()
    vbox = QVBoxLayout(outer)
    vbox.setContentsMargins(0, 0, 0, 0)
    vbox.setSpacing(8)

    lbl = QLabel(f"Active Positions  ({len(positions)})")
    lbl.setStyleSheet(_SECTION_HDR_S)
    vbox.addWidget(lbl)

    # Plain QFrame — QGridLayout of QLabels, not a scroll area
    frame = QFrame()
    frame.setStyleSheet(f"QFrame {{ background-color: {_BG}; border: 1px solid {_BORDER}; }}")
    grid = QGridLayout(frame)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(0)

    for col, (h, a) in enumerate(zip(_ACT_HDRS, _ACT_ALIGN)):
        grid.addWidget(_col_hdr(h, a), 0, col)

    for r, p in enumerate(positions, start=1):
        pc = _pnl_color(p.unrealized_pnl)
        cells = [
            (p.market,                        _L, _TEXT),
            (p.outcome,                       _L, _TEXT),
            (f"{p.quantity:,.0f}",            _R, _TEXT),
            (f"${p.avg_cost:.4f}",            _R, _TEXT),
            (f"${p.current_price:.4f}",       _R, _TEXT),
            (f"${p.current_value:,.2f}",      _R, _TEXT),
            (f"${p.unrealized_pnl:,.2f}",     _R, pc),
            (f"{p.unrealized_pnl_pct:+.1f}%", _R, pc),
        ]
        for col, (text, align, color) in enumerate(cells):
            grid.addWidget(_row_cell(text, align, color), r, col)

    grid.setColumnStretch(0, 1)
    vbox.addWidget(frame)
    return outer


# ── Resolved positions section ─────────────────────────────────────────────────

_RES_HDRS  = ["Market", "Outcome Held", "Winning Outcome", "Qty", "Cost Basis", "Redeem Value", "Realized P/L", "P/L %", "Redeemed"]
_RES_ALIGN = [_L, _L, _L, _R, _R, _R, _R, _R, _L]


def _resolved_section(positions: List[ResolvedPosition]) -> QWidget:
    outer = QWidget()
    vbox = QVBoxLayout(outer)
    vbox.setContentsMargins(0, 0, 0, 0)
    vbox.setSpacing(8)

    lbl = QLabel(f"Resolved Positions  ({len(positions)})")
    lbl.setStyleSheet(_SECTION_HDR_S)
    vbox.addWidget(lbl)

    frame = QFrame()
    frame.setStyleSheet(f"QFrame {{ background-color: {_BG}; border: 1px solid {_BORDER}; }}")
    grid = QGridLayout(frame)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(0)

    for col, (h, a) in enumerate(zip(_RES_HDRS, _RES_ALIGN)):
        grid.addWidget(_col_hdr(h, a), 0, col)

    for r, p in enumerate(positions, start=1):
        pc = _pnl_color(p.realized_pnl)
        oc = _GREEN if p.is_win else _RED
        sc = _GREEN if p.redeemed else _MUTED
        cells = [
            (p.market,                          _L, _TEXT),
            (p.outcome_held,                    _L, oc),
            (p.winning_outcome,                 _L, _TEXT),
            (f"{p.quantity:,.0f}",              _R, _TEXT),
            (f"${p.cost_basis:,.2f}",           _R, _TEXT),
            (f"${p.redeem_value:,.2f}",         _R, _TEXT),
            (f"${p.realized_pnl:,.2f}",         _R, pc),
            (f"{p.realized_pnl_pct:+.1f}%",    _R, pc),
            ("Yes" if p.redeemed else "Pending", _L, sc),
        ]
        for col, (text, align, color) in enumerate(cells):
            grid.addWidget(_row_cell(text, align, color), r, col)

    grid.setColumnStretch(0, 1)
    vbox.addWidget(frame)
    return outer


# ── Overview widget ────────────────────────────────────────────────────────────

class OverviewWidget(QWidget):
    def __init__(
        self,
        active: List[ActivePosition],
        resolved: List[ResolvedPosition],
        metrics: dict,
    ):
        super().__init__()

        # One scroll area owns the entire page
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        main = QVBoxLayout(content)
        main.setContentsMargins(16, 16, 16, 20)
        main.setSpacing(0)

        # ── Top: metric cards (left) + P/L chart (right) ──────────
        top = QWidget()
        top.setMinimumHeight(280)
        top_row = QHBoxLayout(top)
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(14)
        top_row.addWidget(_cards_panel(metrics), 42)
        top_row.addWidget(PnlChartWidget(resolved), 58)
        main.addWidget(top)

        main.addSpacing(20)
        main.addWidget(_divider())
        main.addSpacing(16)

        # ── Active positions — labels in a grid, no scroll box ─────
        main.addWidget(_active_section(active))

        main.addSpacing(20)
        main.addWidget(_divider())
        main.addSpacing(16)

        # ── Resolved positions — same approach ─────────────────────
        main.addWidget(_resolved_section(resolved))

        # Push everything up if the window is taller than the content
        main.addStretch(1)

        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
