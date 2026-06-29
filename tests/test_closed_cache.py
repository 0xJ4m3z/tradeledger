"""
Tests for closed positions cache in database.py.
Each test uses a fresh temp SQLite file via the isolated_db fixture.
"""

import pytest

from app.models import ResolvedPosition


def _rpos(market: str, outcome: str = "Yes", cost: float = 100.0, pnl: float = 10.0) -> ResolvedPosition:
    return ResolvedPosition(
        market=market,
        outcome_held=outcome,
        winning_outcome=outcome if pnl >= 0 else "No",
        quantity=1000.0,
        cost_basis=cost,
        redeem_value=cost + pnl,
        redeemed=True,
        resolved_date="2025-01-15",
    )


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch, tmp_path):
    db_file = str(tmp_path / "test_tradeledger.db")
    monkeypatch.setattr("app.database.DB_PATH", db_file)
    import app.database as db
    db.init_db()
    yield db


class TestClosedPositionsCache:
    def test_empty_on_init(self, isolated_db):
        assert isolated_db.count_closed_positions_cache() == 0

    def test_upsert_and_count(self, isolated_db):
        positions = [_rpos("Market A"), _rpos("Market B")]
        isolated_db.upsert_closed_positions_cache(positions)
        assert isolated_db.count_closed_positions_cache() == 2

    def test_load_returns_resolved_positions(self, isolated_db):
        p = _rpos("Market X", cost=200.0, pnl=50.0)
        isolated_db.upsert_closed_positions_cache([p])
        results = isolated_db.load_closed_positions_cache()
        assert len(results) == 1
        r = results[0]
        assert r.market == "Market X"
        assert r.cost_basis == 200.0
        assert r.redeem_value == 250.0

    def test_upsert_deduplicates_by_position_key(self, isolated_db):
        p = _rpos("Dup Market", cost=100.0, pnl=10.0)
        isolated_db.upsert_closed_positions_cache([p])
        isolated_db.upsert_closed_positions_cache([p])   # same position again
        assert isolated_db.count_closed_positions_cache() == 1

    def test_upsert_updates_existing_on_conflict(self, isolated_db):
        p1 = ResolvedPosition(
            market="Market",
            outcome_held="Yes",
            winning_outcome="Yes",
            quantity=100.0,
            cost_basis=50.0,
            redeem_value=60.0,
            redeemed=True,
            resolved_date=None,
        )
        isolated_db.upsert_closed_positions_cache([p1])

        # Same key (market + outcome + cost_basis), different redeem_value
        p2 = ResolvedPosition(
            market="Market",
            outcome_held="Yes",
            winning_outcome="Yes",
            quantity=100.0,
            cost_basis=50.0,   # same cost_basis → same position_key
            redeem_value=75.0,  # updated
            redeemed=True,
            resolved_date=None,
        )
        isolated_db.upsert_closed_positions_cache([p2])

        assert isolated_db.count_closed_positions_cache() == 1
        results = isolated_db.load_closed_positions_cache()
        assert results[0].redeem_value == 75.0

    def test_different_cost_basis_creates_new_row(self, isolated_db):
        p1 = _rpos("Market", cost=100.0, pnl=10.0)
        p2 = _rpos("Market", cost=200.0, pnl=20.0)  # different cost_basis → different key
        isolated_db.upsert_closed_positions_cache([p1, p2])
        assert isolated_db.count_closed_positions_cache() == 2

    def test_all_positions_returned(self, isolated_db):
        positions = [_rpos(f"Market {i}", cost=float(i * 10)) for i in range(10)]
        isolated_db.upsert_closed_positions_cache(positions)
        results = isolated_db.load_closed_positions_cache()
        assert len(results) == 10

    def test_empty_list_upsert_is_noop(self, isolated_db):
        isolated_db.upsert_closed_positions_cache([])
        assert isolated_db.count_closed_positions_cache() == 0

    def test_position_key_format(self, isolated_db):
        from app.database import _position_key
        p = _rpos("BTC Market", cost=123.456789)
        key = _position_key(p)
        assert key == "BTC Market|Yes|123.456789"
