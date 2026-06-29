from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.database import (
    clear_wallet_snapshots_today,
    load_last_wallet,
    load_loss_watch_acknowledged,
    load_wallet_snapshots,
    save_loss_watch_acknowledged,
    save_wallet_snapshot,
)
from app.debug import _dlog
from app.models import ActivePosition, ResolvedPosition, UserActivity
from app.services.loss_watch import compute_loss_watch_count
from app.services.metrics import compute_dashboard_metrics, compute_total_tracked_value
from app.services.pnl_today import filter_closed_by_range, is_data_partial
from app.ui.pnl_chart import PnlChartWidget
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

_RANGE_BTN_ACTIVE = (
    f"background-color: #1f2937; border: 1px solid {_BLUE}; border-radius: 4px;"
    f" color: {_BLUE}; padding: 3px 14px; font-size: 12px; font-weight: 600;"
)
_RANGE_BTN_IDLE = (
    f"background-color: #21262d; border: 1px solid {_BORDER}; border-radius: 4px;"
    f" color: {_MUTED}; padding: 3px 14px; font-size: 12px;"
)


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


# ── Loss Watch card (with Acknowledge button) ──────────────────────────────────

class _LossWatchCard(QFrame):
    def __init__(self):
        super().__init__()
        self.setStyleSheet(_CARD_FRAME_S)
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(14, 12, 14, 12)
        vbox.setSpacing(4)

        t = QLabel("LOSS WATCH")
        t.setStyleSheet(_METRIC_TITLE_S)

        self._val = QLabel("—")
        self._val.setStyleSheet(f"color: {_MUTED}; font-size: 20px; font-weight: 700;")
        self._val.setAlignment(_L | _V)

        self._sub = QLabel("unacknowledged losing positions")
        self._sub.setStyleSheet(f"color: {_MUTED}; font-size: 11px;")

        self._btn = QPushButton("Acknowledge All")
        self._btn.setStyleSheet(
            f"background-color: #21262d; border: 1px solid {_BORDER}; border-radius: 4px;"
            f" color: {_MUTED}; padding: 3px 10px; font-size: 11px; margin-top: 4px;"
        )
        self._btn.setEnabled(False)

        vbox.addWidget(t)
        vbox.addWidget(self._val)
        vbox.addWidget(self._sub)
        vbox.addWidget(self._btn)

    def update_count(self, count: int) -> None:
        if count > 0:
            self._val.setText(str(count))
            self._val.setStyleSheet(f"color: {_RED}; font-size: 20px; font-weight: 700;")
            self._btn.setEnabled(True)
        else:
            self._val.setText("0")
            self._val.setStyleSheet(f"color: {_MUTED}; font-size: 20px; font-weight: 700;")
            self._btn.setEnabled(False)

    @property
    def acknowledge_btn(self) -> QPushButton:
        return self._btn


# ── Grid-based flat table ──────────────────────────────────────────────────────

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

_RES_HDRS  = ["Market", "Outcome", "Winning Outcome", "Qty", "Cost Basis", "Redeem Value", "Realized P/L", "P/L %"]
_RES_ALIGN = [_L, _L, _L, _R, _R, _R, _R, _R]


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
        cells = [
            (p.market,                          _L, _TEXT),
            (p.outcome_held,                    _L, oc),
            (p.winning_outcome,                 _L, _TEXT),
            (f"{p.quantity:,.0f}",              _R, _TEXT),
            (f"${p.cost_basis:,.2f}",           _R, _TEXT),
            (f"${p.redeem_value:,.2f}",         _R, _TEXT),
            (f"${p.realized_pnl:,.2f}",         _R, pc),
            (f"{p.realized_pnl_pct:+.1f}%",    _R, pc),
        ]
        for col, (text, align, color) in enumerate(cells):
            grid.addWidget(_row_cell(text, align, color), r, col)

    grid.setColumnStretch(0, 1)
    vbox.addWidget(frame)
    return outer


# ── Closed positions section ───────────────────────────────────────────────────

_CLS_HDRS  = ["Market", "Outcome", "Result", "Cost Basis", "Proceeds", "Realized P/L", "P/L %", "Resolved"]
_CLS_ALIGN = [_L, _L, _L, _R, _R, _R, _R, _L]


