from typing import List, Tuple

import matplotlib
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from app.services.chart_ranges import _DEFAULT_RANGE, _RANGES, filter_snapshots_by_range  # noqa: F401

matplotlib.rcParams.update({
    "axes.facecolor":    "#0d1117",
    "figure.facecolor":  "#0d1117",
    "axes.edgecolor":    "#30363d",
    "axes.labelcolor":   "#8b949e",
    "xtick.color":       "#8b949e",
    "ytick.color":       "#8b949e",
    "text.color":        "#c9d1d9",
    "grid.color":        "#21262d",
    "grid.linestyle":    "--",
    "grid.linewidth":    0.6,
})

_LINE_COLOR = "#58a6ff"
_FILL_COLOR = "#1f3a5f"

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


def _usd_fmt(x, _):
    if abs(x) >= 1000:
        return f"${x/1000:.1f}k"
    return f"${x:.0f}"


class TotalValueChartWidget(QWidget):
    """
    Total Tracked Value over time chart.

    Pass show_range_buttons=False to hide the 1D/1W/1M/All controls
    (used in the Overview tab where space is tight and range switching
    is handled by the full-size Total Tracked Value tab).

    Public interface:
      update_snapshots(snapshots)  — refresh with new snapshot list
    """

    def __init__(
        self,
        snapshots: List[dict],
        figsize: Tuple[float, float] = (5, 2.8),
        show_range_buttons: bool = True,
    ):
        super().__init__()
        self._all_snapshots      = snapshots
        self._range_key          = _DEFAULT_RANGE
        self._figsize            = figsize
        self._show_range_buttons = show_range_buttons
        self._build_ui()
        self._redraw()

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._range_btns: dict[str, QPushButton] = {}

        if self._show_range_buttons:
            btn_row = QHBoxLayout()
            btn_row.addStretch()
            for key in _RANGES:
                btn = QPushButton(key)
                btn.setCheckable(True)
                btn.setChecked(key == _DEFAULT_RANGE)
                btn.setStyleSheet(_BTN_STYLE)
                btn.clicked.connect(lambda _checked, k=key: self._on_range(k))
                self._range_btns[key] = btn
                btn_row.addWidget(btn)
            layout.addLayout(btn_row)

        # Matplotlib canvas
        fig = Figure(figsize=self._figsize, tight_layout=True)
        self._canvas = FigureCanvas(fig)
        self._canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._ax = fig.add_subplot(111)
        layout.addWidget(self._canvas)

    # ── Slots ──────────────────────────────────────────────────────────────

    def _on_range(self, key: str) -> None:
        self._range_key = key
        for k, btn in self._range_btns.items():
            btn.setChecked(k == key)
        self._redraw()

    # ── Public ─────────────────────────────────────────────────────────────

    def update_snapshots(self, snapshots: List[dict]) -> None:
        self._all_snapshots = snapshots
        self._redraw()

    # ── Drawing ────────────────────────────────────────────────────────────

    def _redraw(self) -> None:
        filtered = filter_snapshots_by_range(self._all_snapshots, self._range_key)
        self._ax.clear()
        self._plot(filtered)
        self._canvas.draw()

    def _plot(self, snapshots: List[dict]) -> None:
        ax = self._ax
        ax.set_title("Total Tracked Value Over Time", color="#c9d1d9",
                     fontsize=11, fontweight="600", pad=8)
        ax.yaxis.set_major_formatter(FuncFormatter(_usd_fmt))
        ax.grid(True, axis="y")

        if not snapshots:
            msg = (
                "No data for this range."
                if self._range_key != "All"
                else "No history yet.\nEnter a wallet value to start tracking."
            )
            ax.text(0.5, 0.5, msg, ha="center", va="center",
                    color="#8b949e", fontsize=10, transform=ax.transAxes)
            ax.set_xticks([])
            ax.set_yticks([])
            return

        dates  = [s["captured_at"] for s in snapshots]
        values = [s["total_tracked_value"] for s in snapshots]

        if len(dates) == 1:
            ax.plot(dates, values, "o", color=_LINE_COLOR, markersize=7)
        else:
            ax.plot(dates, values, color=_LINE_COLOR, linewidth=2)
            ax.fill_between(dates, values, alpha=0.15, color=_FILL_COLOR)

        tick_step = max(1, len(dates) // 6)
        ax.set_xticks(dates[::tick_step])
        ax.set_xticklabels(
            [d[:10] for d in dates[::tick_step]],
            rotation=30, ha="right", fontsize=8,
        )
        ax.yaxis.set_tick_params(labelsize=8)
