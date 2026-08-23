"""
Tests for app.services.refresh.run_full_refresh — the framework-agnostic
orchestration extracted from the desktop app's _FetchThread/_on_positions_fetched.

Mocks every adapter call (no live network access), consistent with the rest
of the suite. Each test uses a fresh temp SQLite file via the isolated_db
fixture (same pattern as tests/test_wallet_persistence.py).
"""

import pytest

from app.adapters.polymarket_adapter import PolymarketLookupError
from app.adapters.wallet_adapter import WalletLookupError
from app.models import ActivePosition, ResolvedPosition, UserActivity
from app.services import refresh as refresh_module

ADDRESS = "0xAbCdEf1234567890AbCdEf1234567890AbCdEf12"


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch, tmp_path):
    db_file = str(tmp_path / "test_tradeledger.db")
    monkeypatch.setattr("app.database.DB_PATH", db_file)
    import app.database as db
    db.init_db()
    yield db


def _active(market="Market A", outcome="YES", qty=10, avg=0.5, cur=0.6):
    return ActivePosition(market=market, outcome=outcome, quantity=qty, avg_cost=avg, current_price=cur)


def _resolved(market="Market B", outcome_held="YES", winning="YES", qty=10, cost=5.0, redeem=10.0):
    return ResolvedPosition(
        market=market, outcome_held=outcome_held, winning_outcome=winning,
        quantity=qty, cost_basis=cost, redeem_value=redeem, redeemed=True,
        resolved_date="2025-01-01",
    )


def _activity():
    return UserActivity(
        timestamp=1700000000, type="TRADE", title="Market A", outcome="YES",
        side="BUY", size=10, usdc_size=5.0, price=0.5,
    )


class TestHappyPath:
    def test_fetches_and_caches_everything(self, monkeypatch, isolated_db):
        monkeypatch.setattr(refresh_module, "fetch_wallet_usd_value", lambda addr: 123.45)
        monkeypatch.setattr(refresh_module, "fetch_active_positions", lambda addr: [_active()])
        monkeypatch.setattr(refresh_module, "fetch_resolved_positions", lambda addr: [_resolved()])
        monkeypatch.setattr(refresh_module, "fetch_closed_positions", lambda addr: [_resolved(market="Market C")])
        monkeypatch.setattr(refresh_module, "fetch_activity", lambda addr: [_activity()])

        result = refresh_module.run_full_refresh(ADDRESS)

        assert result.ok
        assert result.wallet_usd_value == 123.45
        assert result.active_count == 1
        assert result.resolved_count == 1
        assert result.closed_count == 1
        assert result.activity_count == 1
        assert result.has_any_data

        assert isolated_db.load_last_wallet() == ADDRESS
        assert len(isolated_db.load_active_positions_cache(ADDRESS)) == 1
        assert len(isolated_db.load_resolved_positions_cache(ADDRESS)) == 1
        assert len(isolated_db.load_all_closed_for_wallet(ADDRESS)) == 1
        snaps = isolated_db.load_wallet_snapshots(ADDRESS)
        assert len(snaps) == 1
        assert snaps[0]["wallet_usd_value"] == 123.45

    def test_dedupes_active_positions_already_resolved(self, monkeypatch, isolated_db):
        shared_market = "Same Market"
        monkeypatch.setattr(refresh_module, "fetch_wallet_usd_value", lambda addr: 0.0)
        monkeypatch.setattr(
            refresh_module, "fetch_active_positions",
            lambda addr: [_active(market=shared_market), _active(market="Still Active")],
        )
        monkeypatch.setattr(refresh_module, "fetch_resolved_positions", lambda addr: [_resolved(market=shared_market)])
        monkeypatch.setattr(refresh_module, "fetch_closed_positions", lambda addr: [])
        monkeypatch.setattr(refresh_module, "fetch_activity", lambda addr: [])

        result = refresh_module.run_full_refresh(ADDRESS)

        assert result.active_count == 1  # shared_market stripped from active
        cached_active = isolated_db.load_active_positions_cache(ADDRESS)
        assert [p.market for p in cached_active] == ["Still Active"]


