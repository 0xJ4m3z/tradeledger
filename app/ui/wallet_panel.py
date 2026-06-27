import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QThread

from app.adapters.wallet_adapter import WalletLookupError, fetch_wallet_usd_value

_POLY_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

_GREEN = "#3fb950"
_RED   = "#f85149"
_MUTED = "#8b949e"
_TEXT  = "#c9d1d9"
_CARD  = "#161b22"
_BG    = "#0d1117"
_BORDER = "#30363d"
_BLUE  = "#58a6ff"


class _FetchThread(QThread):
    succeeded = Signal(float)
    failed = Signal(str)

    def __init__(self, address: str):
        super().__init__()
        self._address = address

    def run(self) -> None:
        try:
            value = fetch_wallet_usd_value(self._address)
            self.succeeded.emit(value)
        except WalletLookupError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Unexpected error: {exc}")


class WalletPanel(QWidget):
    """
    Read-only wallet value panel.

    Emits wallet_value_changed(float) whenever the wallet USD value is
    updated — either via live lookup or manual entry.

    Never requests private keys, seed phrases, or wallet permissions.
    """

    wallet_value_changed = Signal(float)

    def __init__(self):
        super().__init__()
        self._thread: _FetchThread | None = None
        self._current_value = 0.0
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

        # Label
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

        # Status + manual row
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(12)

        self._status = QLabel("No wallet value set — fetch live or enter manually.")
        self._status.setStyleSheet(f"color: {_MUTED}; font-size: 12px; border: none; background: transparent;")
        bottom_row.addWidget(self._status, 1)

        manual_label = QLabel("Manual:")
        manual_label.setStyleSheet(f"color: {_MUTED}; font-size: 12px; border: none; background: transparent;")

        self._manual_input = QLineEdit()
        self._manual_input.setPlaceholderText("0.00")
        self._manual_input.setFixedWidth(90)
        self._manual_input.setStyleSheet(
            f"background-color: {_BG}; border: 1px solid {_BORDER}; border-radius: 4px;"
            f" color: {_TEXT}; padding: 4px 8px; font-size: 13px;"
        )

        set_btn = QPushButton("Set")
        set_btn.setFixedWidth(44)
        set_btn.setStyleSheet(
            f"background-color: #21262d; border: 1px solid {_BORDER}; border-radius: 4px;"
            f" color: {_TEXT}; padding: 4px 8px; font-size: 13px;"
        )
        set_btn.clicked.connect(self._on_set_manual)

        bottom_row.addWidget(manual_label)
        bottom_row.addWidget(self._manual_input)
        bottom_row.addWidget(set_btn)
        vbox.addLayout(bottom_row)

    # ── Slots ──────────────────────────────────────────────────────────────

    def _on_fetch(self) -> None:
        address = self._addr_input.text().strip()
        if not _POLY_RE.match(address):
            self._status.setText("Invalid address — must be 0x followed by 40 hex characters.")
            self._status.setStyleSheet(f"color: {_RED}; font-size: 12px; border: none; background: transparent;")
            return
        self._fetch_btn.setEnabled(False)
        self._fetch_btn.setText("Fetching…")
        self._status.setText("Contacting Polygon RPC…")
        self._status.setStyleSheet(f"color: {_MUTED}; font-size: 12px; border: none; background: transparent;")

        self._thread = _FetchThread(address)
        self._thread.succeeded.connect(self._on_fetch_success)
        self._thread.failed.connect(self._on_fetch_error)
        self._thread.finished.connect(self._on_fetch_done)
        self._thread.start()

    def _on_fetch_success(self, value: float) -> None:
        self._apply_value(value, source="live")

    def _on_fetch_error(self, msg: str) -> None:
        self._status.setText(f"Lookup failed: {msg}")
        self._status.setStyleSheet(f"color: {_RED}; font-size: 12px; border: none; background: transparent;")

    def _on_fetch_done(self) -> None:
        self._fetch_btn.setEnabled(True)
        self._fetch_btn.setText("Fetch Wallet Value")

    def _on_set_manual(self) -> None:
        raw = self._manual_input.text().strip().replace(",", "").replace("$", "")
        try:
            value = float(raw)
            if value < 0:
                raise ValueError
        except ValueError:
            self._status.setText("Enter a valid positive number.")
            self._status.setStyleSheet(f"color: {_RED}; font-size: 12px; border: none; background: transparent;")
            return
        self._apply_value(value, source="manual")

    def _apply_value(self, value: float, source: str) -> None:
        self._current_value = value
        tag = " (manual)" if source == "manual" else ""
        self._status.setText(f"Wallet USD Value: ${value:,.2f}{tag}")
        self._status.setStyleSheet(f"color: {_GREEN}; font-size: 12px; font-weight: 600; border: none; background: transparent;")
        self._manual_input.setText(f"{value:.2f}")
        self.wallet_value_changed.emit(value)

    # ── Public ─────────────────────────────────────────────────────────────

    def current_value(self) -> float:
        return self._current_value
