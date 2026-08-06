"""Settings tab — wallet configuration, chart options, export folder, user stream."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.database import load_setting, save_setting
from app.services import credentials as _creds

# ── Palette (matches the rest of the app) ─────────────────────────────────────
_BG     = "#0d1117"
_CARD   = "#161b22"
_BORDER = "#30363d"
_MUTED  = "#8b949e"
_TEXT   = "#c9d1d9"
_BLUE   = "#58a6ff"
_GREEN  = "#3fb950"

_SECTION_HDR = (
    f"color: {_TEXT}; font-size: 14px; font-weight: 600;"
)
_LABEL_S = (
    f"color: {_MUTED}; font-size: 11px; font-weight: 600; letter-spacing: 0.6px;"
)
_CARD_FRAME = (
    f"QFrame {{ background-color: {_CARD}; border: 1px solid {_BORDER};"
    f" border-radius: 6px; }}"
)

# ── Chart style defaults ───────────────────────────────────────────────────────
_LINEWIDTH_OPTIONS = [
    ("Thin",   1.2),
    ("Normal", 1.8),
    ("Bold",   2.5),
]
_FILL_OPTIONS = [
    ("None",   0.0),
    ("Light",  0.12),
    ("Strong", 0.25),
]


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(_SECTION_HDR)
    return lbl


def _field_label(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(_LABEL_S)
    return lbl


def _divider() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"background-color: {_BORDER}; border: none; max-height: 1px;")
    return f


def _option_btn_style(selected: bool) -> str:
    if selected:
        return (
            f"background-color: {_BLUE}; border: 1px solid {_BLUE};"
            f" border-radius: 4px; color: #0d1117; padding: 5px 16px;"
            f" font-size: 12px; font-weight: 600;"
        )
    return (
        f"background-color: #21262d; border: 1px solid {_BORDER};"
        f" border-radius: 4px; color: {_TEXT}; padding: 5px 16px;"
        f" font-size: 12px;"
    )


class SettingsTab(QWidget):
    """Settings panel — displayed as a top-level tab in MainWindow."""

    # Emitted when any chart option changes: (smooth, linewidth, fill_alpha)
    chart_settings_changed = Signal(bool, float, float)

    # Emitted when the credentials file path changes (or is cleared).
    # Recipients call credentials.load_from_file() on the path themselves
    # so credentials are never held inside this widget.
    credentials_file_changed = Signal(str)   # file path, or "" if cleared

    def __init__(self, wallet_panel: QWidget, parent=None):
        super().__init__(parent)

        # Load persisted chart settings
        self._smooth      = load_setting("chart_smooth",     "1") == "1"
        lw_saved          = load_setting("chart_linewidth",  "1.8")
        fa_saved          = load_setting("chart_fill_alpha", "0.12")
        try:
            self._linewidth  = float(lw_saved)
        except ValueError:
            self._linewidth  = 1.8
        try:
            self._fill_alpha = float(fa_saved)
        except ValueError:
            self._fill_alpha = 0.12

        # ── Scroll area wrapper (lets all sections breathe) ────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        _content = QWidget()
        outer = QVBoxLayout(_content)
        outer.setContentsMargins(24, 20, 24, 24)
        outer.setSpacing(20)

        # ── Wallet ─────────────────────────────────────────────────────────────
        outer.addWidget(_section_label("Wallet"))
        wallet_card = QFrame()
        wallet_card.setStyleSheet(_CARD_FRAME)
        wc_layout = QVBoxLayout(wallet_card)
        wc_layout.setContentsMargins(0, 0, 0, 0)
        wc_layout.setSpacing(0)
        wc_layout.addWidget(wallet_panel)
        outer.addWidget(wallet_card)

        outer.addWidget(_divider())

        # ── Live Trade Stream ──────────────────────────────────────────────────
        outer.addWidget(_section_label("Live Trade Stream"))
        outer.addWidget(self._build_stream_card())

        outer.addWidget(_divider())

        # ── Export ─────────────────────────────────────────────────────────────
        outer.addWidget(_section_label("Export"))
        export_card = QFrame()
        export_card.setStyleSheet(_CARD_FRAME)
        ex_layout = QVBoxLayout(export_card)
        ex_layout.setContentsMargins(16, 14, 16, 16)
        ex_layout.setSpacing(8)

        ex_layout.addWidget(_field_label("Default export folder"))

        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)

        self._folder_edit = QLineEdit()
        self._folder_edit.setPlaceholderText("Leave blank to always ask…")
        self._folder_edit.setText(load_setting("export_folder", ""))
        self._folder_edit.setReadOnly(True)
        self._folder_edit.setStyleSheet(
            f"background-color: {_BG}; border: 1px solid {_BORDER}; border-radius: 4px;"
            f" color: {_TEXT}; padding: 6px 10px; font-size: 13px;"
        )

        browse_btn = QPushButton("Browse…")
        browse_btn.setStyleSheet(
            f"background-color: #21262d; border: 1px solid {_BORDER}; border-radius: 4px;"
            f" color: {_TEXT}; padding: 6px 14px; font-size: 13px; min-width: 80px;"
        )
        browse_btn.clicked.connect(self._on_browse_folder)

        clear_btn = QPushButton("Clear")
        clear_btn.setStyleSheet(
            f"background-color: #21262d; border: 1px solid {_BORDER}; border-radius: 4px;"
            f" color: {_MUTED}; padding: 6px 10px; font-size: 13px; min-width: 50px;"
        )
        clear_btn.clicked.connect(self._on_clear_folder)

        folder_row.addWidget(self._folder_edit, 1)
        folder_row.addWidget(browse_btn)
        folder_row.addWidget(clear_btn)
        ex_layout.addLayout(folder_row)
        outer.addWidget(export_card)

        outer.addWidget(_divider())

        # ── Chart ──────────────────────────────────────────────────────────────
        outer.addWidget(_section_label("Chart"))
        chart_card = QFrame()
        chart_card.setStyleSheet(_CARD_FRAME)
        cc_layout = QVBoxLayout(chart_card)
        cc_layout.setContentsMargins(16, 14, 16, 16)
        cc_layout.setSpacing(14)

        # Line style — Smooth / Sharp
        cc_layout.addWidget(_field_label("Line style"))
        style_row = QHBoxLayout()
        style_row.setSpacing(8)
        self._smooth_btn = QPushButton("Smooth")
        self._sharp_btn  = QPushButton("Sharp")
        self._smooth_btn.setFixedHeight(30)
        self._sharp_btn.setFixedHeight(30)
        self._smooth_btn.clicked.connect(lambda: self._set_smooth(True))
        self._sharp_btn.clicked.connect(lambda: self._set_smooth(False))
        style_row.addWidget(self._smooth_btn)
        style_row.addWidget(self._sharp_btn)
        style_row.addStretch(1)
        cc_layout.addLayout(style_row)
        self._refresh_smooth_btns()

        # Line weight
        cc_layout.addWidget(_field_label("Line weight"))
        weight_row = QHBoxLayout()
        weight_row.setSpacing(8)
        self._lw_btns: list[tuple[QPushButton, float]] = []
        for label, val in _LINEWIDTH_OPTIONS:
            btn = QPushButton(label)
            btn.setFixedHeight(30)
            btn.clicked.connect(lambda _=None, v=val: self._set_linewidth(v))
            self._lw_btns.append((btn, val))
            weight_row.addWidget(btn)
        weight_row.addStretch(1)
        cc_layout.addLayout(weight_row)
        self._refresh_lw_btns()

        # Fill opacity
        cc_layout.addWidget(_field_label("Fill opacity"))
        fill_row = QHBoxLayout()
        fill_row.setSpacing(8)
        self._fill_btns: list[tuple[QPushButton, float]] = []
        for label, val in _FILL_OPTIONS:
            btn = QPushButton(label)
            btn.setFixedHeight(30)
            btn.clicked.connect(lambda _=None, v=val: self._set_fill_alpha(v))
            self._fill_btns.append((btn, val))
            fill_row.addWidget(btn)
        fill_row.addStretch(1)
        cc_layout.addLayout(fill_row)
        self._refresh_fill_btns()

        outer.addWidget(chart_card)
        outer.addStretch(1)

        scroll.setWidget(_content)
        tab_layout = QVBoxLayout(self)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(scroll)

    # ── Live Trade Stream (credentials file) ──────────────────────────────────

    def _build_stream_card(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet(_CARD_FRAME)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(8)

        layout.addWidget(_field_label(
            "Credentials file  (.env or .json — needs CLOB_API_KEY, CLOB_API_SECRET, CLOB_API_PASSPHRASE)"
        ))

        # File path row
        file_row = QHBoxLayout()
        file_row.setSpacing(8)

        self._creds_edit = QLineEdit()
        self._creds_edit.setPlaceholderText("Select your .env or credentials.json file…")
        self._creds_edit.setReadOnly(True)
        self._creds_edit.setStyleSheet(
            f"background-color: {_BG}; border: 1px solid {_BORDER}; border-radius: 4px;"
            f" color: {_TEXT}; padding: 6px 10px; font-size: 13px;"
        )

        browse_creds = QPushButton("Browse…")
        browse_creds.setStyleSheet(
            f"background-color: #21262d; border: 1px solid {_BORDER}; border-radius: 4px;"
            f" color: {_TEXT}; padding: 6px 14px; font-size: 13px; min-width: 80px;"
        )
        browse_creds.clicked.connect(self._on_browse_creds)

        clear_creds = QPushButton("Clear")
        clear_creds.setStyleSheet(
            f"background-color: #21262d; border: 1px solid {_BORDER}; border-radius: 4px;"
            f" color: {_MUTED}; padding: 6px 10px; font-size: 13px; min-width: 50px;"
        )
        clear_creds.clicked.connect(self._on_clear_creds)

        file_row.addWidget(self._creds_edit, 1)
        file_row.addWidget(browse_creds)
        file_row.addWidget(clear_creds)
        layout.addLayout(file_row)

        # Validation status label
        self._creds_status = QLabel("")
        self._creds_status.setStyleSheet(f"color: {_MUTED}; font-size: 12px;")
        layout.addWidget(self._creds_status)

        # Load persisted path and show status
        saved_path = load_setting("user_creds_file", "")
        if saved_path:
            self._creds_edit.setText(saved_path)
            self._refresh_creds_status(saved_path)

        return card

    def _on_browse_creds(self) -> None:
        current = self._creds_edit.text()
        start   = os.path.dirname(current) if current else os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Credentials File", start,
            "Env / JSON files (*.env *.json *.txt);;All files (*)"
        )
        if path:
            self._creds_edit.setText(path)
            save_setting("user_creds_file", path)
            self._refresh_creds_status(path)
            self.credentials_file_changed.emit(path)

    def _on_clear_creds(self) -> None:
        self._creds_edit.clear()
        save_setting("user_creds_file", "")
        self._creds_status.setText("")
        self._creds_status.setStyleSheet(f"color: {_MUTED}; font-size: 12px;")
        self.credentials_file_changed.emit("")

    def _refresh_creds_status(self, path: str) -> None:
        ok, msg = _creds.validate_file(path)
        color   = _GREEN if ok else "#f85149"
        self._creds_status.setText(msg)
        self._creds_status.setStyleSheet(f"color: {color}; font-size: 12px;")

    def update_stream_status(self, connected: bool, error: str = "") -> None:
        """Called by Overview to reflect live user-stream status in Settings."""
        if error:
            # Truncate long error messages so they fit the label
            short = error[:100] + "…" if len(error) > 100 else error
            self._creds_status.setText(f"✗  {short}")
            self._creds_status.setStyleSheet("color: #f85149; font-size: 12px;")
        elif connected:
            self._creds_status.setText("✓  Connected — receiving live trade events")
            self._creds_status.setStyleSheet(f"color: {_GREEN}; font-size: 12px;")
        else:
            path = self._creds_edit.text()
            if path:
                ok, _ = _creds.validate_file(path)
                if ok:
                    self._creds_status.setText("○  Connecting…")
                    self._creds_status.setStyleSheet(f"color: {_MUTED}; font-size: 12px;")

    # ── Public — seed from persisted settings on startup ──────────────────────

    def initial_credentials_file(self) -> str:
        """Return the credentials file path saved in DB (may be empty)."""
        return load_setting("user_creds_file", "")

    # ── Export folder ──────────────────────────────────────────────────────────

    def _on_browse_folder(self) -> None:
        current = self._folder_edit.text()
        start   = current if current and os.path.isdir(current) else os.path.expanduser("~")
        folder  = QFileDialog.getExistingDirectory(self, "Select Export Folder", start)
        if folder:
            self._folder_edit.setText(folder)
            save_setting("export_folder", folder)

    def _on_clear_folder(self) -> None:
        self._folder_edit.clear()
        save_setting("export_folder", "")

    # ── Chart style ────────────────────────────────────────────────────────────

    def _emit_chart(self) -> None:
        self.chart_settings_changed.emit(self._smooth, self._linewidth, self._fill_alpha)

    def _set_smooth(self, smooth: bool) -> None:
        self._smooth = smooth
        save_setting("chart_smooth", "1" if smooth else "0")
        self._refresh_smooth_btns()
        self._emit_chart()

    def _set_linewidth(self, val: float) -> None:
        self._linewidth = val
        save_setting("chart_linewidth", str(val))
        self._refresh_lw_btns()
        self._emit_chart()

    def _set_fill_alpha(self, val: float) -> None:
        self._fill_alpha = val
        save_setting("chart_fill_alpha", str(val))
        self._refresh_fill_btns()
        self._emit_chart()

    def _refresh_smooth_btns(self) -> None:
        self._smooth_btn.setStyleSheet(_option_btn_style(self._smooth))
        self._sharp_btn.setStyleSheet(_option_btn_style(not self._smooth))

    def _refresh_lw_btns(self) -> None:
        for btn, val in self._lw_btns:
            btn.setStyleSheet(_option_btn_style(abs(val - self._linewidth) < 0.01))

    def _refresh_fill_btns(self) -> None:
        for btn, val in self._fill_btns:
            btn.setStyleSheet(_option_btn_style(abs(val - self._fill_alpha) < 0.01))

    # ── Public — seed chart from persisted settings on startup ─────────────────

    def initial_chart_style(self) -> tuple[bool, float, float]:
        """Return (smooth, linewidth, fill_alpha) loaded from DB — call once at startup."""
        return self._smooth, self._linewidth, self._fill_alpha