class TestPartialFailure:
    def test_wallet_lookup_failure_does_not_block_positions(self, monkeypatch, isolated_db):
        def _boom(addr):
            raise WalletLookupError("all RPCs failed")

        monkeypatch.setattr(refresh_module, "fetch_wallet_usd_value", _boom)
        monkeypatch.setattr(refresh_module, "fetch_active_positions", lambda addr: [_active()])
        monkeypatch.setattr(refresh_module, "fetch_resolved_positions", lambda addr: [])
        monkeypatch.setattr(refresh_module, "fetch_closed_positions", lambda addr: [])
        monkeypatch.setattr(refresh_module, "fetch_activity", lambda addr: [])

        result = refresh_module.run_full_refresh(ADDRESS)

        assert not result.ok
        assert result.wallet_error == "all RPCs failed"
        assert result.wallet_usd_value is None
        assert result.active_count == 1  # positions still fetched + cached
        assert result.has_any_data
        # Snapshot still saved (positions succeeded), wallet_usd_value falls back to 0.
        snaps = isolated_db.load_wallet_snapshots(ADDRESS)
        assert len(snaps) == 1
        assert snaps[0]["wallet_usd_value"] == 0.0

    def test_positions_failure_does_not_block_wallet_or_activity(self, monkeypatch, isolated_db):
        def _boom(addr):
            raise PolymarketLookupError("network error")

        monkeypatch.setattr(refresh_module, "fetch_wallet_usd_value", lambda addr: 50.0)
        monkeypatch.setattr(refresh_module, "fetch_active_positions", _boom)
        monkeypatch.setattr(refresh_module, "fetch_resolved_positions", lambda addr: [])
        monkeypatch.setattr(refresh_module, "fetch_closed_positions", lambda addr: [])
        monkeypatch.setattr(refresh_module, "fetch_activity", lambda addr: [_activity()])

        result = refresh_module.run_full_refresh(ADDRESS)

        assert not result.ok
        assert result.positions_error == "network error"
        assert result.wallet_usd_value == 50.0
        assert result.activity_count == 1
        # No positions cached, so no snapshot is saved this round.
        assert isolated_db.load_wallet_snapshots(ADDRESS) == []
        # Wallet is still remembered even though this attempt partially failed.
        assert isolated_db.load_last_wallet() == ADDRESS

    def test_activity_failure_is_non_fatal(self, monkeypatch, isolated_db):
        def _boom(addr):
            raise PolymarketLookupError("timeout")

        monkeypatch.setattr(refresh_module, "fetch_wallet_usd_value", lambda addr: 0.0)
        monkeypatch.setattr(refresh_module, "fetch_active_positions", lambda addr: [])
        monkeypatch.setattr(refresh_module, "fetch_resolved_positions", lambda addr: [])
        monkeypatch.setattr(refresh_module, "fetch_closed_positions", lambda addr: [])
        monkeypatch.setattr(refresh_module, "fetch_activity", _boom)

        result = refresh_module.run_full_refresh(ADDRESS)

        assert not result.ok
        assert result.activity_error == "timeout"
        assert result.active_count == 0
        # Positions phase succeeded (returned empty lists, no exception) so a
        # snapshot is still saved even though activity failed.
        assert len(isolated_db.load_wallet_snapshots(ADDRESS)) == 1

    def test_total_failure_still_remembers_the_wallet(self, monkeypatch, isolated_db):
        monkeypatch.setattr(refresh_module, "fetch_wallet_usd_value", lambda addr: (_ for _ in ()).throw(WalletLookupError("x")))
        monkeypatch.setattr(refresh_module, "fetch_active_positions", lambda addr: (_ for _ in ()).throw(PolymarketLookupError("y")))
        monkeypatch.setattr(refresh_module, "fetch_resolved_positions", lambda addr: [])
        monkeypatch.setattr(refresh_module, "fetch_closed_positions", lambda addr: [])
        monkeypatch.setattr(refresh_module, "fetch_activity", lambda addr: (_ for _ in ()).throw(PolymarketLookupError("z")))

        result = refresh_module.run_full_refresh(ADDRESS)

        assert not result.ok
        assert not result.has_any_data
        assert isolated_db.load_last_wallet() == ADDRESS
        assert isolated_db.load_wallet_snapshots(ADDRESS) == []
