from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.database import load_wallet_snapshots, save_wallet_snapshot
from app.models import ActivePosition, ResolvedPosition
from app.services.metrics import compute_dashboard_metrics, compute_total_tracked_value
from app.ui.total_value_chart import TotalValueChartWidget
from app.ui.wallet_panel import WalletPanel

# ── Palette ────────────────────────────────────────────────────────────────────
_GREEN   = "#3fb950"
_RED     = "#f85149"
_MUTED   = "#8b949e"
_TEXT    = "#c9d1d9"
_BLUE    = "#58a6ff"
_BG      = "#0d1117"
_CARD    = "#161b22"
_BORDER  = "#30363d"
_ROWLINE = "#21262d"

_CARD_FRAME_S  = f"QFrame {{ background-color: {_CARD}; border: 1px solid {_BORDER}; border-radius: 6px; }}"
_METRIC_TITLE_S = f"color: {_MUTED}; font-size: 11px; font-weight: 600; letter-spacing: 0.8px;"
_SECTION_HDR_S  = f"color: {_TEXT}; font-size: 14px; font-weight: 600;"
_COL_HDR_S = (
    f"color: {_MUTED}; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; "
    f"padding: 7px 12px; background-color: {_CARD}; border-bottom: 1px solid {_BORDER};"
)

_L = Qt.AlignmentFlag.AlignLeft
_R = Qt.AlignmentFlag.AlignRight
_V = Qt.AlignmentFlag.AlignVCenter


# ── Updatable metric card ──────────────────────────────────────────────────────

class _MetricCard(QFrame):
    def __init__(self, title: str, value: str, color: str):
        super().__init__()
        self.setStyleSheet(_CARD_FRAME_S)
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(14, 12, 14, 14)
        vbox.setSpacing(6)
        t = QLabel(title.upper())
        t.setStyleSheet(_METRIC_TITLE_S)
        self._val = QLabel(value)
        self._val.setStyleSheet(f"color: {color}; font-size: 20px; font-weight: 700;")
        self._val.setAlignment(_L | _V)
        vbox.addWidget(t)
        vbox.addWidget(self._val)

    def update_value(self, value: str, color: str) -> None:
        self._val.setText(value)
        self._val.setStyleSheet(f"color: {color}; font-size: 20px; font-weight: 700;")


# ── Grid-based flat table (no internal scroll) ─────────────────────────────────

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


def _pnl_color(val: float) -> str:
    return _GREEN if val > 0 else (_RED if val < 0 else _TEXT)


# ── Active positions section ───────────────────────────────────────────────────

_ACT_HDRS  = ["Market", "Outcome", "Quantity", "Avg Cost", "Current Price", "Current Value", "Unrealized P/L", "P/L %"]
_ACT_ALIGN = [_L, _L, _R, _R, _R, _R, _R, _R]


