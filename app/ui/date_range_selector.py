"""Reusable date-range filter bar used across TradeLedger tabs.

Emits ``range_changed(str)`` with lowercase range keys:
  '1d', '1w', '1m', '1y', 'ytd', 'all'
"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from app.services.chart_ranges import RANGE_LABELS

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


class DateRangeSelector(QWidget):
    """Horizontal row of range buttons (1D / 1W / 1M / 1Y / YTD / All).

    Emits ``range_changed`` with the selected range key (lowercase).
    """
    range_changed = Signal(str)

    def __init__(self, default: str = "all", parent=None):
        super().__init__(parent)
        self._current = default.lower()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addStretch()
        self._btns: dict[str, QPushButton] = {}
        for key, label in RANGE_LABELS.items():
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(key == self._current)
            btn.setStyleSheet(_BTN_STYLE)
            btn.clicked.connect(lambda _c, k=key: self._on_click(k))
            self._btns[key] = btn
            row.addWidget(btn)

    def _on_click(self, key: str) -> None:
        if key == self._current:
            # Prevent Qt from unchecking the active button on re-click
            self._btns[key].setChecked(True)
            return
        self._current = key
        for k, btn in self._btns.items():
            btn.setChecked(k == key)
        self.range_changed.emit(key)

    def current(self) -> str:
        """Return the currently selected range key (lowercase)."""
        return self._current
