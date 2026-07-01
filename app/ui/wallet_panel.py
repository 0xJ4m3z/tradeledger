import re
from datetime import datetime

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.adapters.polymarket_adapter import (
    PolymarketLookupError,
    fetch_active_positions,
    fetch_activity,
    fetch_activity_page,
    fetch_closed_positions,
    fetch_closed_positions_page,
    fetch_resolved_positions,
)
from app.adapters.wallet_adapter import WalletLookupError, fetch_wallet_usd_value
from app.database import (
    count_activity_cache,
    count_closed_positions_cache,
    init_db,
    load_activity_cache_page,
    load_all_closed_for_wallet,
    load_closed_positions_cache,
    load_closed_positions_cache_page,
    load_last_wallet,
    save_active_positions_cache,
    save_last_wallet,
    save_resolved_positions_cache,
    upsert_activity_cache,
    upsert_closed_positions_cache,
)
from app.debug import _dlog
from app.models import ActivePosition, ResolvedPosition, UserActivity

_POLY_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_MASK_RE = re.compile(r"^0x[0-9a-fA-F]{4}\.{3}[0-9a-fA-F]{5}$")  # e.g. 0x99d0...Aa67e

_GREEN  = "#3fb950"
_RED    = "#f85149"
_MUTED  = "#8b949e"
_TEXT   = "#c9d1d9"
_CARD   = "#161b22"
_BG     = "#0d1117"
_BORDER = "#30363d"

_AUTO_REFRESH_MS = 5 * 60 * 1000  # 5 minutes
_BACKFILL_START  = 100             # offset after the 2-page main fetch (pages 1-2 = offsets 0-99)


def _mask_address(addr: str) -> str:
    """Return a privacy-safe display version: 0x99d0...Aa67e"""
    return f"{addr[:6]}...{addr[-5:]}"


class _FetchThread(QThread):
    wallet_ok      = Signal(float)
    wallet_err     = Signal(str)
    positions_ok   = Signal(list, list, list)   # (active, resolved, closed)
    positions_err  = Signal(str)
    activity_ok    = Signal(list)
    activity_err   = Signal(str)

    def __init__(self, address: str):
        super().__init__()
        self._address = address

    def run(self) -> None:
        # Step 1: wallet USD value
        try:
            value = fetch_wallet_usd_value(self._address)
            self.wallet_ok.emit(value)
        except WalletLookupError as exc:
            self.wallet_err.emit(str(exc))
            return
        except Exception as exc:
            self.wallet_err.emit(f"Unexpected error: {exc}")
            return

        # Step 2: Polymarket positions
        try:
            active   = fetch_active_positions(self._address)
            resolved = fetch_resolved_positions(self._address)
            closed   = fetch_closed_positions(self._address)
            # A market is either active or resolved — strip resolved markets from active
            # so the same position never appears in both lists simultaneously
            resolved_titles = {p.market for p in resolved}
            active = [p for p in active if p.market not in resolved_titles]
            self.positions_ok.emit(active, resolved, closed)
        except PolymarketLookupError as exc:
            self.positions_err.emit(str(exc))
        except Exception as exc:
            self.positions_err.emit(f"Unexpected error: {exc}")

        # Step 3: activity feed (non-fatal — positions already emitted)
        try:
            activity = fetch_activity(self._address)
            self.activity_ok.emit(activity)
        except PolymarketLookupError as exc:
            self.activity_err.emit(str(exc))
        except Exception as exc:
            self.activity_err.emit(f"Unexpected error: {exc}")


