"""Tests for the active/resolved/activity and wallet-isolated closed caches."""

import pytest

from app.models import ActivePosition, ResolvedPosition, UserActivity


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_db(monkeypatch, tmp_path):
    db_file = str(tmp_path / "test.db")
    monkeypatch.setattr("app.database.DB_PATH", db_file)
    import app.database as db
    db.init_db()
    yield db


WALLET_A = "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1"
WALLET_B = "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB2"


def _active(market: str, outcome: str = "Yes") -> ActivePosition:
    return ActivePosition(
        market=market, outcome=outcome,
        quantity=100.0, avg_cost=0.5, current_price=0.6,
    )


def _resolved(market: str, pnl: float = 10.0) -> ResolvedPosition:
    cb = 50.0
    return ResolvedPosition(
        market=market, outcome_held="Yes", winning_outcome="Yes",
        quantity=100.0, cost_basis=cb, redeem_value=cb + pnl,
        redeemed=True, resolved_date="2025-06-01",
    )


def _activity(ts: int = 1_000_000, type_: str = "TRADE", side: str = "BUY") -> UserActivity:
    return UserActivity(
        timestamp=ts, type=type_, title="Market A", outcome="Yes",
        side=side, size=100.0, usdc_size=50.0, price=0.5,
    )


# ── Active positions cache ─────────────────────────────────────────────────────

class TestActivePositionsCache:
    def test_load_returns_empty_before_save(self, isolated_db):
        assert isolated_db.load_active_positions_cache(WALLET_A) == []

    def test_save_and_load_roundtrip(self, isolated_db):
        positions = [_active("BTC"), _active("ETH")]
        isolated_db.save_active_positions_cache(WALLET_A, positions)
        loaded = isolated_db.load_active_positions_cache(WALLET_A)
        assert {p.market for p in loaded} == {"BTC", "ETH"}

    def test_save_replaces_previous(self, isolated_db):
        isolated_db.save_active_positions_cache(WALLET_A, [_active("Old")])
        isolated_db.save_active_positions_cache(WALLET_A, [_active("New")])
        loaded = isolated_db.load_active_positions_cache(WALLET_A)
        assert len(loaded) == 1
        assert loaded[0].market == "New"

    def test_wallet_isolation(self, isolated_db):
        isolated_db.save_active_positions_cache(WALLET_A, [_active("BTC")])
        isolated_db.save_active_positions_cache(WALLET_B, [_active("ETH")])
        assert isolated_db.load_active_positions_cache(WALLET_A)[0].market == "BTC"
        assert isolated_db.load_active_positions_cache(WALLET_B)[0].market == "ETH"

    def test_save_empty_clears_cache(self, isolated_db):
        isolated_db.save_active_positions_cache(WALLET_A, [_active("BTC")])
        isolated_db.save_active_positions_cache(WALLET_A, [])
        assert isolated_db.load_active_positions_cache(WALLET_A) == []

    def test_roundtrip_preserves_fields(self, isolated_db):
        p = ActivePosition(
            market="Gold", outcome="Up", quantity=500.0,
            avg_cost=0.72, current_price=0.88,
        )
        isolated_db.save_active_positions_cache(WALLET_A, [p])
        loaded = isolated_db.load_active_positions_cache(WALLET_A)[0]
        assert loaded.market == "Gold"
        assert loaded.outcome == "Up"
        assert loaded.quantity == 500.0
        assert abs(loaded.avg_cost - 0.72) < 1e-6
        assert abs(loaded.current_price - 0.88) < 1e-6


# ── Resolved positions cache ──────────────────────────────────────────────────