def _active_section(positions: List[ActivePosition]) -> QWidget:
    outer = QWidget()
    vbox = QVBoxLayout(outer)
    vbox.setContentsMargins(0, 0, 0, 0)
    vbox.setSpacing(8)

    lbl = QLabel(f"Active Positions  ({len(positions)})")
    lbl.setStyleSheet(_SECTION_HDR_S)
    vbox.addWidget(lbl)

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
    positions_changed = Signal(list, list, list)   # (active, redeemable, closed) — for main_window tabs
    snapshots_changed = Signal(list)               # updated snapshot list — for the full-size tab chart

    def __init__(
        self,
        active: List[ActivePosition],
        resolved: List[ResolvedPosition],
        metrics: dict,
    ):
        super().__init__()

        self._active_value    = metrics["active_positions_value"]
        self._unrealized_pnl  = metrics["unrealized_pnl"]
        self._realized_pnl    = metrics["realized_pnl"]
        self._wallet_usd_value = 0.0

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        main = QVBoxLayout(content)
        main.setContentsMargins(16, 16, 16, 20)
        main.setSpacing(0)
        self._content_layout = main   # stored for dynamic section replacement

        # ── Wallet panel ───────────────────────────────────────────────
        self._wallet_panel = WalletPanel()
        self._wallet_panel.wallet_value_changed.connect(self._on_wallet_value_changed)
        self._wallet_panel.positions_fetched.connect(self._on_positions_fetched)
        main.addWidget(self._wallet_panel)

        main.addSpacing(14)

        # ── Cards (left) + Total Tracked Value chart (right) ──────────
        top = QWidget()
        top.setMinimumHeight(280)
        top_row = QHBoxLayout(top)
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(14)

        cards_panel = self._build_cards_panel(metrics)
        top_row.addWidget(cards_panel, 42)

        snapshots = load_wallet_snapshots()
        self._chart = TotalValueChartWidget(snapshots)
        top_row.addWidget(self._chart, 58)

        main.addWidget(top)
        main.addSpacing(20)
        main.addWidget(_divider())
        main.addSpacing(16)

        # ── Active positions ───────────────────────────────────────────
        self._act_section = _active_section(active)
        main.addWidget(self._act_section)
        main.addSpacing(20)
        main.addWidget(_divider())
        main.addSpacing(16)

        # ── Resolved positions ─────────────────────────────────────────
        self._res_section = _resolved_section(resolved)
        main.addWidget(self._res_section)
        main.addStretch(1)

        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ── Card panel ─────────────────────────────────────────────────────────────

    def _build_cards_panel(self, m: dict) -> QWidget:
        panel = QWidget()
        vbox = QVBoxLayout(panel)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(10)

        self._total_card  = _MetricCard("Total Tracked Value",    f"${m['total_tracked_value']:,.2f}", _BLUE)
        self._active_card = _MetricCard("Active Positions Value",  f"${m['active_positions_value']:,.2f}", _BLUE)
        self._wallet_card = _MetricCard("Wallet USD Value",        "$0.00", _MUTED)
        self._unreal_card = _MetricCard("Unrealized P/L",          f"${m['unrealized_pnl']:,.2f}", _pnl_color(m["unrealized_pnl"]))
        self._win_card    = _MetricCard("Win Count",                str(m["win_count"]), _GREEN)
        self._loss_card   = _MetricCard("Loss Count",               str(m["loss_count"]), _RED)

        row1 = QHBoxLayout()
        row1.setSpacing(10)
        row1.addWidget(self._total_card)
        row1.addWidget(self._active_card)
        row1.addWidget(self._wallet_card)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        row2.addWidget(self._unreal_card)
        row2.addWidget(self._win_card)
        row2.addWidget(self._loss_card)

        vbox.addLayout(row1)
        vbox.addLayout(row2)
        return panel

    # ── Wallet value update ────────────────────────────────────────────────────

    def _on_wallet_value_changed(self, wallet_usd_value: float) -> None:
        self._wallet_usd_value = wallet_usd_value
        total = compute_total_tracked_value(self._active_value, wallet_usd_value)

        self._total_card.update_value(f"${total:,.2f}", _BLUE)
        self._wallet_card.update_value(f"${wallet_usd_value:,.2f}", _TEXT)

        save_wallet_snapshot(
            active_positions_value=self._active_value,
            wallet_usd_value=wallet_usd_value,
            unrealized_pnl=self._unrealized_pnl,
            realized_pnl=self._realized_pnl,
        )
        snaps = load_wallet_snapshots()
        self._chart.update_snapshots(snaps)
        self.snapshots_changed.emit(snaps)

    # ── Live positions update ──────────────────────────────────────────────────

    def _on_positions_fetched(self, active: list, redeemable: list, closed: list) -> None:
        metrics = compute_dashboard_metrics(active, redeemable)
        self._active_value   = metrics["active_positions_value"]
        self._unrealized_pnl = metrics["unrealized_pnl"]
        self._realized_pnl   = metrics["realized_pnl"]

        total = compute_total_tracked_value(self._active_value, self._wallet_usd_value)
        self._total_card.update_value(f"${total:,.2f}", _BLUE)
        self._active_card.update_value(f"${self._active_value:,.2f}", _BLUE)
        self._unreal_card.update_value(f"${self._unrealized_pnl:,.2f}", _pnl_color(self._unrealized_pnl))
        self._win_card.update_value(str(metrics["win_count"]), _GREEN)
        self._loss_card.update_value(str(metrics["loss_count"]), _RED)

        self._replace_section("_act_section", _active_section(active))
        self._replace_section("_res_section", _resolved_section(redeemable))

        self.positions_changed.emit(active, redeemable, closed)

    def _replace_section(self, attr: str, new_widget: QWidget) -> None:
        old = getattr(self, attr)
        idx = self._content_layout.indexOf(old)
        if idx >= 0:
            self._content_layout.removeWidget(old)
            old.deleteLater()
            self._content_layout.insertWidget(idx, new_widget)
        setattr(self, attr, new_widget)
