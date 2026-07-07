from typing import List, Tuple

import matplotlib
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from app.services.date_range import DateRangeSelection, filter_snapshots_by_selection
from app.ui.date_range_control import DateRangeControl

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

_DEFAULT_SELECTION = DateRangeSelection.preset_range("all")


def _usd_fmt(x, _):
    if abs(x) >= 1000:
        return f"${x/1000:.1f}k"
    return f"${x:.0f}"


class TotalValueChartWidget(QWidget):
    """
    Total Tracked Value over time chart with 1D/1W/1M/1Y/YTD/All/Custom range control.

    Pass show_range_buttons=False to hide the range controls
    (used in the Overview tab where space is tight).

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
        self._selection          = _DEFAULT_SELECTION
        self._figsize            = figsize
        self._show_range_buttons = show_range_buttons
        self._build_ui()
        self._redraw()

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        if self._show_range_buttons:
            self._range_ctrl = DateRangeControl(default="all")
            self._range_ctrl.range_changed.connect(self._on_range)
            layout.addWidget(self._range_ctrl)

        fig = Figure(figsize=self._figsize, tight_layout=True)
        self._canvas = FigureCanvas(fig)
        self._canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._ax = fig.add_subplot(111)
        layout.addWidget(self._canvas)

    # ── Slots ──────────────────────────────────────────────────────────────

    def _on_range(self, selection: DateRangeSelection) -> None:
        self._selection = selection
        self._redraw()

    # ── Public ─────────────────────────────────────────────────────────────

    def update_snapshots(self, snapshots: List[dict]) -> None:
        self._all_snapshots = snapshots
        self._redraw()

    # ── Drawing ────────────────────────────────────────────────────────────

    def _redraw(self) -> None:
        filtered = filter_snapshots_by_selection(self._all_snapshots, self._selection)
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
                if not self._selection.is_all()
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
            v = values[0]
            pad = max(v * 0.04, 1.0)
            ax.set_ylim(v - pad * 0.6, v + pad * 1.2)
        else:
            ax.plot(dates, values, color=_LINE_COLOR, linewidth=2)
            ax.fill_between(dates, values, alpha=0.15, color=_FILL_COLOR)
            mn, mx   = min(values), max(values)
            spread   = max(mx - mn, max(mx * 0.005, 1.0))
            ax.set_ylim(mn - spread * 0.3, mx + spread * 0.5)

        tick_step = max(1, len(dates) // 6)
        ax.set_xticks(dates[::tick_step])
        ax.set_xticklabels(
            [d[:10] for d in dates[::tick_step]],
            rotation=30, ha="right", fontsize=8,
        )
        ax.yaxis.set_tick_params(labelsize=8)
