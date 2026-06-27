from typing import List

from app.models import ActivePosition, ResolvedPosition
from app.services.pnl import calc_unrealized_pnl, calc_realized_pnl


def compute_total_tracked_value(active_positions_value: float, wallet_usd_value: float) -> float:
    return round(active_positions_value + wallet_usd_value, 2)


def compute_dashboard_metrics(
    active: List[ActivePosition],
    resolved: List[ResolvedPosition],
) -> dict:
    wins   = [p for p in resolved if p.is_win]
    losses = [p for p in resolved if not p.is_win]

    unrealized   = calc_unrealized_pnl(active)
    realized     = calc_realized_pnl(resolved)
    active_value = sum(p.current_value for p in active)

    return {
        "active_positions_value": active_value,
        "realized_pnl":          realized,
        "unrealized_pnl":        unrealized,
        "win_count":             len(wins),
        "loss_count":            len(losses),
        # wallet_usd_value and total_tracked_value are set at runtime
        # after the user fetches or enters a wallet value
        "wallet_usd_value":      0.0,
        "total_tracked_value":   active_value,  # starts as active value only
    }
