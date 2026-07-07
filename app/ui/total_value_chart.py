from datetime import datetime, timezone
from typing import List, Tuple

import matplotlib
import matplotlib.dates as mdates
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
_MUTED      = "#8b949e"
_TEXT       = "#c9d1d9"
_CARD       = "#161b22"
_UTC        = timezone.utc

_DEFAULT_SELECTION = DateRangeSelection.preset_range("all")


def _parse_captured_at(s: str) -> datetime:
    """Parse a captured_at ISO string to a UTC-aware datetime."""
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_UTC)
    return dt.astimezone(_UTC)


def _usd_fmt(x, _):
    if abs(x) >= 1000:
        return f"${x/1000:.1f}k"
    return f"${x:.0f}"


def _tooltip_label(dt: datetime, value: float) -> str:
    return f"{dt.strftime('%b %d, %Y %H:%M')}\n${value:,.2f}"


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

        # Hover state
        self._x_nums: list = []
        self._y_data: list = []
        self._x_dts:  list = []
        self._vline        = None
        self._dot          = None
        self._annot        = None

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

        self._canvas.mpl_connect("motion_notify_event", self._on_motion)
        self._canvas.mpl_connect("axes_leave_event",    self._on_leave)

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
        self._vline = self._dot = self._annot = None
        self._x_nums = self._y_data = self._x_dts = []
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

        # Parse captured_at to datetimes, convert to mdates numbers for plotting
        dts    = [_parse_captured_at(s["captured_at"]) for s in snapshots]
        values = [s["total_tracked_value"] for s in snapshots]
        x_nums = list(mdates.date2num(dts))

        self._x_nums = x_nums
        self._y_data = list(values)
        self._x_dts  = list(dts)

        if len(x_nums) == 1:
            ax.plot(x_nums, values, "o", color=_LINE_COLOR, markersize=7)
            v = values[0]
            pad = max(v * 0.04, 1.0)
            ax.set_ylim(v - pad * 0.6, v + pad * 1.2)
        else:
            ax.plot(x_nums, values, color=_LINE_COLOR, linewidth=2)
            ax.fill_between(x_nums, values, alpha=0.15, color=_FILL_COLOR)
            mn, mx = min(values), max(values)
            spread = max(mx - mn, max(mx * 0.005, 1.0))
            ax.set_ylim(mn - spread * 0.3, mx + spread * 0.5)

        tick_step = max(1, len(x_nums) // 6)
        ax.set_xticks(x_nums[::tick_step])
        ax.xaxis.set_major_formatter(
            mdates.DateFormatter("%Y-%m-%d")
        )
        ax.tick_params(axis="x", labelsize=8, rotation=30)
        ax.yaxis.set_tick_params(labelsize=8)

        # Hover elements (invisible until mouse moves)
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
