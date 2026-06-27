from typing import List

from app.models import ActivePosition, ResolvedPosition


def filter_active_by_outcome(positions: List[ActivePosition], outcome: str) -> List[ActivePosition]:
    return [p for p in positions if p.outcome == outcome]


def filter_resolved_wins(positions: List[ResolvedPosition]) -> List[ResolvedPosition]:
    return [p for p in positions if p.is_win]


def filter_resolved_losses(positions: List[ResolvedPosition]) -> List[ResolvedPosition]:
    return [p for p in positions if not p.is_win]


def sort_by_unrealized_pnl(positions: List[ActivePosition]) -> List[ActivePosition]:
    return sorted(positions, key=lambda p: p.unrealized_pnl, reverse=True)


def sort_by_realized_pnl(positions: List[ResolvedPosition]) -> List[ResolvedPosition]:
    return sorted(positions, key=lambda p: p.realized_pnl, reverse=True)
