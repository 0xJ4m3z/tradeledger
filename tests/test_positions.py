from app.models import ActivePosition, ResolvedPosition
from app.services.positions import (
    filter_active_by_outcome,
    filter_resolved_losses,
    filter_resolved_wins,
    sort_by_realized_pnl,
    sort_by_unrealized_pnl,
)


def _active(outcome="YES", avg_cost=0.5, current_price=0.6) -> ActivePosition:
    return ActivePosition("Test", outcome, 100, avg_cost, current_price)


def _resolved(outcome_held="YES", winning="YES", cost=50.0, redeem=100.0) -> ResolvedPosition:
    return ResolvedPosition("Test", outcome_held, winning, 100, cost, redeem, True, "2025-01-01")


class TestFilters:
    def test_filter_active_by_outcome_yes(self):
        positions = [_active("YES"), _active("NO"), _active("YES")]
        assert len(filter_active_by_outcome(positions, "YES")) == 2

    def test_filter_active_by_outcome_no(self):
        positions = [_active("YES"), _active("NO"), _active("NO")]
        assert len(filter_active_by_outcome(positions, "NO")) == 2

    def test_filter_active_by_outcome_empty(self):
        assert filter_active_by_outcome([], "YES") == []

    def test_filter_resolved_wins(self):
        positions = [
            _resolved("YES", "YES"),   # win
            _resolved("YES", "NO"),    # loss
            _resolved("NO", "NO"),     # win (held == winning)
        ]
        assert len(filter_resolved_wins(positions)) == 2

    def test_filter_resolved_losses(self):
        positions = [_resolved("YES", "YES"), _resolved("YES", "NO")]
        assert len(filter_resolved_losses(positions)) == 1

    def test_filter_resolved_wins_empty(self):
        assert filter_resolved_wins([]) == []


class TestSorting:
    def test_sort_active_by_unrealized_pnl_descending(self):
        positions = [
            _active(avg_cost=0.5, current_price=0.6),    # pnl = +10
            _active(avg_cost=0.8, current_price=0.4),    # pnl = -40
            _active(avg_cost=0.3, current_price=0.9),    # pnl = +60
        ]
        result = sort_by_unrealized_pnl(positions)
        pnls = [p.unrealized_pnl for p in result]
        assert pnls == sorted(pnls, reverse=True)

    def test_sort_resolved_by_realized_pnl_descending(self):
        positions = [
            _resolved(cost=50.0, redeem=100.0),    # +50
            _resolved(cost=100.0, redeem=0.0),     # -100
            _resolved(cost=30.0, redeem=150.0),    # +120
        ]
        result = sort_by_realized_pnl(positions)
        pnls = [p.realized_pnl for p in result]
        assert pnls == sorted(pnls, reverse=True)

    def test_sort_does_not_mutate_input(self):
        positions = [_active(avg_cost=0.8, current_price=0.4), _active(avg_cost=0.3, current_price=0.9)]
        original_first_pnl = positions[0].unrealized_pnl
        sort_by_unrealized_pnl(positions)
        assert positions[0].unrealized_pnl == original_first_pnl
