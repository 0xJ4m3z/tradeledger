"""Daily realized P/L bar chart for the Overview panel."""

from collections import defaultdict
from datetime import date
from typing import List

import matplotlib
matplotlib.use("QtAgg")

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from app.models import ResolvedPosition
from app.services.pnl_today import filter_closed_by_range

_BG    = "#0d1117"
_MUTED = "#8b949e"
_GREEN = "#3fb950"
_RED   = "#f85149"


class PnlChartWidget(QWidget):
    """Bar chart of daily realized P/L grouped by resolved_date."""

    def __init__(
        self,
        closed: List[ResolvedPosition],
        range_: str = "1d",
        figsize: tuple = (6, 3),
    ):
        super().__init__()
        self._closed = list(closed)
        self._range  = range_

        self._fig, self._ax = plt.subplots(figsize=figsize)
        self._fig.patch.set_facecolor(_BG)
        self._ax.set_facecolor(_BG)

        self._canvas = FigureCanvasQTAgg(self._fig)
        self._canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._canvas)

        self._draw()

    def update(self, closed: List[ResolvedPosition], range_: str) -> None:
        self._closed = list(closed)
        self._range  = range_
        self._draw()

    def _draw(self) -> None:
        ax = self._ax
        ax.clear()
        ax.set_facecolor(_BG)

        filtered = filter_closed_by_range(self._closed, self._range)

        daily: dict = defaultdict(float)
        for p in filtered:
            if not p.resolved_date:
                continue
            try:
                d = date.fromisoformat(p.resolved_date[:10])
                daily[d] += p.realized_pnl
            except (ValueError, TypeError):
                pass

        if not daily:
            ax.text(
                0.5, 0.5, "No closed positions",
                transform=ax.transAxes,
                ha="center", va="center",
                color=_MUTED, fontsize=11,
            )
            ax.set_xticks([])
            ax.set_yticks([])
            for spine in ax.spines.values():
                spine.set_visible(False)
            self._canvas.draw_idle()
            return

        dates  = sorted(daily.keys())
        values = [daily[d] for d in dates]
        colors = [_GREEN if v >= 0 else _RED for v in values]

        x = list(range(len(dates)))
        ax.bar(x, values, color=colors, width=0.6, zorder=2)
        ax.axhline(0, color=_MUTED, linewidth=0.5, zorder=1)

        ax.set_xticks(x)
        rotation = 45 if len(dates) > 10 else 0
        ax.set_xticklabels(
            [str(d) for d in dates],
            rotation=rotation,
            ha="right" if rotation else "center",
            color=_MUTED,
            fontsize=8,
        )

        ax.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda v, _: f"${v:+,.0f}" if v != 0 else "$0"
        ))
        ax.tick_params(axis="y", colors=_MUTED, labelsize=8)
        ax.tick_params(axis="x", colors=_MUTED, labelsize=8)

        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.grid(axis="y", color=_MUTED, alpha=0.15, linewidth=0.5, zorder=0)

        self._fig.tight_layout(pad=0.4)
        self._canvas.draw_idle()