class _BackfillThread(QThread):
    """Fetch remaining pages of closed positions and upsert into the local cache.

    Accepts a start_offset so that pages already present in the cache are skipped —
    the caller passes count_closed_positions_cache() so we never re-fetch history
    that survived from the previous session.
    """
    page_done = Signal()
    done      = Signal()

    def __init__(self, address: str, start_offset: int = _BACKFILL_START):
        super().__init__()
        self._address      = address
        self._start_offset = start_offset

    def run(self) -> None:
        offset = self._start_offset
        while True:
            # Retry each page up to 3 times before aborting.
            # sorted_=False omits sortBy/sortDirection which cause server-side 408
            # timeouts at high offsets on wallets with many closed positions.
            page = None
            last_exc: Exception | None = None
            for attempt in range(3):
                try:
                    page = fetch_closed_positions_page(
                        self._address, offset, sorted_=False
                    )
                    break
                except Exception as exc:
                    last_exc = exc
                    _dlog(
                        "backfill",
                        "closed page offset=%d attempt=%d/3 failed: %s",
                        offset, attempt + 1, exc,
                    )
                    if attempt < 2:
                        self.msleep(3000)

            if page is None:
                _dlog(
                    "backfill",
                    "closed backfill aborted at offset=%d — all retries failed, last: %s",
                    offset, last_exc,
                )
                break

            if not page:
                _dlog("backfill", "closed offset=%d: empty page — API exhausted", offset)
                break

            try:
                upsert_closed_positions_cache(page, self._address)
                _dlog("backfill", "closed offset=%d  inserted=%d", offset, len(page))
                self.page_done.emit()
            except Exception as exc:
                _dlog("backfill", "closed persist error at offset=%d: %s", offset, exc)

            if len(page) < 50:
                _dlog(
                    "backfill",
                    "closed offset=%d: partial page (%d rows) — done",
                    offset, len(page),
                )
                break
            offset += len(page)
            self.msleep(1000)   # 1 s between pages (was 500 ms)
        self.done.emit()


class _ActivityBackfillThread(QThread):
    """Fetch older pages of activity history and persist to the SQLite cache.

    Starts at start_offset (= current cache row count) so that pages already
    persisted from prior sessions are not re-fetched.  Runs until the API
    returns an empty or partial page, signalling the end of the history.
    """
    page_done = Signal(int, int)  # (rows_inserted, total_in_cache)
    done      = Signal()

    def __init__(self, address: str, start_offset: int):
        super().__init__()
        self._address      = address
        self._start_offset = start_offset

    def run(self) -> None:
        offset = self._start_offset
        while True:
            try:
                page = fetch_activity_page(self._address, offset)
            except Exception as exc:
                _dlog("activity_backfill",
                      "offset=%d: fetch failed — %s — stopping backfill", offset, exc)
                break
            if not page:
                _dlog("activity_backfill", "offset=%d: empty page — API exhausted", offset)
                break
            before = count_activity_cache(self._address)
            try:
                upsert_activity_cache(self._address, page)
            except Exception as exc:
                _dlog("activity_backfill",
                      "offset=%d: persist failed — %s — stopping backfill", offset, exc)
                break
            after    = count_activity_cache(self._address)
            inserted = after - before
            _dlog(
                "activity_backfill",
                "offset=%d  page=%d  inserted=%d  deduped=%d  total=%d",
                offset, len(page), inserted, len(page) - inserted, after,
            )
            self.page_done.emit(inserted, after)
            if len(page) < 100:
                _dlog("activity_backfill", "offset=%d: partial page (%d rows) — done",
                      offset, len(page))
                break
            offset += len(page)
            self.msleep(500)
        self.done.emit()


class _ActivityPageThread(QThread):
    """Fetch one additional page of activity for the infinite-scroll load-more."""
    done = Signal(list)
    err  = Signal(str)

    def __init__(self, address: str, offset: int):
        super().__init__()
        self._address = address
        self._offset  = offset

    def run(self) -> None:
        try:
            page = fetch_activity_page(self._address, self._offset)
            self.done.emit(page)
        except PolymarketLookupError as exc:
            self.err.emit(str(exc))
        except Exception as exc:
            self.err.emit(f"Unexpected error: {exc}")


class _ClosedPageThread(QThread):
    """Fetch one additional page of closed positions for the infinite-scroll load-more."""
    done = Signal(list)
    err  = Signal(str)

    def __init__(self, address: str, offset: int, sorted_: bool = False):
        super().__init__()
        self._address = address
        self._offset  = offset
        self._sorted  = sorted_

    def run(self) -> None:
        try:
            page = fetch_closed_positions_page(self._address, self._offset, sorted_=self._sorted)
            self.done.emit(page)
        except PolymarketLookupError as exc:
            self.err.emit(str(exc))
        except Exception as exc:
            self.err.emit(f"Unexpected error: {exc}")