class TestResolvedPositionsCache:
    def test_load_returns_empty_before_save(self, isolated_db):
        assert isolated_db.load_resolved_positions_cache(WALLET_A) == []

    def test_save_and_load_roundtrip(self, isolated_db):
        positions = [_resolved("Market X"), _resolved("Market Y")]
        isolated_db.save_resolved_positions_cache(WALLET_A, positions)
        loaded = isolated_db.load_resolved_positions_cache(WALLET_A)
        assert len(loaded) == 2
        assert {p.market for p in loaded} == {"Market X", "Market Y"}

    def test_save_replaces_previous(self, isolated_db):
        isolated_db.save_resolved_positions_cache(WALLET_A, [_resolved("Old")])
        isolated_db.save_resolved_positions_cache(WALLET_A, [_resolved("New")])
        loaded = isolated_db.load_resolved_positions_cache(WALLET_A)
        assert len(loaded) == 1
        assert loaded[0].market == "New"

    def test_wallet_isolation(self, isolated_db):
        isolated_db.save_resolved_positions_cache(WALLET_A, [_resolved("MarketA")])
        isolated_db.save_resolved_positions_cache(WALLET_B, [_resolved("MarketB")])
        a = isolated_db.load_resolved_positions_cache(WALLET_A)
        b = isolated_db.load_resolved_positions_cache(WALLET_B)
        assert a[0].market == "MarketA"
        assert b[0].market == "MarketB"

    def test_realized_pnl_preserved(self, isolated_db):
        p = _resolved("BTC", pnl=77.5)
        isolated_db.save_resolved_positions_cache(WALLET_A, [p])
        loaded = isolated_db.load_resolved_positions_cache(WALLET_A)[0]
        assert abs(loaded.realized_pnl - 77.5) < 0.01


# ── Closed positions cache (wallet isolation) ─────────────────────────────────

class TestClosedPositionsCacheWalletIsolation:
    def test_wallet_a_does_not_see_wallet_b_closed(self, isolated_db):
        p_a = _resolved("MarketA")
        p_b = _resolved("MarketB")
        isolated_db.upsert_closed_positions_cache([p_a], WALLET_A)
        isolated_db.upsert_closed_positions_cache([p_b], WALLET_B)
        loaded_a = isolated_db.load_closed_positions_cache(WALLET_A)
        loaded_b = isolated_db.load_closed_positions_cache(WALLET_B)
        assert len(loaded_a) == 1 and loaded_a[0].market == "MarketA"
        assert len(loaded_b) == 1 and loaded_b[0].market == "MarketB"

    def test_dedup_within_same_wallet(self, isolated_db):
        p = _resolved("Market")
        isolated_db.upsert_closed_positions_cache([p], WALLET_A)
        isolated_db.upsert_closed_positions_cache([p], WALLET_A)
        assert isolated_db.count_closed_positions_cache(WALLET_A) == 1

    def test_same_position_different_wallets_not_deduplicated(self, isolated_db):
        # Same logical position (same key) belongs to two different wallets
        p = _resolved("Market", pnl=10.0)
        isolated_db.upsert_closed_positions_cache([p], WALLET_A)
        isolated_db.upsert_closed_positions_cache([p], WALLET_B)
        assert isolated_db.count_closed_positions_cache(WALLET_A) == 1
        assert isolated_db.count_closed_positions_cache(WALLET_B) == 1

    def test_count_scoped_to_wallet(self, isolated_db):
        isolated_db.upsert_closed_positions_cache(
            [_resolved(f"M{i}") for i in range(5)], WALLET_A
        )
        isolated_db.upsert_closed_positions_cache(
            [_resolved(f"M{i}") for i in range(2)], WALLET_B
        )
        assert isolated_db.count_closed_positions_cache(WALLET_A) == 5
        assert isolated_db.count_closed_positions_cache(WALLET_B) == 2


# ── Activity cache ────────────────────────────────────────────────────────────

