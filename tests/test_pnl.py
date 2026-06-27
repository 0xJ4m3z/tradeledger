import pytest

from app.models import ActivePosition, ResolvedPosition
from app.services.pnl import calc_cumulative_pnl, calc_realized_pnl, calc_unrealized_pnl


def _active(quantity=100, avg_cost=0.50, current_price=0.70) -> ActivePosition:
    return ActivePosition("Test Market", "YES", quantity, avg_cost, current_price)


def _resolved(cost_basis=100.0, redeem_value=150.0, resolved_date="2025-01-01") -> ResolvedPosition:
    return ResolvedPosition(
        market="Test Market",
        outcome_held="YES",
        winning_outcome="YES",
        quantity=150,
        cost_basis=cost_basis,
        redeem_value=redeem_value,
        redeemed=True,
        resolved_date=resolved_date,
    )


class TestActivePositionMetrics:
    def test_unrealized_pnl_profit(self):
        p = _active(quantity=100, avg_cost=0.50, current_price=0.70)
        assert p.unrealized_pnl == pytest.approx(20.0)

    def test_unrealized_pnl_loss(self):
        p = _active(quantity=200, avg_cost=0.80, current_price=0.60)
        assert p.unrealized_pnl == pytest.approx(-40.0)

    def test_unrealized_pnl_pct(self):
        p = _active(quantity=100, avg_cost=0.50, current_price=0.75)
        assert p.unrealized_pnl_pct == pytest.approx(50.0)

    def test_current_value(self):
        p = _active(quantity=200, avg_cost=0.30, current_price=0.45)
        assert p.current_value == pytest.approx(90.0)

    def test_cost_basis(self):
        p = _active(quantity=400, avg_cost=0.25, current_price=0.50)
        assert p.cost_basis == pytest.approx(100.0)

    def test_zero_cost_basis_returns_zero_pct(self):
        p = _active(quantity=100, avg_cost=0.0, current_price=0.50)
        assert p.unrealized_pnl_pct == 0.0


class TestResolvedPositionMetrics:
    def test_realized_pnl_win(self):
        p = _resolved(cost_basis=100.0, redeem_value=300.0)
        assert p.realized_pnl == pytest.approx(200.0)

    def test_realized_pnl_loss(self):
        p = ResolvedPosition("Test", "YES", "NO", 100, 75.0, 0.0, False)
        assert p.realized_pnl == pytest.approx(-75.0)

    def test_realized_pnl_pct(self):
        p = _resolved(cost_basis=200.0, redeem_value=400.0)
        assert p.realized_pnl_pct == pytest.approx(100.0)

    def test_is_win_true(self):
        p = _resolved()
        assert p.is_win is True

    def test_is_win_false(self):
        p = ResolvedPosition("Test", "YES", "NO", 100, 50.0, 0.0, False)
        assert p.is_win is False

    def test_zero_cost_basis_returns_zero_pct(self):
        p = ResolvedPosition("Test", "YES", "YES", 100, 0.0, 100.0, True)
        assert p.realized_pnl_pct == 0.0


class TestAggregates:
    def test_calc_unrealized_pnl_mixed(self):
        positions = [
            _active(100, 0.50, 0.70),   # pnl = +20
            _active(200, 0.80, 0.60),   # pnl = -40
        ]
        assert calc_unrealized_pnl(positions) == pytest.approx(-20.0)

    def test_calc_unrealized_pnl_empty(self):
        assert calc_unrealized_pnl([]) == pytest.approx(0.0)

    def test_calc_realized_pnl_mixed(self):
        positions = [
            _resolved(100.0, 200.0),   # +100
            _resolved(50.0, 0.0),      # -50
        ]
        assert calc_realized_pnl(positions) == pytest.approx(50.0)

    def test_calc_realized_pnl_empty(self):
        assert calc_realized_pnl([]) == pytest.approx(0.0)

    def test_calc_cumulative_pnl_sorted_chronologically(self):
        positions = [
            _resolved(100.0, 200.0, "2025-03-01"),   # +100 (later)
            _resolved(50.0, 0.0, "2025-01-01"),      # -50  (earlier)
        ]
        df = calc_cumulative_pnl(positions)
        assert list(df["cumulative_pnl"]) == pytest.approx([-50.0, 50.0])

    def test_calc_cumulative_pnl_empty_list(self):
        df = calc_cumulative_pnl([])
        assert df.empty

    def test_calc_cumulative_pnl_no_dates(self):
        p = ResolvedPosition("Test", "YES", "YES", 100, 50.0, 100.0, True, resolved_date=None)
        df = calc_cumulative_pnl([p])
        assert df.empty
