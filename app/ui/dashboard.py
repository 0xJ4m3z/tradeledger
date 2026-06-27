from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

_CARD = """
QFrame {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 6px;
}
"""
_TITLE = "color: #8b949e; font-size: 11px; font-weight: 600; letter-spacing: 0.8px;"
_VAL_NEUTRAL = "color: #c9d1d9; font-size: 22px; font-weight: 700;"
_VAL_GREEN   = "color: #3fb950; font-size: 22px; font-weight: 700;"
_VAL_RED     = "color: #f85149; font-size: 22px; font-weight: 700;"
_VAL_BLUE    = "color: #58a6ff; font-size: 22px; font-weight: 700;"


def _pnl_style(val: float) -> str:
    if val > 0:
        return _VAL_GREEN
    if val < 0:
        return _VAL_RED
    return _VAL_NEUTRAL


def _fmt(val: float) -> str:
    return f"${val:,.2f}"


def _card(title: str, value: str, val_style: str) -> QFrame:
    frame = QFrame()
    frame.setStyleSheet(_CARD)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(8)

    t = QLabel(title.upper())
    t.setStyleSheet(_TITLE)

    v = QLabel(value)
    v.setStyleSheet(val_style)
    v.setAlignment(Qt.AlignmentFlag.AlignLeft)

    layout.addWidget(t)
    layout.addWidget(v)
    return frame


class DashboardWidget(QWidget):
    def __init__(self, metrics: dict):
        super().__init__()
        grid = QGridLayout(self)
        grid.setContentsMargins(20, 20, 20, 20)
        grid.setSpacing(14)

        cards = [
            ("Active Positions Value", _fmt(metrics["active_positions_value"]), _VAL_BLUE),
            ("Realized P/L",           _fmt(metrics["realized_pnl"]),           _pnl_style(metrics["realized_pnl"])),
            ("Unrealized P/L",         _fmt(metrics["unrealized_pnl"]),         _pnl_style(metrics["unrealized_pnl"])),
            ("Total Estimated Value",  _fmt(metrics["total_estimated_value"]),  _VAL_NEUTRAL),
            ("Win Count",              str(metrics["win_count"]),               _VAL_GREEN),
            ("Loss Count",             str(metrics["loss_count"]),              _VAL_RED),
            ("Largest Win",            _fmt(metrics["largest_win"]),            _VAL_GREEN),
            ("Largest Loss",           _fmt(metrics["largest_loss"]),           _VAL_RED),
        ]

        for i, (title, value, style) in enumerate(cards):
            row, col = divmod(i, 4)
            grid.addWidget(_card(title, value, style), row, col)

        for col in range(4):
            grid.setColumnStretch(col, 1)
        grid.setRowStretch(grid.rowCount(), 1)
