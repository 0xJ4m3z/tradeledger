from typing import List

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.models import ResolvedPosition
from app.services.pnl import calc_cumulative_pnl

_BG     = "#0d1117"
_BORDER = "#30363d"
_MUTED  = "#8b949e"
_GREEN  = "#3fb950"
_RED    = "#f85149"

matplotlib.rcParams.update({
    "font.family":      "DejaVu Sans",
    "text.color":       _MUTED,
    "axes.labelcolor":  _MUTED,
    "xtick.color":      _MUTED,
    "ytick.color":      _MUTED,
    "figure.facecolor": _BG,
    "axes.facecolor":   _BG,
})


class PnlChartWidget(QWidget):
    def __init__(self, resolved: List[ResolvedPosition]):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        title = QLabel("Cumulative P/L Over Time")
        title.setStyleSheet("color: #c9d1d9; font-size: 14px; font-weight: 600;")
        layout.addWidget(title)

        df = calc_cumulative_pnl(resolved)

        fig = Figure(facecolor=_BG, figsize=(10, 5))
        ax = fig.add_subplot(111)
        ax.set_facecolor(_BG)

        if df.empty:
            ax.text(
                0.5, 0.5, "No resolved positions to chart",
                color=_MUTED, ha="center", va="center",
                transform=ax.transAxes, fontsize=13,
            )
        else:
            dates  = df["date"]
            values = df["cumulative_pnl"]
            final  = values.iloc[-1]

            line_color = _GREEN if final >= 0 else _RED
            ax.plot(dates, values, color=line_color, linewidth=2)
            ax.fill_between(dates, values, 0, where=(values >= 0), color=_GREEN, alpha=0.12)
            ax.fill_between(dates, values, 0, where=(values < 0),  color=_RED,   alpha=0.12)
            ax.axhline(0, color=_BORDER, linewidth=1, linestyle="--")

            ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"${x:,.0f}"))
            fig.autofmt_xdate(rotation=30)

        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        ax.spines["bottom"].set_color(_BORDER)
        ax.spines["left"].set_color(_BORDER)
        ax.tick_params(colors=_MUTED, labelsize=10)
        ax.set_xlabel("Date", color=_MUTED, fontsize=11, labelpad=8)
        ax.set_ylabel("Cumulative P/L (USD)", color=_MUTED, fontsize=11, labelpad=8)

        fig.tight_layout(pad=2.0)
        layout.addWidget(FigureCanvas(fig))
