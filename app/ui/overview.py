import time
from datetime import datetime
from typing import List

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.services import notes as _notes
from app.services.window_timing import window_closed as _window_closed
from app.ui.polymarket_menu import MENU_STYLE, NOTE_INDICATOR, _run_note_dialog, open_polymarket

from app.database import (
    clear_wallet_snapshots_today,
    load_all_closed_for_wallet,
    load_last_wallet,
    load_loss_watch_acknowledged,
    load_wallet_snapshots,
    save_loss_watch_acknowledged,
    save_wallet_snapshot,
    upsert_activity_derived_closed_positions,
)
from app.debug import _dlog
from app.models import ActivePosition, ResolvedPosition, UserActivity
from app.services.loss_watch import compute_loss_watch_count
from app.services.market_stream import MarketStreamThread
from app.services.user_stream import UserStreamThread
from app.services import credentials as _creds
from app.services.metrics import compute_dashboard_metrics, compute_total_tracked_value
from app.services.daily_pnl import sort_closed_positions_newest_first
from app.services.pnl_today import (
    classify_closed_positions,
    derive_closed_from_activity,
    derive_sold_from_activity,
)
from app.services.date_range import (
    DateRangeSelection,
    filter_closed_by_selection,
)
from app.ui.date_range_control import DateRangeControl
from app.ui.pnl_chart import PnlChartWidget

try:
    from zoneinfo import ZoneInfo as _ZoneInfo
    _ET_ZONE = _ZoneInfo("America/New_York")
except Exception:
    from datetime import timezone, timedelta as _td
    _ET_ZONE = timezone(_td(hours=-5))

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

        self._btn = QPushButton("Acknowledge All")
        self._btn.setStyleSheet(
            f"background-color: #21262d; border: 1px solid {_BORDER}; border-radius: 4px;"
            f" color: {_MUTED}; padding: 3px 10px; font-size: 11px; margin-top: 4px;"
        )
        self._btn.setEnabled(False)

        vbox.addWidget(t)
        vbox.addWidget(self._val)
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


def _market_row_cell(text: str, slug: str = None) -> QLabel:
    """Market cell with optional right-click menu (Open on Polymarket + Add Note)."""
    note = _notes.get(text)
    display = text + NOTE_INDICATOR if note else text
    lbl = _row_cell(display)
    lbl.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    if slug and note:
        lbl.setToolTip(f"✏️ {note}\n\nRight-click to open on Polymarket")
    elif slug:
        lbl.setToolTip("Right-click to open on Polymarket")
    elif note:
        lbl.setToolTip(f"✏️ {note}")

    def _show_menu(pos, _market=text, _slug=slug, _lbl=lbl):
        from PySide6.QtWidgets import QApplication, QInputDialog
        current_note = _notes.get(_market)
        menu = QMenu(_lbl)
        menu.setStyleSheet(MENU_STYLE)
        open_action  = None
        copy_action  = None
        clear_action = None
        if _slug:
            open_action = menu.addAction("Open on Polymarket")
            copy_action = menu.addAction("Copy Slug")
            menu.addSeparator()
        note_label  = "Edit Note…" if current_note else "Add Note…"
        note_action = menu.addAction(note_label)
        if current_note:
            clear_action = menu.addAction("Clear Note")
        chosen = menu.exec(_lbl.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == open_action:
            open_polymarket(_slug)
        elif chosen == copy_action:
            QApplication.clipboard().setText(_slug)
        elif chosen == note_action:
            new_note, ok = _run_note_dialog(_lbl, _market, current_note)
            if not ok:
                return
            if new_note:
                _notes.set(_market, new_note)
                _lbl.setText(_market + NOTE_INDICATOR)
                _lbl.setToolTip(
                    f"✏️ {new_note}"
                    + ("\n\nRight-click to open on Polymarket" if _slug else "")
                )
            else:
                _notes.delete(_market)
                _lbl.setText(_market)
                _lbl.setToolTip("Right-click to open on Polymarket" if _slug else "")
        elif clear_action and chosen == clear_action:
            _notes.delete(_market)
            _lbl.setText(_market)
            _lbl.setToolTip("Right-click to open on Polymarket" if _slug else "")

    lbl.customContextMenuRequested.connect(_show_menu)
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

    lbl = QLabel("Active")
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
            (p.outcome,                       _L, _TEXT),
            (f"{p.quantity:,.0f}",            _R, _TEXT),
            (f"${p.avg_cost:.4f}",            _R, _TEXT),
            (f"${p.current_price:.4f}",       _R, _TEXT),
            (f"${p.current_value:,.2f}",      _R, _TEXT),
            (f"${p.unrealized_pnl:,.2f}",     _R, pc),
            (f"{p.unrealized_pnl_pct:+.1f}%", _R, pc),
        ]
        grid.addWidget(_market_row_cell(p.market, getattr(p, "slug", None)), r, 0)
        for col, (text, align, color) in enumerate(cells, start=1):
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

    lbl = QLabel("Resolved")
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
            (p.outcome_held,                    _L, oc),
            (p.winning_outcome,                 _L, _TEXT),
            (f"{p.quantity:,.0f}",              _R, _TEXT),
            (f"${p.cost_basis:,.2f}",           _R, _TEXT),
            (f"${p.redeem_value:,.2f}",         _R, _TEXT),
            (f"${p.realized_pnl:,.2f}",         _R, pc),
            (f"{p.realized_pnl_pct:+.1f}%",    _R, pc),
        ]
        grid.addWidget(_market_row_cell(p.market, getattr(p, "slug", None)), r, 0)
        for col, (text, align, color) in enumerate(cells, start=1):
            grid.addWidget(_row_cell(text, align, color), r, col)

    grid.setColumnStretch(0, 1)
    vbox.addWidget(frame)
    return outer