def _closed_section(positions: List[ResolvedPosition], range_label: str = "1D") -> QWidget:
    outer = QWidget()
    vbox = QVBoxLayout(outer)
    vbox.setContentsMargins(0, 0, 0, 0)
    vbox.setSpacing(8)

    lbl = QLabel(f"Closed Positions — {range_label}  ({len(positions)})")
    lbl.setStyleSheet(_SECTION_HDR_S)
    vbox.addWidget(lbl)

    frame = QFrame()
    frame.setStyleSheet(f"QFrame {{ background-color: {_BG}; border: 1px solid {_BORDER}; }}")
    grid = QGridLayout(frame)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(0)

    for col, (h, a) in enumerate(zip(_CLS_HDRS, _CLS_ALIGN)):
        grid.addWidget(_col_hdr(h, a), 0, col)

    for r, p in enumerate(positions, start=1):
        pc = _pnl_color(p.realized_pnl)
        rc = _GREEN if p.is_win else _RED
        resolved_str = (p.resolved_date or "")[:10] if p.resolved_date else "—"
        cells = [
            (p.market,                         _L, _TEXT),
            (p.outcome_held,                   _L, _TEXT),
            ("Win" if p.is_win else "Loss",    _L, rc),
            (f"${p.cost_basis:,.2f}",          _R, _TEXT),
            (f"${p.redeem_value:,.2f}",        _R, _TEXT),
            (f"${p.realized_pnl:,.2f}",        _R, pc),
            (f"{p.realized_pnl_pct:+.1f}%",   _R, pc),
            (resolved_str,                     _L, _MUTED),
        ]
        for col, (text, align, color) in enumerate(cells):
            grid.addWidget(_row_cell(text, align, color), r, col)

    grid.setColumnStretch(0, 1)
    vbox.addWidget(frame)
    return outer


# ── Date-range filtering ───────────────────────────────────────────────────────

_RANGE_LABELS = {
    "1d":  "1D",
    "1w":  "1W",
    "1m":  "1M",
    "1y":  "1Y",
    "ytd": "YTD",
    "all": "All",
}


# ── Overview widget ────────────────────────────────────────────────────────────

