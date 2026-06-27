from typing import List

from app.models import ActivePosition, ResolvedPosition
from app.services.pnl import calc_unrealized_pnl, calc_realized_pnl


def compute_dashboard_metrics(
    active: List[ActivePosition],
    resolved: List[ResolvedPosition],
) -> dict:
    wins = [p for p in resolved if p.is_win]
    losses = [p for p in resolved if not p.is_win]

    unrealized = calc_unrealized_pnl(active)
    realized = calc_realized_pnl(resolved)
    active_value = sum(p.current_value for p in active)

    largest_win = max((p.realized_pnl for p in wins), default=0.0)
    largest_loss = min((p.realized_pnl for p in losses), default=0.0)

    return {
        "active_positions_value": active_value,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "total_estimated_value": active_value + realized,
        "win_count": len(wins),
        "loss_count": len(losses),
        "largest_win": largest_win,
        "largest_loss": largest_loss,
    }
