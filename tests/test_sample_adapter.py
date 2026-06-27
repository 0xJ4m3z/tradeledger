from app.adapters.sample_adapter import load_active_positions, load_all, load_resolved_positions
from app.models import ActivePosition, ResolvedPosition


class TestLoadActivePositions:
    def test_returns_non_empty_list(self):
        positions = load_active_positions()
        assert isinstance(positions, list)
        assert len(positions) > 0

    def test_all_items_are_active_positions(self):
        for p in load_active_positions():
            assert isinstance(p, ActivePosition)

    def test_prices_are_in_valid_range(self):
        for p in load_active_positions():
            assert 0.0 <= p.avg_cost <= 1.0, f"avg_cost out of range: {p.avg_cost}"
            assert 0.0 <= p.current_price <= 1.0, f"current_price out of range: {p.current_price}"

    def test_quantities_are_positive(self):
        for p in load_active_positions():
            assert p.quantity > 0

    def test_market_names_are_non_empty(self):
        for p in load_active_positions():
            assert p.market.strip() != ""


class TestLoadResolvedPositions:
    def test_returns_non_empty_list(self):
        positions = load_resolved_positions()
        assert isinstance(positions, list)
        assert len(positions) > 0

    def test_all_items_are_resolved_positions(self):
        for p in load_resolved_positions():
            assert isinstance(p, ResolvedPosition)

    def test_cost_basis_is_non_negative(self):
        for p in load_resolved_positions():
            assert p.cost_basis >= 0.0

    def test_redeem_value_is_non_negative(self):
        for p in load_resolved_positions():
            assert p.redeem_value >= 0.0

    def test_quantities_are_positive(self):
        for p in load_resolved_positions():
            assert p.quantity > 0

    def test_winning_positions_have_full_redeem(self):
        """Positions where outcome_held == winning_outcome should have redeem_value > 0."""
        for p in load_resolved_positions():
            if p.is_win:
                assert p.redeem_value > 0, f"Win with zero redeem: {p.market}"

    def test_losing_positions_have_zero_redeem(self):
        for p in load_resolved_positions():
            if not p.is_win:
                assert p.redeem_value == 0.0, f"Loss with non-zero redeem: {p.market}"


class TestLoadAll:
    def test_returns_two_lists(self):
        active, resolved = load_all()
        assert isinstance(active, list)
        assert isinstance(resolved, list)

    def test_consistent_with_individual_loaders(self):
        active, resolved = load_all()
        assert len(active) == len(load_active_positions())
        assert len(resolved) == len(load_resolved_positions())