class TestActivityCache:
    def test_load_returns_empty_before_upsert(self, isolated_db):
        assert isolated_db.load_activity_cache(WALLET_A) == []

    def test_upsert_and_load(self, isolated_db):
        events = [_activity(1000), _activity(2000)]
        isolated_db.upsert_activity_cache(WALLET_A, events)
        loaded = isolated_db.load_activity_cache(WALLET_A)
        assert len(loaded) == 2

    def test_dedup_by_event_key(self, isolated_db):
        a = _activity(1000, "TRADE", "BUY")
        isolated_db.upsert_activity_cache(WALLET_A, [a])
        isolated_db.upsert_activity_cache(WALLET_A, [a])   # same event again
        loaded = isolated_db.load_activity_cache(WALLET_A)
        assert len(loaded) == 1

    def test_different_timestamp_not_deduplicated(self, isolated_db):
        isolated_db.upsert_activity_cache(WALLET_A, [_activity(1000)])
        isolated_db.upsert_activity_cache(WALLET_A, [_activity(2000)])
        assert len(isolated_db.load_activity_cache(WALLET_A)) == 2

    def test_wallet_isolation(self, isolated_db):
        isolated_db.upsert_activity_cache(WALLET_A, [_activity(1000)])
        isolated_db.upsert_activity_cache(WALLET_B, [_activity(9999)])
        a = isolated_db.load_activity_cache(WALLET_A)
        b = isolated_db.load_activity_cache(WALLET_B)
        assert len(a) == 1 and a[0].timestamp == 1000
        assert len(b) == 1 and b[0].timestamp == 9999

    def test_returned_newest_first(self, isolated_db):
        isolated_db.upsert_activity_cache(
            WALLET_A, [_activity(1000), _activity(3000), _activity(2000)]
        )
        loaded = isolated_db.load_activity_cache(WALLET_A)
        timestamps = [a.timestamp for a in loaded]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_limit_caps_results(self, isolated_db):
        events = [_activity(i * 1000) for i in range(20)]
        isolated_db.upsert_activity_cache(WALLET_A, events)
        loaded = isolated_db.load_activity_cache(WALLET_A, limit=5)
        assert len(loaded) == 5

    def test_roundtrip_preserves_fields(self, isolated_db):
        a = UserActivity(
            timestamp=123456, type="REDEEM", title="Gold Market",
            outcome="", side="", size=500.0, usdc_size=300.0, price=0.0,
        )
        isolated_db.upsert_activity_cache(WALLET_A, [a])
        loaded = isolated_db.load_activity_cache(WALLET_A)[0]
        assert loaded.timestamp == 123456
        assert loaded.type == "REDEEM"
        assert loaded.title == "Gold Market"
        assert loaded.size == 500.0
        assert loaded.usdc_size == 300.0

    def test_merge_new_without_duplicates(self, isolated_db):
        """Simulates scroll-load: each page only adds genuinely new events."""
        page1 = [_activity(i * 100) for i in range(5)]
        page2 = [_activity(i * 100) for i in range(3, 8)]  # overlaps with page1
        isolated_db.upsert_activity_cache(WALLET_A, page1)
        isolated_db.upsert_activity_cache(WALLET_A, page2)
        all_loaded = isolated_db.load_activity_cache(WALLET_A)
        # Timestamps 0,100,200,300,400,500,600,700 — 8 unique events
        unique_ts = {a.timestamp for a in all_loaded}
        assert len(unique_ts) == 8


# ── Active/resolved/closed mutual exclusivity ─────────────────────────────────

class TestMutualExclusivity:
    def test_resolved_market_not_in_active(self, isolated_db):
        """The FetchThread strips resolved markets from active; caches should reflect this."""
        resolved = [_resolved("BTC")]
        active   = [_active("ETH")]   # BTC not in active
        isolated_db.save_active_positions_cache(WALLET_A, active)
        isolated_db.save_resolved_positions_cache(WALLET_A, resolved)
        active_markets   = {p.market for p in isolated_db.load_active_positions_cache(WALLET_A)}
        resolved_markets = {p.market for p in isolated_db.load_resolved_positions_cache(WALLET_A)}
        assert "BTC" not in active_markets
        assert "BTC" in resolved_markets
        assert "ETH" in active_markets
        assert "ETH" not in resolved_markets

    def test_replacing_active_cache_reflects_resolved_transition(self, isolated_db):
        """If a market moves from active to resolved, saving new active cache removes it."""
        isolated_db.save_active_positions_cache(WALLET_A, [_active("BTC"), _active("ETH")])
        # Next fetch: BTC resolved, only ETH active
        isolated_db.save_active_positions_cache(WALLET_A, [_active("ETH")])
        isolated_db.save_resolved_positions_cache(WALLET_A, [_resolved("BTC")])
        active_markets = {p.market for p in isolated_db.load_active_positions_cache(WALLET_A)}
        assert "BTC" not in active_markets
        assert "ETH" in active_markets