class OverviewWidget(QWidget):
    positions_changed    = Signal(list, list, list)  # (active, resolved, closed)
    snapshots_changed    = Signal(list)              # updated snapshot list
    activity_changed     = Signal(list)              # activity feed
    closed_cache_updated = Signal(list)              # full closed history after backfill
    more_closed          = Signal(list)              # next closed positions page for scroll-load
    more_activity        = Signal(list)              # next activity page for infinite scroll

    def __init__(
        self,
        active: List[ActivePosition],
        resolved: List[ResolvedPosition],
        metrics: dict,
    ):
        super().__init__()

        self._active_value         = metrics["active_positions_value"]
        self._unrealized_pnl       = metrics["unrealized_pnl"]
        self._realized_pnl         = metrics["realized_pnl"]
        self._wallet_usd_value     = 0.0
        self._active_positions     = list(active)
        self._closed_positions: List[ResolvedPosition] = []
        self._activity: list       = []
        self._acknowledged_markets = load_loss_watch_acknowledged()
        self._range                = "1d"
        # Wallet address for tagging snapshots — updated on confirmed fetch
        self._confirmed_wallet     = load_last_wallet()
        # Guard: clear today's stale snapshots (saved before real positions load) on first fetch
        self._first_positions_fetch = True

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        main = QVBoxLayout(content)
        main.setContentsMargins(16, 16, 16, 20)
        main.setSpacing(0)
        self._content_layout = main

        # ── Wallet panel ───────────────────────────────────────────────
        self._wallet_panel = WalletPanel()
        self._wallet_panel.wallet_address_changed.connect(self._on_wallet_address_changed)
        self._wallet_panel.wallet_value_changed.connect(self._on_wallet_value_changed)
        self._wallet_panel.positions_fetched.connect(self._on_positions_fetched)
        self._wallet_panel.activity_fetched.connect(self._on_activity_fetched)
        self._wallet_panel.closed_cache_updated.connect(self._on_closed_cache_updated)
        self._wallet_panel.more_closed_fetched.connect(self.more_closed.emit)
        self._wallet_panel.more_activity_fetched.connect(self._on_more_activity_fetched)
        main.addWidget(self._wallet_panel)

        main.addSpacing(12)

        # ── Time range filter ──────────────────────────────────────────
        main.addWidget(self._build_range_bar())
        main.addSpacing(14)

        # ── Cards (left) + Total Tracked Value chart (right) ──────────
        top = QWidget()
        top.setMinimumHeight(280)
        top_row = QHBoxLayout(top)
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(14)

        cards_panel = self._build_cards_panel(metrics, active, resolved)
        top_row.addWidget(cards_panel, 42)

        self._chart = PnlChartWidget([], [], self._range)
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
        main.addSpacing(20)
        main.addWidget(_divider())
        main.addSpacing(16)

        # ── Closed positions ───────────────────────────────────────────
        self._cls_section = _closed_section([], _RANGE_LABELS[self._range])
        main.addWidget(self._cls_section)
        main.addStretch(1)

        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ── Range filter bar ───────────────────────────────────────────────────────

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
            btn.setStyleSheet(_RANGE_BTN_ACTIVE if key == self._range else _RANGE_BTN_IDLE)
            btn.clicked.connect(lambda _checked, k=key: self._on_range_changed(k))
            self._range_btns[key] = btn
            row.addWidget(btn)

        row.addStretch(1)
        return bar

    def _on_range_changed(self, range_: str) -> None:
        self._range = range_
        for key, btn in self._range_btns.items():
            btn.setStyleSheet(_RANGE_BTN_ACTIVE if key == range_ else _RANGE_BTN_IDLE)
        filtered = filter_closed_by_range(self._closed_positions, range_)
        self._replace_section("_cls_section", _closed_section(filtered, _RANGE_LABELS[range_]))
        self._chart.update(self._activity, self._closed_positions, range_)
        self._update_metric_cards()

    # ── Card panel ─────────────────────────────────────────────────────────────

    def _build_cards_panel(
        self,
        m: dict,
        active: List[ActivePosition],
        resolved: List[ResolvedPosition],
    ) -> QWidget:
        panel = QWidget()
        vbox = QVBoxLayout(panel)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(10)

        # Row 1: Total Tracked Value | Wallet USD Value | Positions Value
        self._total_card  = _MetricCard("Total Tracked Value", f"${m['total_tracked_value']:,.2f}", _BLUE)
        self._wallet_card = _MetricCard("Wallet USD Value",    "$0.00", _MUTED)
        self._active_card = _MetricCard("Positions Value",     f"${m['active_positions_value']:,.2f}", _BLUE)

        # Row 2: Loss Watch | Realized P/L Today | Trades Today
        self._loss_watch_card = _LossWatchCard()
        initial_lw = compute_loss_watch_count(active, self._acknowledged_markets)
        self._loss_watch_card.update_count(initial_lw)
        self._loss_watch_card.acknowledge_btn.clicked.connect(self._on_acknowledge)

        self._pnl_today_card    = _MetricCard("Realized P/L", "—", _MUTED)
        self._trades_today_card = _MetricCard("Trades",       "—", _TEXT)

        row1 = QHBoxLayout()
        row1.setSpacing(10)
        row1.addWidget(self._total_card)
        row1.addWidget(self._wallet_card)
        row1.addWidget(self._active_card)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        row2.addWidget(self._loss_watch_card)
        row2.addWidget(self._pnl_today_card)
        row2.addWidget(self._trades_today_card)

        vbox.addLayout(row1)
        vbox.addLayout(row2)
        return panel

    # ── Loss Watch acknowledge ─────────────────────────────────────────────────

    def _on_acknowledge(self) -> None:
        losing_markets = [
            p.market for p in self._active_positions if p.unrealized_pnl < 0
        ]
        self._acknowledged_markets = losing_markets
        save_loss_watch_acknowledged(self._acknowledged_markets)
        count = compute_loss_watch_count(self._active_positions, self._acknowledged_markets)
        self._loss_watch_card.update_count(count)

    # ── Wallet address change ──────────────────────────────────────────────────

    def _on_wallet_address_changed(self, address: str) -> None:
        # Always refresh the Total Tracked Value chart snapshots
        snaps = load_wallet_snapshots(address)
        self.snapshots_changed.emit(snaps)

        if address == self._confirmed_wallet:
            # Same wallet re-confirmed (startup refresh or auto-refresh).
            # Do NOT clear cached data — seed_from_cache already populated it.
            _dlog("wallet", "same wallet re-confirmed (%s) — keeping %d cached activity rows",
                  address[:10], len(self._activity))
            return

        # Truly different wallet: switch caches and clear stale data
        _dlog("wallet", "wallet changed to %s — clearing cached data", address[:10])
        self._confirmed_wallet = address
        self._activity = []
        self._closed_positions = []
        self._chart.update([], [], self._range)

    # ── Wallet value update ────────────────────────────────────────────────────

    def _on_wallet_value_changed(self, wallet_usd_value: float) -> None:
        self._wallet_usd_value = wallet_usd_value
        total = compute_total_tracked_value(self._active_value, wallet_usd_value)
        self._total_card.update_value(f"${total:,.2f}", _TEXT)
        self._wallet_card.update_value(f"${wallet_usd_value:,.2f}", _TEXT)
        # Snapshot is saved in _on_positions_fetched once both wallet USD and
        # real positions values are known — saving here would use stale sample data

    # ── Live positions update ──────────────────────────────────────────────────

    def _on_positions_fetched(self, active: list, resolved: list, closed: list) -> None:
        self._active_positions = list(active)
        # Merge closed: keep everything already loaded, prepend any new records
        if not self._closed_positions:
            self._closed_positions = list(closed)
        else:
            seen  = {(p.market, p.outcome_held, p.cost_basis) for p in self._closed_positions}
            fresh = [p for p in closed if (p.market, p.outcome_held, p.cost_basis) not in seen]
            if fresh:
                self._closed_positions = fresh + self._closed_positions
        metrics = compute_dashboard_metrics(active, resolved)
        self._active_value   = metrics["active_positions_value"]
        self._unrealized_pnl = metrics["unrealized_pnl"]
        self._realized_pnl   = metrics["realized_pnl"]

        total = compute_total_tracked_value(self._active_value, self._wallet_usd_value)
        self._total_card.update_value(f"${total:,.2f}", _TEXT)
        self._active_card.update_value(f"${self._active_value:,.2f}", _TEXT)

        lw_count = compute_loss_watch_count(active, self._acknowledged_markets)
        self._loss_watch_card.update_count(lw_count)

        self._replace_section("_act_section", _active_section(active))
        self._replace_section("_res_section", _resolved_section(resolved))

        filtered = filter_closed_by_range(self._closed_positions, self._range)
        self._replace_section("_cls_section", _closed_section(filtered, _RANGE_LABELS[self._range]))
        self._chart.update(self._activity, self._closed_positions, self._range)
        self._update_metric_cards()

        # Save snapshot now that both wallet USD and real positions values are settled.
        # On the first fetch of each session, wipe today's snapshots first — any that
        # were saved before positions loaded used stale sample data and are wrong.
        if self._confirmed_wallet:
            if self._first_positions_fetch:
                self._first_positions_fetch = False
                clear_wallet_snapshots_today(self._confirmed_wallet)
            save_wallet_snapshot(
                wallet_address=self._confirmed_wallet,
                active_positions_value=self._active_value,
                wallet_usd_value=self._wallet_usd_value,
                unrealized_pnl=self._unrealized_pnl,
                realized_pnl=self._realized_pnl,
            )
            snaps = load_wallet_snapshots(self._confirmed_wallet)
            self.snapshots_changed.emit(snaps)

        self.positions_changed.emit(active, resolved, closed)

    # ── Activity update ────────────────────────────────────────────────────────

    def _on_activity_fetched(self, activity: list) -> None:
        # Merge fresh API records into the in-memory list; never replace the cached
        # history with just the newest 100 API rows from the live refresh.
        before = len(self._activity)
        if not self._activity:
            self._activity = list(activity)
        else:
            seen  = {(a.timestamp, a.type, a.side, a.size) for a in self._activity}
            fresh = [a for a in activity if (a.timestamp, a.type, a.side, a.size) not in seen]
            if fresh:
                self._activity = fresh + self._activity
        _dlog("activity", "fetched %d rows → merged to %d total (was %d)",
              len(activity), len(self._activity), before)
        self.activity_changed.emit(activity)
        self._chart.update(self._activity, self._closed_positions, self._range)
        self._update_metric_cards()

    def _on_more_activity_fetched(self, page: list) -> None:
        # Scroll-loaded pages are older records — extend without duplicating
        before = len(self._activity)
        seen  = {(a.timestamp, a.type, a.side, a.size) for a in self._activity}
        fresh = [a for a in page if (a.timestamp, a.type, a.side, a.size) not in seen]
        self._activity.extend(fresh)
        _dlog("activity", "scroll-load %d rows → %d new, total now %d",
              len(page), len(fresh), len(self._activity))
        self.more_activity.emit(page)
        self._chart.update(self._activity, self._closed_positions, self._range)
        self._update_metric_cards()

    def _update_metric_cards(self) -> None:
        filtered = filter_closed_by_range(self._closed_positions, self._range)
        partial  = is_data_partial(self._closed_positions, self._range) or self._chart.is_partial
        prefix   = "~" if partial else ""

        pnl   = sum(p.realized_pnl for p in filtered)
        color = _GREEN if pnl > 0 else (_RED if pnl < 0 else _MUTED)
        display = f"{prefix}${pnl:+,.2f}" if pnl != 0 else f"{prefix}$0.00"
        self._pnl_today_card.update_value(display, color)
        self._trades_today_card.update_value(
            f"{prefix}{len(filtered)}" if filtered else "0", _TEXT
        )

    # ── Closed cache updates (backfill pages) ─────────────────────────────────

    def _on_closed_cache_updated(self, all_closed: list) -> None:
        self._closed_positions = list(all_closed)
        filtered = filter_closed_by_range(all_closed, self._range)
        self._replace_section("_cls_section", _closed_section(filtered, _RANGE_LABELS[self._range]))
        self._chart.update(self._activity, all_closed, self._range)
        self._update_metric_cards()
        self.closed_cache_updated.emit(all_closed)

    # ── Public ─────────────────────────────────────────────────────────────────

    def seed_from_cache(self, closed: list, activity: list = None) -> None:
        """Pre-populate with cached data before the first live fetch.

        Called by MainWindow on startup when cached data exists for the wallet.
        Seeds closed positions and (optionally) activity so the 1D chart can
        show intraday points immediately from cached REDEEM events.
        """
        self._closed_positions = list(closed)
        if activity is not None:
            self._activity = list(activity)
        _dlog("cache", "seed_from_cache: %d closed, %d activity",
              len(self._closed_positions), len(self._activity))
        filtered = filter_closed_by_range(closed, self._range)
        self._replace_section("_cls_section", _closed_section(filtered, _RANGE_LABELS[self._range]))
        self._chart.update(self._activity, closed, self._range)
        self._update_metric_cards()

    def request_refresh(self) -> None:
        self._wallet_panel.request_refresh()

    def on_load_more_closed(self, offset: int) -> None:
        """Called by the Closed Positions tab's scroll handler to request the next page."""
        self._wallet_panel.fetch_closed_page(offset)

    def on_load_more_activity(self, offset: int) -> None:
        """Called by the Activity tab's scroll handler to request the next page."""
        self._wallet_panel.fetch_activity_page(offset)

    def reload_acknowledged(self) -> None:
        self._acknowledged_markets = load_loss_watch_acknowledged()
        count = compute_loss_watch_count(self._active_positions, self._acknowledged_markets)
        self._loss_watch_card.update_count(count)

    def _replace_section(self, attr: str, new_widget: QWidget) -> None:
        old = getattr(self, attr)
        idx = self._content_layout.indexOf(old)
        if idx >= 0:
            self._content_layout.removeWidget(old)
            old.deleteLater()
            self._content_layout.insertWidget(idx, new_widget)
        setattr(self, attr, new_widget)
