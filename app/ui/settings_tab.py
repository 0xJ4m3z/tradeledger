"""Settings tab — wallet configuration, chart options, export folder."""
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
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.database import load_setting, save_setting

# ── Palette (matches the rest of the app) ─────────────────────────────────────
_BG     = "#0d1117"
_CARD   = "#161b22"
_BORDER = "#30363d"
_MUTED  = "#8b949e"
_TEXT   = "#c9d1d9"
_BLUE   = "#58a6ff"

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

        outer = QVBoxLayout(self)
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
