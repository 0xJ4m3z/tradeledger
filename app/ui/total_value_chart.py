from typing import List

import matplotlib
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

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


def _usd_fmt(x, _):
    if abs(x) >= 1000:
        return f"${x/1000:.1f}k"
    return f"${x:.0f}"


class TotalValueChartWidget(FigureCanvas):
    """
    Plots Total Tracked Value over time from wallet snapshot history.
    Shows an empty-state message when no snapshots exist yet.
    """

    def __init__(self, snapshots: List[dict]):
        fig = Figure(figsize=(5, 2.8), tight_layout=True)
        super().__init__(fig)
        self._ax = fig.add_subplot(111)
        self._plot(snapshots)

    def update_snapshots(self, snapshots: List[dict]) -> None:
        self._ax.clear()
        self._plot(snapshots)
        self.draw()

    def _plot(self, snapshots: List[dict]) -> None:
        ax = self._ax
        ax.set_title("Total Tracked Value Over Time", color="#c9d1d9",
                     fontsize=11, fontweight="600", pad=8)
        ax.yaxis.set_major_formatter(FuncFormatter(_usd_fmt))
        ax.grid(True, axis="y")

        if not snapshots:
            ax.text(
                0.5, 0.5,
                "No history yet.\nEnter a wallet value to start tracking.",
                ha="center", va="center", color="#8b949e", fontsize=10,
                transform=ax.transAxes,
            )
            ax.set_xticks([])
            ax.set_yticks([])
            return

        dates  = [s["captured_at"] for s in snapshots]
        values = [s["total_tracked_value"] for s in snapshots]

        if len(dates) == 1:
            # Single point — draw a dot with a label
            ax.plot(dates, values, "o", color=_LINE_COLOR, markersize=7)
        else:
            ax.plot(dates, values, color=_LINE_COLOR, linewidth=2)
            ax.fill_between(dates, values, alpha=0.15, color=_FILL_COLOR)

        # Thin the x-axis labels if many points
        tick_step = max(1, len(dates) // 6)
        ax.set_xticks(dates[::tick_step])
        ax.set_xticklabels(
            [d[:10] for d in dates[::tick_step]],
            rotation=30, ha="right", fontsize=8,
        )
        ax.yaxis.set_tick_params(labelsize=8)
