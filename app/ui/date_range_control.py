"""Combined preset + custom date-range control for TradeLedger analytics tabs.

Layout:
  [1D][1W][1M][1Y][YTD][All][Custom]
  From: [date] To: [date] [Apply] [Clear]   ← inline panel, shown when Custom active

Emits ``range_changed(DateRangeSelection)`` on every confirmed change:
  - clicking a preset emits immediately
  - clicking Custom reveals the date panel (no emit until Apply)
  - Apply emits the custom range
  - Clear hides the panel and emits All
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.chart_ranges import RANGE_LABELS
from app.services.date_range import DateRangeSelection

_BTN_STYLE = (
    "QPushButton {"
    "  background-color: #21262d; border: 1px solid #30363d;"
    "  border-radius: 3px; color: #8b949e;"
    "  padding: 2px 8px; font-size: 11px; min-width: 28px;"
    "}"
    "QPushButton:checked {"
    "  background-color: #1f3a5f; border: 1px solid #58a6ff; color: #58a6ff;"
    "}"
    "QPushButton:hover { color: #c9d1d9; }"
)

_BTN_APPLY = (
    "QPushButton {"
    "  background-color: #1f6feb; border: 1px solid #388bfd; border-radius: 3px;"
    "  color: #ffffff; padding: 2px 10px; font-size: 11px;"
    "}"
    "QPushButton:hover { background-color: #388bfd; }"
)

_BTN_CLEAR = (
    "QPushButton {"
    "  background-color: #21262d; border: 1px solid #30363d; border-radius: 3px;"
    "  color: #8b949e; padding: 2px 10px; font-size: 11px;"
    "}"
    "QPushButton:hover { color: #c9d1d9; }"
)

_LABEL_STYLE = "color: #8b949e; font-size: 11px;"

_DATE_EDIT_STYLE = (
    "QDateEdit {"
    "  background-color: #21262d; border: 1px solid #30363d;"
    "  border-radius: 3px; color: #c9d1d9; padding: 2px 6px; font-size: 11px;"
    "}"
    "QDateEdit:focus { border-color: #58a6ff; }"
    "QDateEdit::drop-down { border: none; width: 18px; }"
)

_CALENDAR_STYLE = """
QCalendarWidget {
    background-color: #161b22;
    color: #c9d1d9;
    font-size: 11px;
}
QCalendarWidget QWidget {
    background-color: #161b22;
    alternate-background-color: #21262d;
    color: #c9d1d9;
}
QCalendarWidget QAbstractItemView:enabled {
    background-color: #0d1117;
    color: #c9d1d9;
    selection-background-color: #1f6feb;
    selection-color: #ffffff;
    border: none;
}
QCalendarWidget QAbstractItemView:disabled {
    color: #484f58;
}
QCalendarWidget QToolButton {
    background-color: #21262d;
    color: #c9d1d9;
    border: none;
    border-radius: 3px;
    padding: 2px 4px;
    font-size: 11px;
}
QCalendarWidget QToolButton:hover {
    background-color: #30363d;
}
QCalendarWidget QMenu {
    background-color: #161b22;
    color: #c9d1d9;
    border: 1px solid #30363d;
}
QCalendarWidget #qt_calendar_navigationbar {
    background-color: #21262d;
    padding: 4px;
    border-bottom: 1px solid #30363d;
}
QCalendarWidget QSpinBox {
    background-color: #21262d;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 3px;
    padding: 1px 3px;
}
"""


def _make_date_edit(default_qdate: QDate) -> QDateEdit:
    edit = QDateEdit()
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("yyyy-MM-dd")
    edit.setDate(default_qdate)
    edit.setStyleSheet(_DATE_EDIT_STYLE)
    cal = edit.calendarWidget()
    if cal is not None:
        cal.setStyleSheet(_CALENDAR_STYLE)
    return edit


class DateRangeControl(QWidget):
    """Preset buttons row + collapsible custom From/To date panel.

    Emits ``range_changed(DateRangeSelection)`` whenever the active range
    changes (preset click or custom Apply/Clear).
    """
    range_changed = Signal(object)   # emits DateRangeSelection

    def __init__(self, default: str = "all", align: str = "right", parent=None):
        super().__init__(parent)
        self._selection = DateRangeSelection.preset_range(default.lower())
        self._align_left = align.lower() == "left"
        self._build_ui()

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(3)

        # ── Preset + Custom button row ─────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(4)
        if not self._align_left:
            btn_row.addStretch()

        self._preset_btns: dict[str, QPushButton] = {}
        for key, label in RANGE_LABELS.items():
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(key == self._selection.preset)
            btn.setStyleSheet(_BTN_STYLE)
            btn.clicked.connect(lambda _c, k=key: self._on_preset(k))
            self._preset_btns[key] = btn
            btn_row.addWidget(btn)

        self._custom_btn = QPushButton("Custom")
        self._custom_btn.setCheckable(True)
        self._custom_btn.setChecked(False)
        self._custom_btn.setStyleSheet(_BTN_STYLE)
        self._custom_btn.clicked.connect(self._toggle_custom_panel)
        btn_row.addWidget(self._custom_btn)

        if self._align_left:
            btn_row.addStretch()

        outer.addLayout(btn_row)

        # ── Custom date panel (hidden by default) ──────────────────────────
        self._custom_panel = QWidget()
        panel_row = QHBoxLayout(self._custom_panel)
        panel_row.setContentsMargins(0, 0, 0, 0)
        panel_row.setSpacing(6)
        if not self._align_left:
            panel_row.addStretch()

        panel_row.addWidget(QLabel("From:", styleSheet=_LABEL_STYLE))
        self._from_edit = _make_date_edit(QDate.currentDate().addDays(-7))
        panel_row.addWidget(self._from_edit)

        panel_row.addWidget(QLabel("To:", styleSheet=_LABEL_STYLE))
        self._to_edit = _make_date_edit(QDate.currentDate())
        panel_row.addWidget(self._to_edit)

        apply_btn = QPushButton("Apply")
        apply_btn.setStyleSheet(_BTN_APPLY)
        apply_btn.clicked.connect(self._on_apply)
        panel_row.addWidget(apply_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.setStyleSheet(_BTN_CLEAR)
        clear_btn.clicked.connect(self._on_clear)
        panel_row.addWidget(clear_btn)

        if self._align_left:
            panel_row.addStretch()

        self._custom_panel.setVisible(False)
        outer.addWidget(self._custom_panel)

    # ── Slots ──────────────────────────────────────────────────────────────

    def _on_preset(self, key: str) -> None:
        self._custom_panel.setVisible(False)
        self._custom_btn.setChecked(False)
        for k, btn in self._preset_btns.items():
            btn.setChecked(k == key)
        self._selection = DateRangeSelection.preset_range(key)
        self.range_changed.emit(self._selection)

    def _toggle_custom_panel(self) -> None:
        """Show the custom panel; deselect preset buttons."""
        for btn in self._preset_btns.values():
            btn.setChecked(False)
        self._custom_btn.setChecked(True)
        self._custom_panel.setVisible(not self._custom_panel.isVisible())

    def _on_apply(self) -> None:
        qf = self._from_edit.date()
        qt = self._to_edit.date()
        start = date(qf.year(), qf.month(), qf.day())
        end   = date(qt.year(), qt.month(), qt.day())
        if end < start:
            end = start
        self._selection = DateRangeSelection.custom_range(start, end)
        self.range_changed.emit(self._selection)

    def _on_clear(self) -> None:
        self._custom_panel.setVisible(False)
        self._on_preset("all")

    # ── Public ─────────────────────────────────────────────────────────────

    def current(self) -> DateRangeSelection:
        """Return the currently active DateRangeSelection."""
        return self._selection
