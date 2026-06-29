"""
Tests for app/services/loss_watch.py.
"""

import pytest

from app.models import ActivePosition
from app.services.loss_watch import compute_loss_watch_count, get_loss_watch_positions


def _pos(market: str, avg_cost: float, current_price: float, qty: float = 100.0) -> ActivePosition:
    return ActivePosition(
        market=market,
        outcome="Yes",
        quantity=qty,
        avg_cost=avg_cost,
        current_price=current_price,
    )


class TestGetLossWatchPositions:
    def test_empty_list(self):
        assert get_loss_watch_positions([]) == []

    def test_all_winners(self):
        positions = [
            _pos("A", 0.40, 0.60),
            _pos("B", 0.50, 0.80),
        ]
        assert get_loss_watch_positions(positions) == []

    def test_all_losers(self):
        positions = [
            _pos("A", 0.60, 0.40),
            _pos("B", 0.80, 0.50),
        ]
        result = get_loss_watch_positions(positions)
        assert len(result) == 2

    def test_mixed(self):
        positions = [
            _pos("Win",  0.40, 0.60),
            _pos("Loss", 0.60, 0.40),
            _pos("Even", 0.50, 0.50),
        ]
        result = get_loss_watch_positions(positions)
        assert len(result) == 1
        assert result[0].market == "Loss"

    def test_breakeven_excluded(self):
        p = _pos("Breakeven", 0.50, 0.50)
        assert p.unrealized_pnl == 0.0
        assert get_loss_watch_positions([p]) == []


class TestComputeLossWatchCount:
    def test_empty_active(self):
        assert compute_loss_watch_count([], []) == 0

    def test_no_losers(self):
        positions = [_pos("A", 0.40, 0.60)]
        assert compute_loss_watch_count(positions, []) == 0

    def test_all_unacknowledged_losers(self):
        positions = [
            _pos("A", 0.60, 0.40),
            _pos("B", 0.70, 0.30),
        ]
        assert compute_loss_watch_count(positions, []) == 2

    def test_acknowledged_market_excluded(self):
        positions = [
            _pos("A", 0.60, 0.40),
            _pos("B", 0.70, 0.30),
        ]
        assert compute_loss_watch_count(positions, ["A"]) == 1

    def test_all_acknowledged(self):
        positions = [
            _pos("A", 0.60, 0.40),
            _pos("B", 0.70, 0.30),
        ]
        assert compute_loss_watch_count(positions, ["A", "B"]) == 0

    def test_acknowledged_winner_does_not_affect_count(self):
        positions = [
            _pos("Winner",  0.40, 0.60),
            _pos("Loser",   0.60, 0.40),
        ]
        # Acknowledging a winner has no effect
        assert compute_loss_watch_count(positions, ["Winner"]) == 1

    def test_acknowledged_list_is_superset(self):
        positions = [_pos("A", 0.60, 0.40)]
        # acknowledged contains extra markets not in active — no problem
        assert compute_loss_watch_count(positions, ["A", "B", "C"]) == 0
