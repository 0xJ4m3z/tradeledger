from typing import List

from app.models import ActivePosition


def get_loss_watch_positions(active: List[ActivePosition]) -> List[ActivePosition]:
    """Return active positions with negative unrealized P/L."""
    return [p for p in active if p.unrealized_pnl < 0]


def compute_loss_watch_count(
    active: List[ActivePosition],
    acknowledged_markets: List[str],
) -> int:
    """Count open losing positions whose market title is not in acknowledged_markets."""
    ack_set = set(acknowledged_markets)
    return sum(
        1
        for p in active
        if p.unrealized_pnl < 0 and p.market not in ack_set
    )
