"""Cumulative realized P/L line chart for the Overview panel.

For 1D: intraday series driven by closed_at timestamps on closed positions.
         Works for any close type (REDEEM, SELL, MERGE, etc.).
         Steps-post line so the value stays flat between events.
For 1W+: daily rollup from closed positions, normal line.

Interactive hover: vertical crosshair, dot on the line, tooltip showing
time (1D) or date (1W+) and the cumulative P/L at that point.
"""
from __future__ import annotations

from typing import List
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("QtAgg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from app.models import ResolvedPosition, UserActivity
from app.services.pnl_points import build_cumulative_pnl_points

_BG    = "#0d1117"
_CARD  = "#161b22"
_MUTED = "#8b949e"
_GREEN = "#3fb950"
_RED   = "#f85149"
_TEXT  = "#c9d1d9"
_ET    = ZoneInfo("America/New_York")


def _tooltip_ts(ts, range_: str) -> str:
    """Format a timezone-aware datetime for the hover tooltip."""
    local = ts.astimezone(_ET)
    if range_ == "1d":
        return local.strftime("%H:%M ET")
    if range_ in ("1w", "1m"):
        return local.strftime("%b %d")
    return local.strftime("%b %d, %Y")


def _xaxis_label(x_num, range_: str) -> str:
    """Format a matplotlib date number for the x-axis tick label (ET)."""
    dt_et = mdates.num2date(x_num).astimezone(_ET)
    if range_ == "1d":
        return dt_et.strftime("%H:%M")
    if range_ in ("1w", "1m"):
        return dt_et.strftime("%b %d")
    return dt_et.strftime("%b '%y")


class PnlChartWidget(QWidget):
    """Cumulative realized P/L line chart with step-hold and hover crosshair."""

    def __init__(
        self,
        activity: List[UserActivity] = None,
        closed: List[ResolvedPosition] = None,
        range_: str = "1d",
        figsize: tuple = (6, 3),
    ):
        super().__init__()
        self._activity = list(activity or [])
        self._closed   = list(closed or [])
        self._range    = range_
        self.is_partial = False  # set by _draw(); checked by overview for card ~

        self._fig, self._ax = plt.subplots(figsize=figsize)
        self._fig.patch.set_facecolor(_BG)
        self._ax.set_facecolor(_BG)

        self._canvas = FigureCanvasQTAgg(self._fig)
        self._canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        # Hover state — all Python lists so bool checks are safe
        self._x_nums: list = []   # float date numbers
        self._y_data: list = []   # float P/L values
        self._x_data: list = []   # aware datetime objects for tooltip

        self._vline = None
        self._dot   = None
        self._annot = None

        self._canvas.mpl_connect("motion_notify_event", self._on_motion)
        self._canvas.mpl_connect("axes_leave_event",    self._on_leave)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._canvas)

        self._draw()

    # ── Public ────────────────────────────────────────────────────────────────

    def update(
        self,
        activity: List[UserActivity],
        closed: List[ResolvedPosition],
        range_: str,
    ) -> None:
        self._activity = list(activity)
        self._closed   = list(closed)
        self._range    = range_
        self._draw()

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw(self) -> None:
        ax = self._ax
        ax.clear()
        ax.set_facecolor(_BG)

        # Reset hover state; the axis was cleared
        self._vline = self._dot = self._annot = None
        self._x_nums = self._y_data = self._x_data = []

        points, self.is_partial = build_cumulative_pnl_points(
            self._activity, self._closed, self._range
        )

        if not points:
            self._draw_empty()
            return

        timestamps = [p["timestamp"] for p in points]
        y_vals     = [p["value"]     for p in points]

        # Keep as Python lists so `not self._x_nums` works correctly
        x_nums = list(mdates.date2num(timestamps))
        self._x_nums = x_nums
        self._y_data = list(y_vals)
        self._x_data = list(timestamps)

        final = y_vals[-1] if len(y_vals) > 1 else 0.0
        color = _GREEN if final >= 0 else _RED

        is_1d = (self._range == "1d")
        draw_style = "steps-post" if is_1d else "default"
        fill_step  = "post"       if is_1d else None

        ax.plot(x_nums, y_vals, color=color, linewidth=1.8,
                drawstyle=draw_style, zorder=3)
        ax.axhline(0, color=_MUTED, linewidth=0.5, alpha=0.5, zorder=1)

        ax.fill_between(
            x_nums, 0, y_vals,
            where=[v >= 0 for v in y_vals],
            color=_GREEN, alpha=0.12, step=fill_step, zorder=2,
        )
        ax.fill_between(
            x_nums, 0, y_vals,
            where=[v < 0 for v in y_vals],
            color=_RED, alpha=0.12, step=fill_step, zorder=2,
        )

        # X-axis: convert float date numbers back to ET datetimes for labels
        _rng = self._range  # capture for closure
        ax.xaxis.set_major_formatter(
            plt.FuncFormatter(lambda x, _: _xaxis_label(x, _rng))
        )
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3, maxticks=7))
        ax.tick_params(axis="x", labelsize=8, colors=_MUTED)

        # Y-axis
        ax.yaxis.set_major_formatter(
            plt.FuncFormatter(lambda v, _: f"${v:+,.0f}" if v != 0 else "$0")
        )
        ax.tick_params(axis="y", labelsize=8, colors=_MUTED)

        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.grid(axis="y", color=_MUTED, alpha=0.1, linewidth=0.5, zorder=0)

        # Persistent hover overlay objects (created once per draw, updated on motion)
        self._vline, = ax.plot(
            [], [], color=_MUTED, linewidth=0.8, linestyle="--", zorder=5, visible=False
        )
        self._dot, = ax.plot(
            [], [], "o", color=_TEXT, markersize=5, zorder=6, visible=False
        )
        self._annot = ax.annotate(
            "", xy=(0, 0), xytext=(8, 8), textcoords="offset points",
            bbox=dict(boxstyle="round,pad=0.4", fc=_CARD, ec=_MUTED,
                      alpha=0.9, linewidth=0.8),
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

    # ── Hover ─────────────────────────────────────────────────────────────────

    def _on_motion(self, event) -> None:
        if (
            event.inaxes is not self._ax
            or not self._x_nums
            or self._vline is None
        ):
            return

        idx = min(
            range(len(self._x_nums)),
            key=lambda i: abs(self._x_nums[i] - event.xdata),
        )
        xn = self._x_nums[idx]
        yv = self._y_data[idx]
        ts = self._x_data[idx]

        label = f"{_tooltip_ts(ts, self._range)}\n${yv:+,.2f}"

        ylim = self._ax.get_ylim()
        self._vline.set_data([xn, xn], [ylim[0], ylim[1]])
        self._vline.set_visible(True)
        self._dot.set_data([xn], [yv])
        self._dot.set_visible(True)
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
