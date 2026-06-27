"""
Tests for wallet snapshot storage in database.py.
Uses a temporary SQLite file so tests never touch the real tradeledger.db.
"""

import pytest


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch, tmp_path):
    """Point DB_PATH at a fresh temp file for each test."""
    db_file = str(tmp_path / "test_tradeledger.db")
    monkeypatch.setattr("app.database.DB_PATH", db_file)
    # Re-import to pick up patched path
    import app.database as db
    db.init_db()
    yield db


class TestWalletSnapshotStorage:
    def test_empty_on_init(self, isolated_db):
        snapshots = isolated_db.load_wallet_snapshots()
        assert snapshots == []

    def test_save_and_load_single_snapshot(self, isolated_db):
        isolated_db.save_wallet_snapshot(
            active_positions_value=2256.00,
            wallet_usd_value=1244.00,
            unrealized_pnl=310.50,
            realized_pnl=680.50,
        )
        snapshots = isolated_db.load_wallet_snapshots()
        assert len(snapshots) == 1
        s = snapshots[0]
        assert s["active_positions_value"] == 2256.00
        assert s["wallet_usd_value"] == 1244.00
        assert s["total_tracked_value"] == 3500.00
        assert s["unrealized_pnl"] == 310.50
        assert s["realized_pnl"] == 680.50

    def test_total_tracked_value_is_sum(self, isolated_db):
        isolated_db.save_wallet_snapshot(
            active_positions_value=1000.00,
            wallet_usd_value=500.00,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
        )
        s = isolated_db.load_wallet_snapshots()[0]
        assert s["total_tracked_value"] == 1500.00

    def test_multiple_snapshots_ordered_chronologically(self, isolated_db):
        for wallet_val in [100.0, 200.0, 300.0]:
            isolated_db.save_wallet_snapshot(
                active_positions_value=1000.0,
                wallet_usd_value=wallet_val,
                unrealized_pnl=0.0,
                realized_pnl=0.0,
            )
        snapshots = isolated_db.load_wallet_snapshots()
        assert len(snapshots) == 3
        totals = [s["total_tracked_value"] for s in snapshots]
        assert totals == [1100.0, 1200.0, 1300.0]

    def test_zero_wallet_value_snapshot(self, isolated_db):
        isolated_db.save_wallet_snapshot(
            active_positions_value=500.0,
            wallet_usd_value=0.0,
            unrealized_pnl=50.0,
            realized_pnl=25.0,
        )
        s = isolated_db.load_wallet_snapshots()[0]
        assert s["wallet_usd_value"] == 0.0
        assert s["total_tracked_value"] == 500.0

    def test_captured_at_is_present(self, isolated_db):
        isolated_db.save_wallet_snapshot(1000.0, 500.0, 0.0, 0.0)
        s = isolated_db.load_wallet_snapshots()[0]
        assert s["captured_at"] is not None
        assert len(s["captured_at"]) > 0
