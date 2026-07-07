"""Total Tracked Value over time chart.

Matches the visual style of PnlChartWidget: dark background, pchip-smoothed
line, subtle fill, and a hover crosshair showing date/time + value.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Tuple
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("QtAgg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from app.services.chart_utils import pchip_smooth
from app.services.date_range import DateRangeSelection, filter_snapshots_by_selection
from app.ui.date_range_control import DateRangeControl

_BG    = "#0d1117"
_CARD  = "#161b22"
_MUTED = "#8b949e"
_BLUE  = "#58a6ff"
_FILL  = "#1f3a5f"
_TEXT  = "#c9d1d9"
_UTC   = timezone.utc
_ET    = ZoneInfo("America/New_York")

_DEFAULT_SELECTION = DateRangeSelection.preset_range("all")


def _parse_captured_at(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_UTC)
    return dt.astimezone(_UTC)


def _xaxis_label(x_num: float, selection: DateRangeSelection) -> str:
    dt_et = mdates.num2date(x_num).astimezone(_ET)
    if selection.is_preset() and selection.preset == "1d":
        return dt_et.strftime("%H:%M")
    if selection.is_preset() and selection.preset in ("1w", "1m"):
        return dt_et.strftime("%b %d")
    return dt_et.strftime("%b '%y")


def _tooltip_label(dt: datetime, value: float) -> str:
    local = dt.astimezone(_ET)
    return f"{local.strftime('%b %d, %Y %H:%M')}\n${value:,.2f}"


def _usd_fmt(v, _):
    if abs(v) >= 1_000:
        return f"${v/1000:.1f}k"
    return f"${v:.0f}"


class TotalValueChartWidget(QWidget):
    """Total Tracked Value chart, styled to match PnlChartWidget.

    Pass show_range_buttons=False to hide the range control row.

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

        # Hover state
        self._x_nums: list = []
        self._y_data: list = []
        self._x_dts:  list = []
        self._vline        = None
        self._dot          = None
        self._annot        = None

        self._fig, self._ax = plt.subplots(figsize=figsize)
        self._fig.patch.set_facecolor(_BG)
        self._ax.set_facecolor(_BG)

        self._canvas = FigureCanvasQTAgg(self._fig)
        self._canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._canvas.mpl_connect("motion_notify_event", self._on_motion)
        self._canvas.mpl_connect("axes_leave_event",    self._on_leave)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        if show_range_buttons:
            self._range_ctrl = DateRangeControl(default="all")
            self._range_ctrl.range_changed.connect(self._on_range)
            layout.addWidget(self._range_ctrl)

        layout.addWidget(self._canvas)

        self._redraw()

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
        ax = self._ax
        ax.clear()
        ax.set_facecolor(_BG)

        self._vline = self._dot = self._annot = None
        self._x_nums = self._y_data = self._x_dts = []

        if not filtered:
            msg = (
                "No data for this range."
                if not self._selection.is_all()
                else "No history yet.\nEnter a wallet value to start tracking."
            )
            ax.text(0.5, 0.5, msg, ha="center", va="center",
                    color=_MUTED, fontsize=10, transform=ax.transAxes)
            ax.set_xticks([])
            ax.set_yticks([])
            for spine in ax.spines.values():
                spine.set_visible(False)
            self._canvas.draw_idle()
            return

        dts    = [_parse_captured_at(s["captured_at"]) for s in filtered]
        values = [s["total_tracked_value"] for s in filtered]
        x_nums = list(mdates.date2num(dts))

        self._x_nums = x_nums
        self._y_data = list(values)
        self._x_dts  = list(dts)

        sel = self._selection
        x_draw, y_draw = pchip_smooth(x_nums, values, n=300)

        ax.plot(x_draw, y_draw, color=_BLUE, linewidth=1.8, zorder=3)
        ax.fill_between(x_draw, y_draw, alpha=0.12, color=_FILL, zorder=2)

        ax.xaxis.set_major_formatter(
            plt.FuncFormatter(lambda x, _: _xaxis_label(x, sel))
        )
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3, maxticks=7))
        ax.tick_params(axis="x", labelsize=8, colors=_MUTED)

        ax.yaxis.set_major_formatter(plt.FuncFormatter(_usd_fmt))
        ax.tick_params(axis="y", labelsize=8, colors=_MUTED)

        mn, mx = min(values), max(values)
        spread = max(mx - mn, max(mx * 0.005, 1.0))
        ax.set_ylim(mn - spread * 0.3, mx + spread * 0.5)

        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.grid(axis="y", color=_MUTED, alpha=0.1, linewidth=0.5, zorder=0)

        # Hover elements
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

        self._fig.subplots_adjust(left=0.10, right=0.98, top=0.97, bottom=0.18)
        self._canvas.draw_idle()

    # ── Hover ──────────────────────────────────────────────────────────────

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
        dt = self._x_dts[idx]

        ylim = self._ax.get_ylim()
        self._vline.set_data([xn, xn], [ylim[0], ylim[1]])
        self._vline.set_visible(True)
        self._dot.set_data([xn], [yv])
        self._dot.set_visible(True)
        self._annot.set_text(_tooltip_label(dt, yv))
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
