"""Cumulative realized P/L line chart for the Overview panel.

Shows cumulative realized P/L from closed positions over the selected range.
Starts at $0 at the range boundary and moves with each closed position.

Interactive: hover over the chart to see the exact date and value at any point.
Uses matplotlib motion_notify_event — no extra dependencies.
"""

from typing import List

import matplotlib
matplotlib.use("QtAgg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from app.models import ResolvedPosition
from app.services.pnl_series import build_pnl_series

_BG    = "#0d1117"
_CARD  = "#161b22"
_MUTED = "#8b949e"
_GREEN = "#3fb950"
_RED   = "#f85149"
_BLUE  = "#58a6ff"
_TEXT  = "#c9d1d9"


def _range_date_format(range_: str, n_days: int) -> str:
    """Pick an appropriate strftime format for the x-axis based on range."""
    if range_ == "1d":
        return "%b %d"
    if range_ in ("1w", "1m"):
        return "%b %d"
    if range_ in ("1y", "ytd", "all") and n_days > 90:
        return "%b '%y"
    return "%b %d"


class PnlChartWidget(QWidget):
    """Cumulative realized P/L line chart with hover crosshair and tooltip."""

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

        # Hover state
        self._x_nums: list  = []   # matplotlib date numbers for each data point
        self._y_data: list  = []   # y values matching _x_nums
        self._x_data: list  = []   # original date objects for tooltip text
        self._vline  = None
        self._dot    = None
        self._annot  = None

        self._canvas.mpl_connect("motion_notify_event", self._on_motion)
        self._canvas.mpl_connect("axes_leave_event",    self._on_leave)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._canvas)

        self._draw()

    def update(self, closed: List[ResolvedPosition], range_: str) -> None:
        self._closed = list(closed)
        self._range  = range_
        self._draw()

    # ── Drawing ────────────────────────────────────────────────────────────────

    def _draw(self) -> None:
        ax = self._ax
        ax.clear()
        ax.set_facecolor(_BG)

        # Clear hover references (axis was cleared)
        self._vline = self._dot = self._annot = None
        self._x_nums = self._y_data = self._x_data = []

        x_dates, y_vals = build_pnl_series(self._closed, self._range)

        if not x_dates:
            self._draw_empty()
            return

        x_nums = mdates.date2num(x_dates)
        self._x_nums = x_nums
        self._y_data = y_vals
        self._x_data = x_dates

        final = y_vals[-1] if len(y_vals) > 1 else 0.0
        line_color = _GREEN if final >= 0 else _RED

        ax.plot(x_nums, y_vals, color=line_color, linewidth=1.8, zorder=3)
        ax.axhline(0, color=_MUTED, linewidth=0.5, alpha=0.5, zorder=1)

        # Shade area above/below zero
        y_arr = y_vals
        ax.fill_between(
            x_nums, 0, y_arr,
            where=[v >= 0 for v in y_arr],
            color=_GREEN, alpha=0.12, zorder=2,
        )
        ax.fill_between(
            x_nums, 0, y_arr,
            where=[v < 0 for v in y_arr],
            color=_RED, alpha=0.12, zorder=2,
        )

        # X-axis formatting
        n_days = (x_dates[-1] - x_dates[0]).days if len(x_dates) > 1 else 1
        fmt = _range_date_format(self._range, n_days)
        ax.xaxis.set_major_formatter(mdates.DateFormatter(fmt))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3, maxticks=7))

        # Y-axis formatting
        ax.yaxis.set_major_formatter(
            plt.FuncFormatter(lambda v, _: f"${v:+,.0f}" if v != 0 else "$0")
        )

        # Style
        ax.tick_params(axis="both", colors=_MUTED, labelsize=8)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.grid(axis="y", color=_MUTED, alpha=0.1, linewidth=0.5, zorder=0)

        # Persistent hover overlay objects (created once, updated on motion)
        self._vline, = ax.plot(
            [], [], color=_MUTED, linewidth=0.8, linestyle="--", zorder=5, visible=False
        )
        self._dot, = ax.plot(
            [], [], "o", color=_TEXT, markersize=5, zorder=6, visible=False
        )
        self._annot = ax.annotate(
            "", xy=(0, 0), xytext=(8, 8), textcoords="offset points",
            bbox=dict(boxstyle="round,pad=0.4", fc=_CARD, ec=_MUTED, alpha=0.9, linewidth=0.8),
            fontsize=8, color=_TEXT, zorder=7, visible=False,
        )

        self._fig.tight_layout(pad=0.5)
        self._canvas.draw_idle()

    def _draw_empty(self) -> None:
        ax = self._ax
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

    # ── Hover ──────────────────────────────────────────────────────────────────

    def _on_motion(self, event) -> None:
        if (
            event.inaxes is not self._ax
            or not self._x_nums
            or self._vline is None
        ):
            return

        # Snap to nearest data point by x
        idx = min(
            range(len(self._x_nums)),
            key=lambda i: abs(self._x_nums[i] - event.xdata),
        )
        xn = self._x_nums[idx]
        yv = self._y_data[idx]
        xd = self._x_data[idx]

        self._vline.set_data([xn, xn], [self._ax.get_ylim()[0], self._ax.get_ylim()[1]])
        self._vline.set_visible(True)

        self._dot.set_data([xn], [yv])
        self._dot.set_visible(True)

        label = f"{xd}\n{'$' + f'{yv:+,.2f}'}"
        self._annot.set_text(label)
        self._annot.xy = (xn, yv)
        self._annot.set_visible(True)

        self._canvas.draw_idle()

    def _on_leave(self, event) -> None:
        if self._vline is None:
            return
        self._vline.set_visible(False)
        self._dot.set_visible(False)
        if self._annot:
            self._annot.set_visible(False)
        self._canvas.draw_idle()