class WalletPanel(QWidget):
    """
    Read-only wallet panel.

    Signals:
      wallet_value_changed(float)          — new USD wallet balance
      positions_fetched(list, list, list)  — (active, resolved, closed positions)
      activity_fetched(list)               — recent activity records

    Never requests private keys, seed phrases, or wallet permissions.
    """

    wallet_value_changed   = Signal(float)
    wallet_address_changed = Signal(str)         # emitted when the wallet address changes
    positions_fetched      = Signal(list, list, list)  # (active, resolved, closed)
    activity_fetched       = Signal(list)
    closed_cache_updated   = Signal(list)        # full closed history after backfill completes
    more_closed_fetched    = Signal(list)        # next page for closed positions scroll-load
    more_activity_fetched  = Signal(list)        # next page for activity infinite-scroll

    def __init__(self):
        super().__init__()
        self._thread: _FetchThread | None = None
        self._backfill: _BackfillThread | None = None
        self._activity_backfill: _ActivityBackfillThread | None = None
        self._activity_page_thread: _ActivityPageThread | None = None
        self._closed_page_thread: _ClosedPageThread | None = None
        self._current_value      = 0.0
        self._pending_value      = 0.0
        self._full_address       = ""
        self._confirmed_address  = ""   # address of the last *successful* wallet fetch
        self._has_fetched        = False
        self._positions_ok       = False

        init_db()
        self._build_ui()
        self._load_last_wallet()

        self._timer = QTimer(self)
        self._timer.setInterval(_AUTO_REFRESH_MS)
        self._timer.timeout.connect(self._on_timer_tick)

    def _build_ui(self) -> None:
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background-color: {_CARD}; border: 1px solid {_BORDER}; border-radius: 6px; }}"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)

        vbox = QVBoxLayout(frame)
        vbox.setContentsMargins(14, 10, 14, 12)
        vbox.setSpacing(8)

        # Header
        title = QLabel("WALLET")
        title.setStyleSheet(
            f"color: {_MUTED}; font-size: 11px; font-weight: 600; letter-spacing: 0.8px;"
            f" border: none; background: transparent;"
        )
        vbox.addWidget(title)

        # Address input row
        addr_row = QHBoxLayout()
        addr_row.setSpacing(8)

        self._addr_input = QLineEdit()
        self._addr_input.setPlaceholderText("Enter Polygon wallet address  (0x...)")
        self._addr_input.setStyleSheet(
            f"background-color: {_BG}; border: 1px solid {_BORDER}; border-radius: 4px;"
            f" color: {_TEXT}; padding: 6px 10px; font-size: 13px;"
        )
        self._fetch_btn = QPushButton("Fetch Wallet Value")
        self._fetch_btn.setStyleSheet(
            f"background-color: #21262d; border: 1px solid {_BORDER}; border-radius: 4px;"
            f" color: {_TEXT}; padding: 6px 14px; font-size: 13px;"
            f" min-width: 148px;"
        )
        self._fetch_btn.clicked.connect(self._on_fetch)

        addr_row.addWidget(self._addr_input, 1)
        addr_row.addWidget(self._fetch_btn)
        vbox.addLayout(addr_row)

        # Bottom row: status | auto-refresh checkbox | last-updated
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(16)

        self._status = QLabel("Enter your Polygon wallet address and click Fetch.")
        self._status.setStyleSheet(
            f"color: {_MUTED}; font-size: 12px; border: none; background: transparent;"
        )
        bottom_row.addWidget(self._status, 1)

        self._auto_cb = QCheckBox("Auto-refresh every 5 min")
        self._auto_cb.setChecked(False)
        self._auto_cb.setStyleSheet(
            f"color: {_MUTED}; font-size: 12px; border: none; background: transparent;"
        )
        self._auto_cb.toggled.connect(self._on_auto_refresh_toggled)
        bottom_row.addWidget(self._auto_cb)

        self._last_updated = QLabel("")
        self._last_updated.setStyleSheet(
            f"color: {_MUTED}; font-size: 11px; border: none; background: transparent;"
        )
        bottom_row.addWidget(self._last_updated)

        vbox.addLayout(bottom_row)

    # ── Wallet persistence ─────────────────────────────────────────────────

    def _load_last_wallet(self) -> None:
        addr = load_last_wallet()
        if addr and _POLY_RE.match(addr):
            self._full_address = addr
            self._addr_input.setText(_mask_address(addr))
            # Defer auto-fetch until the event loop starts so all signals are connected
            QTimer.singleShot(0, self._on_fetch)

    # ── Auto-refresh ───────────────────────────────────────────────────────

    def _on_auto_refresh_toggled(self, checked: bool) -> None:
        if checked:
            self._timer.start()
        else:
            self._timer.stop()

    def _on_timer_tick(self) -> None:
        if self._full_address and not (self._thread and self._thread.isRunning()):
            self._on_fetch()

    # ── Fetch flow ─────────────────────────────────────────────────────────

    def _on_fetch(self) -> None:
        raw = self._addr_input.text().strip()
        address = self._full_address if _MASK_RE.match(raw) else raw
        if not _POLY_RE.match(address):
            self._set_status("Invalid address — must be 0x followed by 40 hex characters.", _RED)
            return
        if self._thread and self._thread.isRunning():
            return
        self._full_address = address
        self._positions_ok = False
        self._fetch_btn.setEnabled(False)
        self._fetch_btn.setText("Fetching…")
        self._set_status("Fetching wallet value and positions…", _MUTED)

        self._thread = _FetchThread(address)
        self._thread.wallet_ok.connect(self._on_wallet_ok)
        self._thread.wallet_err.connect(self._on_wallet_err)
        self._thread.positions_ok.connect(self._on_positions_ok)
        self._thread.positions_err.connect(self._on_positions_err)
        self._thread.activity_ok.connect(self._on_activity_ok)
        self._thread.finished.connect(self._on_fetch_done)
        self._thread.start()

    def _on_wallet_ok(self, value: float) -> None:
        self._has_fetched   = True
        self._current_value = value
        self._pending_value = value
        self._addr_input.setText(_mask_address(self._full_address))
        self._set_status(f"Wallet: ${value:,.2f}  ·  Loading positions…", _MUTED)
        if self._full_address != self._confirmed_address:
            self._confirmed_address = self._full_address
            self.wallet_address_changed.emit(self._full_address)
        self.wallet_value_changed.emit(value)

    def _on_wallet_err(self, msg: str) -> None:
        self._set_status(f"Lookup failed: {msg}", _RED)

    def _on_positions_ok(self, active: list, resolved: list, closed: list) -> None:
        self._positions_ok = True
        self._set_status(
            f"Wallet: ${self._pending_value:,.2f}  ·  {len(active)} active"
            f"  ·  {len(resolved)} resolved",
            _TEXT,
        )
        addr = self._full_address
        try:
            upsert_closed_positions_cache(closed, addr)
            save_active_positions_cache(addr, active)
            save_resolved_positions_cache(addr, resolved)
        except Exception:
            pass
        self.positions_fetched.emit(active, resolved, closed)

    def _on_positions_err(self, msg: str) -> None:
        self._set_status(
            f"Wallet: ${self._pending_value:,.2f}  ·  Positions unavailable: {msg}",
            _RED,
        )

    def _on_fetch_done(self) -> None:
        self._fetch_btn.setEnabled(True)
        self._fetch_btn.setText("Refresh" if self._has_fetched else "Fetch Wallet Value")
        now = datetime.now().strftime("%H:%M:%S")
        self._last_updated.setText(f"Last updated {now}")
        save_last_wallet(self._full_address)
        if self._positions_ok:
            self._start_backfill()

    def _start_backfill(self) -> None:
        if self._backfill and self._backfill.isRunning():
            return
        # Start from the current cache size so already-persisted pages are skipped
        cached_count = count_closed_positions_cache(self._full_address)
        start_offset = max(_BACKFILL_START, cached_count)
        _dlog("backfill", "starting closed backfill at offset %d (cache has %d)",
              start_offset, cached_count)
        self._backfill = _BackfillThread(self._full_address, start_offset)
        self._backfill.page_done.connect(self._on_backfill_page_done)
        self._backfill.done.connect(self._on_backfill_done)
        self._backfill.start()

    def _on_activity_ok(self, activity: list) -> None:
        try:
            upsert_activity_cache(self._full_address, activity)
            _dlog("cache", "activity: upserted %d rows — total in cache: %d",
                  len(activity), count_activity_cache(self._full_address))
        except Exception:
            pass
        self.activity_fetched.emit(activity)
        self._start_activity_backfill()

    def _start_activity_backfill(self) -> None:
        if self._activity_backfill and self._activity_backfill.isRunning():
            return
        start_offset = count_activity_cache(self._full_address)
        if start_offset == 0:
            return
        _dlog("activity_backfill", "starting at offset %d", start_offset)
        self._activity_backfill = _ActivityBackfillThread(self._full_address, start_offset)
        self._activity_backfill.done.connect(self._on_activity_backfill_done)
        self._activity_backfill.start()

    def _on_activity_backfill_done(self) -> None:
        total = count_activity_cache(self._full_address)
        _dlog("activity_backfill", "done — %d total activity rows in cache", total)

    def _on_backfill_page_done(self) -> None:
        """After each backfill page: reload ALL cached rows from DB and push to UI.

        Uses load_all_closed_for_wallet (no row cap) so the full history is emitted,
        not just the first 2000 rows.
        """
        try:
            all_closed = load_all_closed_for_wallet(self._full_address)
            _dlog("backfill", "page done — %d total in cache", len(all_closed))
            self.closed_cache_updated.emit(all_closed)
        except Exception as exc:
            _dlog("backfill", "ERROR in _on_backfill_page_done: %s", exc)

    def _on_backfill_done(self) -> None:
        """Final reload once all backfill pages are complete."""
        try:
            all_closed = load_all_closed_for_wallet(self._full_address)
            _dlog("backfill", "done — %d total closed in cache", len(all_closed))
            self.closed_cache_updated.emit(all_closed)
        except Exception as exc:
            _dlog("backfill", "ERROR in _on_backfill_done: %s", exc)

    def _set_status(self, text: str, color: str) -> None:
        weight = "600" if color == _GREEN else "normal"
        self._status.setText(text)
        self._status.setStyleSheet(
            f"color: {color}; font-size: 12px; font-weight: {weight};"
            f" border: none; background: transparent;"
        )

    # ── Public ─────────────────────────────────────────────────────────────

    def current_value(self) -> float:
        return self._current_value

    def request_refresh(self) -> None:
        """Trigger a refresh programmatically (e.g. from another tab's Refresh button)."""
        if self._full_address and not (self._thread and self._thread.isRunning()):
            self._on_fetch()

    def fetch_activity_page(self, offset: int) -> None:
        """Fetch the next activity page at offset — cache-first, API on cache miss."""
        if not self._full_address:
            return
        # Try the local SQLite cache first (synchronous, no network latency).
        # The cache is ordered newest-first, matching the UI's in-memory order, so
        # OFFSET=len(ui_rows) consistently yields the next older page.
        try:
            cached = load_activity_cache_page(self._full_address, offset, limit=100)
            if cached:
                _dlog("cache", "activity page offset=%d: %d rows from cache", offset, len(cached))
                self.more_activity_fetched.emit(cached)
                return
        except Exception:
            pass
        # Cache miss — fetch from API in background thread and persist the result.
        if self._activity_page_thread and self._activity_page_thread.isRunning():
            return
        _dlog("cache", "activity page offset=%d: cache miss — fetching from API", offset)
        self._activity_page_thread = _ActivityPageThread(self._full_address, offset)
        self._activity_page_thread.done.connect(self._on_activity_page_done)
        self._activity_page_thread.start()

    def _on_activity_page_done(self, page: list) -> None:
        """Persist scroll-loaded activity to SQLite before forwarding to the UI."""
        try:
            upsert_activity_cache(self._full_address, page)
            _dlog("cache", "persisted %d scroll-loaded activity rows", len(page))
        except Exception:
            pass
        self.more_activity_fetched.emit(page)

    def fetch_closed_page(self, offset: int) -> None:
        """Fetch the next closed positions page at offset — cache-first, API on cache miss."""
        if not self._full_address:
            return
        try:
            cached = load_closed_positions_cache_page(self._full_address, offset, limit=50)
            if cached:
                _dlog("cache", "closed page offset=%d: %d rows from cache", offset, len(cached))
                self.more_closed_fetched.emit(cached)
                return
        except Exception:
            pass
        if self._closed_page_thread and self._closed_page_thread.isRunning():
            return
        _dlog("cache", "closed page offset=%d: cache miss — fetching from API", offset)
        # sorted_=False: omit sortBy/sortDirection to avoid server-side 408 timeouts
        # at high offsets; scroll-loaded rows are deduplicated on insert anyway.
        self._closed_page_thread = _ClosedPageThread(self._full_address, offset, sorted_=False)
        self._closed_page_thread.done.connect(self._on_closed_page_done)
        self._closed_page_thread.start()

    def _on_closed_page_done(self, page: list) -> None:
        """Persist scroll-loaded closed positions to SQLite before forwarding to the UI."""
        before = count_closed_positions_cache(self._full_address)
        try:
            upsert_closed_positions_cache(page, self._full_address)
            after = count_closed_positions_cache(self._full_address)
            _dlog("cache", "persisted %d scroll-loaded closed position rows", len(page))
        except Exception as exc:
            _dlog("cache", "ERROR: failed to persist %d scroll-loaded closed positions: %s",
                  len(page), exc)
        self.more_closed_fetched.emit(page)
