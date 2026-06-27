import re
from typing import List

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
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
    fetch_closed_positions,
    fetch_redeemable_positions,
)
from app.adapters.wallet_adapter import WalletLookupError, fetch_wallet_usd_value
from app.models import ActivePosition, ResolvedPosition

_POLY_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

_GREEN  = "#3fb950"
_RED    = "#f85149"
_MUTED  = "#8b949e"
_TEXT   = "#c9d1d9"
_CARD   = "#161b22"
_BG     = "#0d1117"
_BORDER = "#30363d"


class _FetchThread(QThread):
    wallet_ok      = Signal(float)
    wallet_err     = Signal(str)
    positions_ok   = Signal(list, list, list)   # (active, redeemable, closed)
    positions_err  = Signal(str)

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

        # Step 2: Polymarket positions (wallet succeeded; run regardless)
        try:
            active     = fetch_active_positions(self._address)
            redeemable = fetch_redeemable_positions(self._address)
            closed     = fetch_closed_positions(self._address)
            self.positions_ok.emit(active, redeemable, closed)
        except PolymarketLookupError as exc:
            self.positions_err.emit(str(exc))
        except Exception as exc:
            self.positions_err.emit(f"Unexpected error: {exc}")


class WalletPanel(QWidget):
    """
    Read-only wallet panel.

    Signals:
      wallet_value_changed(float)       — new USD wallet value
      positions_fetched(list, list)     — (active positions, redeemable positions)

    Never requests private keys, seed phrases, or wallet permissions.
    """

    wallet_value_changed = Signal(float)
    positions_fetched    = Signal(list, list, list)   # (active, redeemable, closed)

    def __init__(self):
        super().__init__()
        self._thread: _FetchThread | None = None
        self._current_value  = 0.0
        self._pending_value  = 0.0   # wallet value buffered until status can be updated
        self._build_ui()

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

        title = QLabel("WALLET  (READ-ONLY · POLYGON)")
        title.setStyleSheet(
            f"color: {_MUTED}; font-size: 11px; font-weight: 600; letter-spacing: 0.8px;"
            f" border: none; background: transparent;"
        )
        vbox.addWidget(title)

        # Address row
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

        # Status row
        self._status = QLabel("Enter your Polygon wallet address and click Fetch.")
        self._status.setStyleSheet(
            f"color: {_MUTED}; font-size: 12px; border: none; background: transparent;"
        )
        vbox.addWidget(self._status)

    # ── Slots ──────────────────────────────────────────────────────────────

    def _on_fetch(self) -> None:
        address = self._addr_input.text().strip()
        if not _POLY_RE.match(address):
            self._set_status("Invalid address — must be 0x followed by 40 hex characters.", _RED)
            return
        self._fetch_btn.setEnabled(False)
        self._fetch_btn.setText("Fetching…")
        self._set_status("Fetching wallet value and positions…", _MUTED)

        self._thread = _FetchThread(address)
        self._thread.wallet_ok.connect(self._on_wallet_ok)
        self._thread.wallet_err.connect(self._on_wallet_err)
        self._thread.positions_ok.connect(self._on_positions_ok)
        self._thread.positions_err.connect(self._on_positions_err)
        self._thread.finished.connect(self._on_fetch_done)
        self._thread.start()

    def _on_wallet_ok(self, value: float) -> None:
        self._current_value = value
        self._pending_value = value
        self._set_status(f"Wallet: ${value:,.2f}  ·  Loading positions…", _MUTED)
        self.wallet_value_changed.emit(value)

    def _on_wallet_err(self, msg: str) -> None:
        self._set_status(f"Lookup failed: {msg}", _RED)

    def _on_positions_ok(self, active: list, redeemable: list, closed: list) -> None:
        self._set_status(
            f"Wallet: ${self._pending_value:,.2f}  ·  {len(active)} active"
            f"  ·  {len(redeemable)} redeemable  ·  {len(closed)} closed",
            _GREEN,
        )
        self.positions_fetched.emit(active, redeemable, closed)

    def _on_positions_err(self, msg: str) -> None:
        self._set_status(
            f"Wallet: ${self._pending_value:,.2f}  ·  Positions unavailable: {msg}",
            _RED,
        )

    def _on_fetch_done(self) -> None:
        self._fetch_btn.setEnabled(True)
        self._fetch_btn.setText("Fetch Wallet Value")

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