# ── Sold positions section ─────────────────────────────────────────────────────

_SOLD_HDRS  = ["Market", "Outcome Held", "Winning Outcome", "Sell Price", "Realized P/L", "P/L %", "Sold (ET)"]
_SOLD_ALIGN = [_L, _L, _L, _R, _R, _R, _L]


def _fmt_sold_time(p: ResolvedPosition) -> str:
    """Return the sell timestamp as MM-DD HH:MM:SS in ET, falling back to date only."""
    if p.closed_at:
        try:
            return datetime.fromtimestamp(p.closed_at, tz=_ET_ZONE).strftime("%m-%d %H:%M:%S")
        except (OSError, OverflowError, ValueError):
            pass
    if p.resolved_date:
        return p.resolved_date[:10]
    return "—"


def _sold_section(positions: List[ResolvedPosition], range_label: str = "") -> QWidget:
    """Closed positions that were CLOB-sold (stop-loss / manual exit).

    Shows only positions whose market window is still open (not yet resolved).
    Once the window end time passes, the position graduates to the Closed section.
    """
    sold = [p for p in positions
            if getattr(p, "close_type", None) == "SOLD"
            and not _window_closed(p.market, p.resolved_date, p.closed_at)]

    outer = QWidget()
    vbox = QVBoxLayout(outer)
    vbox.setContentsMargins(0, 0, 0, 0)
    vbox.setSpacing(8)

    count = len(sold)
    lbl = QLabel("Sold")
    lbl.setStyleSheet(_SECTION_HDR_S)
    vbox.addWidget(lbl)

    frame = QFrame()
    frame.setStyleSheet(f"QFrame {{ background-color: {_BG}; border: 1px solid {_BORDER}; }}")
    grid = QGridLayout(frame)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(0)

    for col, (h, a) in enumerate(zip(_SOLD_HDRS, _SOLD_ALIGN)):
        grid.addWidget(_col_hdr(h, a), 0, col)

    visible = sold[:_OVERVIEW_ROW_CAP]
    for r, p in enumerate(visible, start=1):
        pc = _pnl_color(p.realized_pnl)
        oc = _GREEN if p.realized_pnl >= 0 else _RED

        # Sell price per share = USDC received ÷ shares sold
        qty = p.quantity if p.quantity > 0 else 1
        sell_price = p.redeem_value / qty

        wo     = p.winning_outcome or ""
        wo_col = _TEXT if wo else _MUTED
        wo_lbl = wo if wo else "Pending…"

        cells = [
            (p.outcome_held,                  _L, oc),
            (wo_lbl,                          _L, wo_col),
            (f"${sell_price:.4f}",            _R, _TEXT),
            (f"${p.realized_pnl:,.2f}",       _R, pc),
            (f"{p.realized_pnl_pct:+.1f}%",  _R, pc),
            (_fmt_sold_time(p),               _L, _MUTED),
        ]
        grid.addWidget(_market_row_cell(p.market, getattr(p, "slug", None)), r, 0)
        for col, (text, align, color) in enumerate(cells, start=1):
            grid.addWidget(_row_cell(text, align, color), r, col)

    if count > _OVERVIEW_ROW_CAP:
        overflow_lbl = QLabel(
            f"  … {count - _OVERVIEW_ROW_CAP:,} more — see Closed Positions tab"
        )
        overflow_lbl.setStyleSheet(f"color: {_MUTED}; font-size: 11px; padding: 4px 6px;")
        grid.addWidget(overflow_lbl, len(visible) + 1, 0, 1, len(_SOLD_HDRS))

    grid.setColumnStretch(0, 1)
    vbox.addWidget(frame)
    return outer


# ── Closed positions section ───────────────────────────────────────────────────

_CLS_HDRS  = ["Market", "Outcome", "Result", "Cost Basis", "Proceeds", "Realized P/L", "P/L %", "Closed"]
_CLS_ALIGN = [_L, _L, _L, _R, _R, _R, _R, _L]


def _fmt_closed_date(p: ResolvedPosition) -> str:
    """Return the actual close date in ET (from closed_at), falling back to resolved_date."""
    if p.closed_at:
        try:
            return datetime.fromtimestamp(p.closed_at, tz=_ET_ZONE).strftime("%Y-%m-%d")
        except (OSError, OverflowError, ValueError):
            pass
    if p.resolved_date:
        return p.resolved_date[:10]
    return "—"


_OVERVIEW_ROW_CAP = 100   # max rows rendered in the overview panel grid


def _closed_section(
    positions: List[ResolvedPosition],
    range_label: str = "1D",
    activity: list = None,
) -> QWidget:
    # Show definitively resolved positions (REDEEMED_WIN / RESOLVED_LOSS) plus
    # any SOLD positions whose market window has now closed — those graduate here
    # from the Sold section once the window end time passes.
    positions = [p for p in positions
                 if getattr(p, "close_type", None) != "SOLD"
                 or _window_closed(p.market, p.resolved_date, p.closed_at)]

    outer = QWidget()
    vbox = QVBoxLayout(outer)
    vbox.setContentsMargins(0, 0, 0, 0)
    vbox.setSpacing(8)

    total = len(positions)
    lbl = QLabel(f"Closed — {range_label}")
    lbl.setStyleSheet(_SECTION_HDR_S)
    vbox.addWidget(lbl)

    frame = QFrame()
    frame.setStyleSheet(f"QFrame {{ background-color: {_BG}; border: 1px solid {_BORDER}; }}")
    grid = QGridLayout(frame)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(0)

    for col, (h, a) in enumerate(zip(_CLS_HDRS, _CLS_ALIGN)):
        grid.addWidget(_col_hdr(h, a), 0, col)

    visible = positions[:_OVERVIEW_ROW_CAP]
    for r, p in enumerate(visible, start=1):
        pc = _pnl_color(p.realized_pnl)
        rc = _GREEN if p.is_win else _RED
        cells = [
            (p.outcome_held,                   _L, _TEXT),
            ("Win" if p.is_win else "Loss",    _L, rc),
            (f"${p.cost_basis:,.2f}",          _R, _TEXT),
            (f"${p.redeem_value:,.2f}",        _R, _TEXT),
            (f"${p.realized_pnl:,.2f}",        _R, pc),
            (f"{p.realized_pnl_pct:+.1f}%",   _R, pc),
            (_fmt_closed_date(p),              _L, _MUTED),
        ]
        mkt_lbl = _market_row_cell(p.market, getattr(p, "slug", None))
        grid.addWidget(mkt_lbl, r, 0)
        row_labels = [mkt_lbl]
        for col, (text, align, color) in enumerate(cells, start=1):
            cell_lbl = _row_cell(text, align, color)
            grid.addWidget(cell_lbl, r, col)
            row_labels.append(cell_lbl)

        # Attach double-click to every cell in this row so the user can
        # double-click anywhere on the row to open the transactions dialog.
        if activity is not None:
            def _make_dclick(_p=p, _act=activity):
                def _handler(event):
                    if event.button() == Qt.MouseButton.LeftButton:
                        from app.ui.position_transactions_dialog import (
                            PositionTransactionsDialog,
                        )
                        dlg = PositionTransactionsDialog(_p.market, _act)
                        dlg.exec()
                return _handler
            _fn = _make_dclick()
            for cell_lbl in row_labels:
                cell_lbl.mouseDoubleClickEvent = _fn

    if total > _OVERVIEW_ROW_CAP:
        overflow_lbl = QLabel(
            f"  … {total - _OVERVIEW_ROW_CAP:,} more — see Closed Positions tab"
        )
        overflow_lbl.setStyleSheet(f"color: {_MUTED}; font-size: 11px; padding: 4px 6px;")
        grid.addWidget(overflow_lbl, len(visible) + 1, 0, 1, len(_CLS_HDRS))

    grid.setColumnStretch(0, 1)
    vbox.addWidget(frame)
    return outer


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
        wallet_panel: "WalletPanel",
    ):
        super().__init__()

        self._active_value         = metrics["active_positions_value"]
        self._unrealized_pnl       = metrics["unrealized_pnl"]
        self._realized_pnl         = metrics["realized_pnl"]
        self._wallet_usd_value     = 0.0
        self._active_positions     = list(active)
        self._closed_positions: List[ResolvedPosition] = []
        self._sold_stubs:       List[ResolvedPosition] = []   # ephemeral stubs from SELL activity
        self._activity: list       = []
        self._acknowledged_markets = load_loss_watch_acknowledged()
        self._selection            = DateRangeSelection.preset_range("1d")
        # Wallet address for tagging snapshots — updated on confirmed fetch
        self._confirmed_wallet     = load_last_wallet()
        # Guard: clear today's stale snapshots (saved before real positions load) on first fetch
        self._first_positions_fetch = True

        # Market stream (WebSocket) — started once we have CLOB token IDs from live fetch
        self._stream: MarketStreamThread | None = None
        self._stream_token_ids: set             = set()
        self._price_update_pending: bool        = False
        self._trade_debounce: QTimer | None     = None

        # User stream (authenticated WebSocket) — started when credentials are loaded
        self._user_stream: UserStreamThread | None = None
        self._user_stream_connected: bool          = False
        # Dedup: trade IDs we have already processed from the user stream
        self._seen_trade_ids: set[str]             = set()
        # Settings tab reference for status feedback (set via set_settings_tab())
        self._settings_tab = None

        # WalletPanel is owned by MainWindow / displayed in SettingsTab;
        # we hold a reference here for data-flow purposes only (no layout add).
        self._wallet_panel = wallet_panel
        self._wallet_panel.wallet_address_changed.connect(self._on_wallet_address_changed)
        self._wallet_panel.wallet_value_changed.connect(self._on_wallet_value_changed)
        self._wallet_panel.positions_fetched.connect(self._on_positions_fetched)
        self._wallet_panel.activity_fetched.connect(self._on_activity_fetched)
        self._wallet_panel.closed_cache_updated.connect(self._on_closed_cache_updated)
        self._wallet_panel.more_closed_fetched.connect(self.more_closed.emit)
        self._wallet_panel.more_activity_fetched.connect(self._on_more_activity_fetched)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        main = QVBoxLayout(content)
        main.setContentsMargins(16, 16, 16, 20)
        main.setSpacing(0)
        self._content_layout = main

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

        self._chart = PnlChartWidget([], [], self._selection.preset or "1d")
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

        # ── Sold positions (CLOB exits) ────────────────────────────────
        self._sold_section = _sold_section([], self._selection.display_label())
        main.addWidget(self._sold_section)
        main.addSpacing(20)
        main.addWidget(_divider())
        main.addSpacing(16)

        # ── Closed positions ───────────────────────────────────────────
        self._cls_section = _closed_section([], self._selection.display_label())
        main.addWidget(self._cls_section)
        main.addStretch(1)

        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ── Range filter bar ───────────────────────────────────────────────────────

    def _build_range_bar(self) -> QWidget:
        row = QWidget()
        hbox = QHBoxLayout(row)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(8)

        ctrl = DateRangeControl(default="1d", align="left")
        ctrl.range_changed.connect(self._on_range_changed)
        hbox.addWidget(ctrl, 1)

        # Market stream — real-time price ticks; hidden until actually connected
        self._stream_dot = QLabel("")
        self._stream_dot.setStyleSheet(
            f"color: {_GREEN}; font-size: 11px; padding: 0 6px;"
        )
        self._stream_dot.setToolTip(
            "Market price stream — live price ticks for active positions."
        )
        self._stream_dot.setVisible(False)
        hbox.addWidget(self._stream_dot, 0, Qt.AlignmentFlag.AlignRight)

        # User stream — authenticated trade notifications (hidden until credentials set)
        self._user_dot = QLabel("")
        self._user_dot.setStyleSheet(
            f"color: {_MUTED}; font-size: 11px; padding: 0 6px;"
        )
        self._user_dot.setToolTip(
            "User trade stream — authenticated live notifications\n"
            "for your own buys and sells."
        )
        self._user_dot.setVisible(False)
        hbox.addWidget(self._user_dot, 0, Qt.AlignmentFlag.AlignRight)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setFixedHeight(30)
        self._refresh_btn.setFixedWidth(90)
        self._refresh_btn.setStyleSheet(
            f"background-color: #21262d; border: 1px solid {_BORDER}; border-radius: 4px;"
            f" color: {_TEXT}; padding: 0 14px; font-size: 13px;"
        )
        self._refresh_btn.clicked.connect(self._on_refresh_clicked)
        hbox.addWidget(self._refresh_btn, 0, Qt.AlignmentFlag.AlignRight)

        return row

    def _on_refresh_clicked(self) -> None:
        self._refresh_btn.setText("Refreshing…")
        self._refresh_btn.setEnabled(False)
        # Re-enable after next positions fetch completes
        self._wallet_panel.positions_fetched.connect(
            self._on_refresh_done, Qt.ConnectionType.SingleShotConnection
        )
        self.request_refresh()

    def _on_refresh_done(self) -> None:
        self._refresh_btn.setText("Refresh")
        self._refresh_btn.setEnabled(True)

    # ── Market stream (WebSocket) ───────────────────────────────────────────────

    def _update_stream(self, token_ids: list) -> None:
        """Start or restart the market stream with the given CLOB token IDs.

        If the token set hasn't changed and the stream is running, does nothing.
        Called whenever active positions are refreshed so new buys are subscribed.
        """
        new_ids = set(filter(None, token_ids))
        if new_ids == self._stream_token_ids and self._stream and self._stream.isRunning():
            return
        self._stream_token_ids = new_ids
        self._stop_stream()
        if not new_ids:
            self._stream_dot.setVisible(False)
            return
        self._stream = MarketStreamThread(list(new_ids))
        self._stream.price_updated.connect(self._on_stream_price)
        self._stream.trade_occurred.connect(self._on_stream_trade)
        self._stream.market_resolved.connect(self._on_stream_resolved)
        self._stream.stream_connected.connect(self._on_stream_connected)
        self._stream.stream_disconnected.connect(self._on_stream_disconnected)
        self._stream.start()

    def _stop_stream(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.wait(1500)
            self._stream = None

    def _on_stream_connected(self) -> None:
        n = len(self._stream_token_ids)
        self._stream_dot.setText(f"● Prices  ({n})")
        self._stream_dot.setStyleSheet(f"color: {_GREEN}; font-size: 11px; padding: 0 6px;")
        self._stream_dot.setVisible(True)

    def _on_stream_disconnected(self) -> None:
        # Keep visible briefly while reconnecting; _update_stream hides it
        # again if there end up being no token IDs.
        self._stream_dot.setText("○  Prices…")
        self._stream_dot.setStyleSheet(f"color: {_MUTED}; font-size: 11px; padding: 0 6px;")
        self._stream_dot.setVisible(True)

    def _on_stream_price(self, asset_id: str, price: float) -> None:
        """Update the matching active position's current price and redraw the section.

        Debounced: multiple price events within 100 ms are coalesced into one redraw
        so rapid price ticks don't hammer the UI.
        """
        for p in self._active_positions:
            if getattr(p, "asset_id", None) == asset_id:
                p.current_price = price
        if not self._price_update_pending:
            self._price_update_pending = True
            QTimer.singleShot(100, self._flush_price_update)

    def _flush_price_update(self) -> None:
        """Apply accumulated price changes to the Active section and metric cards."""
        self._price_update_pending = False
        self._replace_section("_act_section", _active_section(self._active_positions))
        self._active_value = sum(p.current_value for p in self._active_positions)
        total = compute_total_tracked_value(self._active_value, self._wallet_usd_value)
        self._total_card.update_value(f"${total:,.2f}", _TEXT)
        self._active_card.update_value(f"${self._active_value:,.2f}", _TEXT)
        # Keep Loss Watch in sync with the updated unrealized P/L
        lw = compute_loss_watch_count(self._active_positions, self._acknowledged_markets)
        self._loss_watch_card.update_count(lw)

    def _on_stream_trade(self, asset_id: str, side: str) -> None:
        """Schedule a quick full refresh when any trade hits one of our tokens.

        Debounced to 5 s so a burst of trades (e.g. a merge position) only
        triggers one refresh.  Catches our own buys/sells much earlier than
        the 5-minute polling interval.
        """
        if self._trade_debounce and self._trade_debounce.isActive():
            return   # already scheduled
        self._trade_debounce = QTimer(self)
        self._trade_debounce.setSingleShot(True)
        self._trade_debounce.timeout.connect(self.request_refresh)
        self._trade_debounce.start(5_000)

    def _on_stream_resolved(self, asset_id: str, winning_outcome: str) -> None:
        """Trigger an immediate refresh when one of our markets resolves."""
        self.request_refresh()

    # ── User stream (authenticated WebSocket) ──────────────────────────────────

    def set_settings_tab(self, tab) -> None:
        """Store a reference to SettingsTab for status feedback."""
        self._settings_tab = tab

    def on_credentials_file_changed(self, path: str) -> None:
        """Called when the user picks or clears a credentials file in Settings.

        Reads the file, starts/restarts the user stream if credentials are valid,
        or stops it if the file is removed.
        """
        creds = _creds.load_from_file(path) if path else None
        if creds:
            api_key, secret, passphrase = creds
            self._start_user_stream(api_key, secret, passphrase)
        else:
            self._stop_user_stream()
            self._user_dot.setVisible(False)

    def _start_user_stream(self, api_key: str, secret: str, passphrase: str) -> None:
        """Start (or restart) the authenticated user stream."""
        self._stop_user_stream()
        self._user_stream_connected = False
        self._user_dot.setText("○  Trades…")
        self._user_dot.setStyleSheet(f"color: {_MUTED}; font-size: 11px; padding: 0 6px;")
        self._user_dot.setVisible(True)

        self._user_stream = UserStreamThread(api_key, secret, passphrase)
        self._user_stream.trade_event.connect(self._on_user_trade)
        self._user_stream.stream_connected.connect(self._on_user_stream_connected)
        self._user_stream.stream_disconnected.connect(self._on_user_stream_disconnected)
        self._user_stream.stream_error.connect(self._on_user_stream_error)
        self._user_stream.start()

        if self._settings_tab is not None:
            self._settings_tab.update_stream_status(False)

    def _stop_user_stream(self) -> None:
        if self._user_stream is not None:
            self._user_stream.stop()
            self._user_stream.wait(1500)
            self._user_stream = None
        self._user_stream_connected = False

    def _on_user_stream_connected(self) -> None:
        self._user_stream_connected = True
        self._user_dot.setText("● Trades")
        self._user_dot.setStyleSheet(f"color: {_GREEN}; font-size: 11px; padding: 0 6px;")
        self._user_dot.setVisible(True)
        if self._settings_tab is not None:
            self._settings_tab.update_stream_status(True)

    def _on_user_stream_disconnected(self) -> None:
        self._user_stream_connected = False
        self._user_dot.setText("○  Trades…")
        self._user_dot.setStyleSheet(f"color: {_MUTED}; font-size: 11px; padding: 0 6px;")
        if self._settings_tab is not None:
            self._settings_tab.update_stream_status(False)

    def _on_user_stream_error(self, error: str) -> None:
        """Handle a fatal stream error (auth rejected, server closed).

        Stops the reconnect loop so we don't hammer the server with bad
        credentials.  The user must fix the credentials file and re-select it.
        """
        self._stop_user_stream()
        self._user_stream_connected = False
        self._user_dot.setText("✗  Trades error")
        self._user_dot.setStyleSheet(f"color: #f85149; font-size: 11px; padding: 0 6px;")
        self._user_dot.setVisible(True)
        if self._settings_tab is not None:
            self._settings_tab.update_stream_status(False, error)

    def _on_user_trade(self, event: dict) -> None:
        """Handle a Trade Event from the authenticated user stream.

        For SELL: inject into the internal activity list (for sold-stub building)
        and immediately refresh the Sold section — no API round-trip needed.
        For BUY: trigger a 5-second debounced full refresh.

        We deliberately do NOT emit activity_changed here.  User-stream events
        often lack the market title at MATCHED status, which would add "—" rows
        to the Activity tab.  The Activity tab updates cleanly via the next API
        poll, which always has full titles.

        Only MATCHED events are acted on; subsequent MINED / CONFIRMED updates
        for the same trade ID are dropped by the seen-ID dedup.
        """
        status = (event.get("status") or "").upper()
        # Only act on the first confirmation (MATCHED); later status updates
        # (MINED, CONFIRMED) carry no new information for our purposes.
        # Empty status means the server omitted it — treat as MATCHED.
        if status and status not in ("MATCHED", ""):
            return

        # ── Dedup by server-assigned trade ID ─────────────────────────────────
        trade_id = event.get("id") or ""
        if trade_id:
            if trade_id in self._seen_trade_ids:
                return
            self._seen_trade_ids.add(trade_id)

        side     = (event.get("side") or "").upper()
        outcome  = event.get("outcome") or ""
        asset_id = event.get("asset_id") or ""
        size     = float(event.get("size")  or 0)
        price    = float(event.get("price") or 0)

        # ── Title lookup ───────────────────────────────────────────────────────
        # Trade Events at MATCHED status often omit the market title.
        # Look it up from active positions (which always have the title).
        title = event.get("title") or ""
        if not title and asset_id:
            for pos in self._active_positions:
                if getattr(pos, "asset_id", None) == asset_id:
                    title = pos.market
                    break
        # If we still have no title, check recent activity for the same asset
        if not title and asset_id:
            for act in self._activity[:200]:
                if act.title and getattr(act, "asset_id", None) == asset_id:
                    title = act.title
                    break

        # ── Timestamp ─────────────────────────────────────────────────────────
        ts_raw = event.get("match_time") or event.get("timestamp") or ""
        try:
            ts = int(float(ts_raw))
        except (ValueError, TypeError):
            try:
                from datetime import timezone
                dt = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                ts = int(dt.astimezone(timezone.utc).timestamp())
            except Exception:
                ts = int(time.time())

        _dlog("user_stream", "trade: %s %s '%s' qty=%.2f price=%.4f id=%s",
              side, outcome, title[:50], size, price, trade_id)

        # ── For SELL: inject into _activity (for sold-stub building only) ─────
        # We do NOT emit activity_changed — the Activity tab will get the clean
        # API version (with proper title) on the next poll.
        if side == "SELL":
            activity_row = UserActivity(
                timestamp = ts,
                type      = "TRADE",
                title     = title,
                outcome   = outcome,
                side      = side,
                size      = size,
                usdc_size = round(size * price, 6),
                price     = price,
                slug      = None,
            )
            # Only inject if we have a title — otherwise the stub would show "Unknown"
            # and be indistinguishable from other unknown stubs.
            if title:
                # Avoid double-injection if the API already fetched this trade
                key = (ts, "TRADE", side, size)
                already_there = any(
                    (a.timestamp, a.type, a.side, a.size) == key
                    for a in self._activity
                )
                if not already_there:
                    self._activity.insert(0, activity_row)

            # Rebuild Sold section immediately
            self._refresh_closed_section()

        # ── For BUY: debounced refresh to pick up new active position ─────────
        else:
            if not (self._trade_debounce and self._trade_debounce.isActive()):
                self._trade_debounce = QTimer(self)
                self._trade_debounce.setSingleShot(True)
                self._trade_debounce.timeout.connect(self.request_refresh)
                self._trade_debounce.start(5_000)

    def _on_range_changed(self, selection: DateRangeSelection) -> None:
        self._selection = selection
        self._refresh_closed_section()
        self._update_pnl_chart()
        self._update_metric_cards()

    def _rebuild_sold_stubs(self) -> None:
        """Derive ephemeral SOLD stubs from activity SELL events.

        Only keeps stubs for (market, outcome) pairs NOT already in _closed_positions
        so the real API entry always wins as soon as it arrives.
        """
        derived  = derive_sold_from_activity(self._activity)
        api_seen = {(p.market, p.outcome_held) for p in self._closed_positions}
        self._sold_stubs = [
            p for p in derived
            if (p.market, p.outcome_held) not in api_seen
        ]

    def _refresh_closed_section(self) -> None:
        self._rebuild_sold_stubs()
        filtered      = filter_closed_by_selection(self._closed_positions, self._selection)
        stub_filtered = filter_closed_by_selection(self._sold_stubs, self._selection)
        label         = self._selection.display_label()
        # Sold section: stubs whose market window is still open + real SOLD from API
        self._replace_section("_sold_section", _sold_section(stub_filtered + filtered, label))
        # Closed section: real positions + "graduated" stubs — stubs whose market
        # window has now closed but haven't yet appeared in the closed-positions API.
        # Without this, a freshly-sold position disappears for the brief window between
        # the market closing and the API indexing the record.
        graduated = [p for p in stub_filtered
                     if _window_closed(p.market, p.resolved_date, p.closed_at)]
        self._replace_section("_cls_section",  _closed_section(graduated + filtered, label, self._activity))

    def _update_pnl_chart(self) -> None:
        if self._selection.is_preset():
            self._chart.update(self._activity, self._closed_positions, self._selection.preset)
        else:
            filtered = filter_closed_by_selection(self._closed_positions, self._selection)
            self._chart.update(self._activity, filtered, "all")

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

        # Truly different wallet: reload notes for the new wallet, switch caches.
        _dlog("wallet", "wallet changed to %s — clearing cached data", address[:10])
        _notes.load_for_wallet(address)
        self._confirmed_wallet = address
        self._activity = []
        self._closed_positions = []
        self._chart.update([], [], self._selection.preset or "1d")
        # Stop market stream for old wallet — restarts once new wallet's positions load
        self._stop_stream()
        self._stream_token_ids = set()
        self._seen_trade_ids   = set()
        # User stream is per-credentials, not per-wallet — keep it running

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
            self._closed_positions = sort_closed_positions_newest_first(list(closed))
        else:
            seen  = {(p.market, p.outcome_held) for p in self._closed_positions}
            fresh = [p for p in closed if (p.market, p.outcome_held) not in seen]
            if fresh:
                self._closed_positions = sort_closed_positions_newest_first(
                    fresh + self._closed_positions
                )
        classify_closed_positions(self._closed_positions, self._activity)
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

        self._refresh_closed_section()
        self._update_pnl_chart()
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

        # Emit self._closed_positions (full merged history), NOT the raw API
        # `closed` list which is only the most-recent 100 rows.  Emitting the
        # 100-row slice would replace a larger cached dataset in the Closed tab.
        self.positions_changed.emit(active, resolved, self._closed_positions)

        # Start/update market stream with CLOB token IDs from the live fetch.
        # asset_id is only populated from live API data, not from the DB cache,
        # so this is the right place (not seed_from_cache).
        token_ids = [getattr(p, "asset_id", None) for p in active]
        self._update_stream(token_ids)

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

        # Derive new closed positions from fresh REDEEM events and persist to DB.
        # Supplements the /closed-positions API which may only return ~100 recent records.
        if self._confirmed_wallet and self._activity:
            derived = derive_closed_from_activity(self._activity)
            n_new = upsert_activity_derived_closed_positions(derived, self._confirmed_wallet)
            if n_new > 0:
                _dlog("activity", "derived %d new closed positions from activity", n_new)
                all_closed = load_all_closed_for_wallet(self._confirmed_wallet)
                seen_closed = {(p.market, p.outcome_held) for p in self._closed_positions}
                fresh_closed = [p for p in all_closed
                                if (p.market, p.outcome_held) not in seen_closed]
                if fresh_closed:
                    self._closed_positions = sort_closed_positions_newest_first(
                        fresh_closed + self._closed_positions
                    )
                    self.closed_cache_updated.emit(self._closed_positions)

        # Re-classify positions: new SELLs in activity may change close_type on existing positions
        classify_closed_positions(self._closed_positions, self._activity)
        # Emit the full merged list so ActivityTable sees all rows, not just the API page.
        self.activity_changed.emit(self._activity)
        self._update_pnl_chart()
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
        self._update_pnl_chart()
        self._update_metric_cards()

    def _update_metric_cards(self) -> None:
        # Use the complete in-memory lists loaded from SQLite on startup (no DB query).
        # load_all_closed_for_wallet and load_all_activity_for_wallet bring ALL cached
        # rows into memory at startup — no scroll, no limit, no DB round-trip here.
        filtered = filter_closed_by_selection(self._closed_positions, self._selection)
        pnl      = sum(p.realized_pnl for p in filtered)
        trades   = len(filtered)
        _dlog("pnl_check",
              "card: range=%s positions=%d filtered=%d pnl=%.2f",
              self._selection.display_label(), len(self._closed_positions), trades, pnl)

        color   = _GREEN if pnl > 0 else (_RED if pnl < 0 else _MUTED)
        display = f"${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
        self._pnl_today_card.update_value(display, color)
        self._trades_today_card.update_value(str(trades) if trades else "0", _TEXT)

    # ── Closed cache updates (backfill pages) ─────────────────────────────────

    def _on_closed_cache_updated(self, all_closed: list) -> None:
        if all_closed:
            # Merge: prefer the backfill's ordered set but preserve any rows the user
            # scroll-loaded beyond the backfill's coverage (e.g. older than limit=2000).
            seen_backfill = {(p.market, p.outcome_held) for p in all_closed}
            extra = [p for p in self._closed_positions
                     if (p.market, p.outcome_held) not in seen_backfill]
            self._closed_positions = sort_closed_positions_newest_first(
                list(all_closed) + extra
            )
        classify_closed_positions(self._closed_positions, self._activity)
        _dlog("backfill", "closed_positions now %d rows after cache update",
              len(self._closed_positions))
        self._refresh_closed_section()
        self._update_pnl_chart()
        self._update_metric_cards()
        self.closed_cache_updated.emit(self._closed_positions)

    # ── Public ─────────────────────────────────────────────────────────────────

    def seed_from_cache(self, closed: list, activity: list = None) -> None:
        """Pre-populate with cached data before the first live fetch.

        Called by MainWindow on startup when cached data exists for the wallet.
        Seeds closed positions and (optionally) activity so the 1D chart can
        show intraday points immediately from cached REDEEM events.
        """
        self._closed_positions = sort_closed_positions_newest_first(list(closed))
        if activity is not None:
            self._activity = list(activity)
        classify_closed_positions(self._closed_positions, self._activity)
        _dlog("cache", "seed_from_cache: %d closed, %d activity",
              len(self._closed_positions), len(self._activity))
        self._refresh_closed_section()
        self._update_pnl_chart()
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

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """Stop both streams cleanly before the widget is destroyed."""
        self._stop_stream()
        self._stop_user_stream()
        super().closeEvent(event)

    def apply_chart_style(self, smooth: bool, linewidth: float, fill_alpha: float) -> None:
        """Forward chart style options from Settings tab to the embedded chart."""
        self._chart.set_chart_style(smooth=smooth, linewidth=linewidth, fill_alpha=fill_alpha)

    def _replace_section(self, attr: str, new_widget: QWidget) -> None:
        old = getattr(self, attr)
        idx = self._content_layout.indexOf(old)
        if idx >= 0:
            self._content_layout.removeWidget(old)
            old.deleteLater()
            self._content_layout.insertWidget(idx, new_widget)
        setattr(self, attr, new_widget)
