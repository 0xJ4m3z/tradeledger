"""Tests for cache hydration and persistence correctness.

Covers the three bugs fixed in v0.3.1:
  1. Scroll-loaded activity pages now persisted to SQLite
  2. Scroll-loaded closed position pages now persisted to SQLite
  3. Activity in-memory list merges (not replaces) on live refresh

All tests are offline — no network calls, no Qt widgets.
"""

import pytest

from app.models import ResolvedPosition, UserActivity


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_db(monkeypatch, tmp_path):
    db_file = str(tmp_path / "hydration_test.db")
    monkeypatch.setattr("app.database.DB_PATH", db_file)
    import app.database as db
    db.init_db()
    yield db


WALLET = "0xCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC1"


def _act(ts: int, type_: str = "TRADE", side: str = "BUY", size: float = 50.0) -> UserActivity:
    return UserActivity(
        timestamp=ts, type=type_, title="Market", outcome="Yes",
        side=side, size=size, usdc_size=size, price=0.5,
    )


def _redeem(ts: int, usdc: float = 75.0) -> UserActivity:
    return UserActivity(
        timestamp=ts, type="REDEEM", title="Market", outcome="Yes",
        side="", size=100.0, usdc_size=usdc, price=0.0,
    )


def _closed(market: str, pnl: float = 10.0, cost: float = 50.0) -> ResolvedPosition:
    return ResolvedPosition(
        market=market, outcome_held="Yes", winning_outcome="Yes",
        quantity=100.0, cost_basis=cost, redeem_value=cost + pnl,
        redeemed=True, resolved_date="2025-06-01",
    )


# ── Scroll-loaded activity pages persist to SQLite ────────────────────────────

class TestActivityScrollPersistence:
    def test_initial_page_then_scroll_pages_accumulate(self, isolated_db):
        """Simulate initial fetch (100 rows) + 2 scroll pages (100 each) = 300 unique rows."""
        initial_page = [_act(i * 100) for i in range(100)]
        scroll_page_1 = [_act((100 + i) * 100) for i in range(100)]
        scroll_page_2 = [_act((200 + i) * 100) for i in range(100)]

        isolated_db.upsert_activity_cache(WALLET, initial_page)
        isolated_db.upsert_activity_cache(WALLET, scroll_page_1)
        isolated_db.upsert_activity_cache(WALLET, scroll_page_2)

        # Load with a limit large enough to see all three batches
        loaded = isolated_db.load_activity_cache(WALLET, limit=500)
        assert len(loaded) == 300

    def test_scroll_overlap_does_not_create_duplicates(self, isolated_db):
        """API pages sometimes overlap — dedup must prevent double-counting."""
        page1 = [_act(i * 100) for i in range(50)]
        page2 = [_act((40 + i) * 100) for i in range(50)]  # overlaps by 10 records

        isolated_db.upsert_activity_cache(WALLET, page1)
        isolated_db.upsert_activity_cache(WALLET, page2)

        loaded = isolated_db.load_activity_cache(WALLET, limit=200)
        # 50 + 50 - 10 overlap = 90 unique
        assert len(loaded) == 90

    def test_cached_rows_survive_simulated_restart(self, isolated_db):
        """After scroll-pages are persisted, they must be loadable on next startup."""
        initial  = [_act(i * 100) for i in range(100)]
        scroll_1 = [_act((100 + i) * 100) for i in range(50)]
        scroll_2 = [_act((150 + i) * 100) for i in range(50)]

        isolated_db.upsert_activity_cache(WALLET, initial)
        isolated_db.upsert_activity_cache(WALLET, scroll_1)
        isolated_db.upsert_activity_cache(WALLET, scroll_2)

        # Simulate restart: load the cache fresh
        loaded = isolated_db.load_activity_cache(WALLET, limit=500)
        assert len(loaded) == 200

    def test_redeem_events_persist_correctly(self, isolated_db):
        """REDEEM events (used for 1D chart) must survive scroll-page persistence."""
        redeems = [_redeem(ts=1_700_000_000 + i * 3600, usdc=float(i * 10 + 50)) for i in range(5)]
        buys    = [_act(ts=1_700_000_000 + i * 3600 + 1800) for i in range(5)]

        isolated_db.upsert_activity_cache(WALLET, redeems)
        isolated_db.upsert_activity_cache(WALLET, buys)

        loaded = isolated_db.load_activity_cache(WALLET, limit=20)
        redeem_loaded = [a for a in loaded if a.type == "REDEEM"]
        assert len(redeem_loaded) == 5
        assert all(a.type == "REDEEM" for a in redeem_loaded)


# ── Scroll-loaded closed position pages persist to SQLite ─────────────────────

class TestClosedPositionsScrollPersistence:
    def test_initial_page_then_scroll_pages_accumulate(self, isolated_db):
        """Simulate initial fetch + scroll pages accumulating in cache."""
        batch1 = [_closed(f"Market-{i}", pnl=float(i)) for i in range(50)]
        batch2 = [_closed(f"Market-{50 + i}", pnl=float(50 + i)) for i in range(50)]
        batch3 = [_closed(f"Market-{100 + i}", pnl=float(100 + i)) for i in range(50)]

        isolated_db.upsert_closed_positions_cache(batch1, WALLET)
        isolated_db.upsert_closed_positions_cache(batch2, WALLET)
        isolated_db.upsert_closed_positions_cache(batch3, WALLET)

        count = isolated_db.count_closed_positions_cache(WALLET)
        assert count == 150

    def test_scroll_overlap_no_duplicates(self, isolated_db):
        """Overlapping pages in closed positions must not create duplicate records."""
        batch1 = [_closed(f"M{i}", cost=float(i), pnl=10.0) for i in range(40)]
        # batch2 overlaps with the last 10 of batch1 (same market + cost_basis = same key)
        batch2 = [_closed(f"M{30 + i}", cost=float(30 + i), pnl=10.0) for i in range(20)]

        isolated_db.upsert_closed_positions_cache(batch1, WALLET)
        isolated_db.upsert_closed_positions_cache(batch2, WALLET)

        count = isolated_db.count_closed_positions_cache(WALLET)
        # 40 + 20 - 10 overlap = 50 unique
        assert count == 50

    def test_cached_closed_survive_restart(self, isolated_db):
        """Closed positions from scroll-loading must persist across restarts."""
        batch1 = [_closed(f"A-{i}") for i in range(30)]
        batch2 = [_closed(f"B-{i}") for i in range(30)]

        isolated_db.upsert_closed_positions_cache(batch1, WALLET)
        isolated_db.upsert_closed_positions_cache(batch2, WALLET)

        # Simulate restart load
        loaded = isolated_db.load_closed_positions_cache(WALLET, limit=500)
        assert len(loaded) == 60


# ── In-memory activity merge logic ────────────────────────────────────────────

def _merge_activity(existing: list, incoming: list) -> list:
    """Pure-Python replica of the fixed _on_activity_fetched merge logic."""
    if not existing:
        return list(incoming)
    seen  = {(a.timestamp, a.type, a.side, a.size) for a in existing}
    fresh = [a for a in incoming if (a.timestamp, a.type, a.side, a.size) not in seen]
    if fresh:
        return fresh + existing
    return existing


class TestActivityMergeLogic:
    def test_first_fetch_populates_from_scratch(self):
        result = _merge_activity([], [_act(1000), _act(2000)])
        assert len(result) == 2

    def test_refresh_prepends_only_new_records(self):
        """Live refresh should add new records without discarding cached history."""
        # 500 rows from cache startup
        cached = [_act(i * 100) for i in range(500)]
        # 100 rows from live API (80 overlap + 20 new, all newer)
        api_rows = [_act((500 + i) * 100) for i in range(20)] + cached[:80]

        result = _merge_activity(cached, api_rows)

        assert len(result) == 520   # 500 cached + 20 new
        # The 20 new records should be at the front
        new_ts = {(500 + i) * 100 for i in range(20)}
        for a in result[:20]:
            assert a.timestamp in new_ts

    def test_no_duplicates_when_all_records_already_known(self):
        """Auto-refresh returning the same 100 rows must not grow the list."""
        cached = [_act(i * 100) for i in range(100)]
        same   = [_act(i * 100) for i in range(100)]

        result = _merge_activity(cached, same)
        assert len(result) == 100

    def test_cache_history_never_lost_on_refresh(self):
        """The core bug: refreshing must NOT shrink the list to just API page size."""
        # 500 cached rows (indexes 0..499)
        cached = [_act(i * 100) for i in range(500)]
        # Refresh returns only the newest 100 (indexes 400..499)
        refresh = [_act(i * 100) for i in range(400, 500)]

        result = _merge_activity(cached, refresh)

        # All 500 must survive — the 100 from refresh overlap, no extras added
        assert len(result) == 500

    def test_scroll_extend_merge(self):
        """Scroll-load (older pages) must extend the list without duplicates."""
        existing = [_act(i * 100) for i in range(200, 300)]  # 100 recent records
        page     = [_act(i * 100) for i in range(100, 210)]  # 110 older, overlaps by 10

        seen  = {(a.timestamp, a.type, a.side, a.size) for a in existing}
        fresh = [a for a in page if (a.timestamp, a.type, a.side, a.size) not in seen]
        result = existing + fresh

        # 100 existing + 110 page - 10 overlap = 200 unique
        unique_ts = {a.timestamp for a in result}
        assert len(unique_ts) == 200

    def test_wallet_switch_starts_fresh(self):
        """When the wallet truly changes, _activity is reset to [] before first fetch."""
        existing = [_act(i * 100) for i in range(500)]
        cleared  = []   # wallet_address_changed clears to []
        # First fetch for new wallet
        new_wallet_api = [_act(i * 10) for i in range(100)]

        result = _merge_activity(cleared, new_wallet_api)
        assert len(result) == 100
        assert all(a.timestamp % 10 == 0 for a in result)


# ── Startup cache hydration: full DB round-trip ───────────────────────────────

class TestStartupHydration:
    def test_startup_loads_full_cached_activity(self, isolated_db):
        """Main window loads cached activity at startup; all rows must be present."""
        # Simulate persistent cache built over several sessions
        session1 = [_act(i * 100) for i in range(100)]
        session2 = [_act((100 + i) * 100) for i in range(100)]
        scroll_1 = [_act((200 + i) * 100) for i in range(100)]

        isolated_db.upsert_activity_cache(WALLET, session1)
        isolated_db.upsert_activity_cache(WALLET, session2)
        isolated_db.upsert_activity_cache(WALLET, scroll_1)

        # Startup load (default limit 500)
        cached = isolated_db.load_activity_cache(WALLET)
        assert len(cached) == 300

    def test_startup_closed_positions_cover_history(self, isolated_db):
        """Startup loads cached closed positions across multiple prior sessions."""
        week1 = [_closed(f"W1-{i}") for i in range(50)]
        week2 = [_closed(f"W2-{i}") for i in range(50)]
        week3 = [_closed(f"W3-{i}") for i in range(50)]

        isolated_db.upsert_closed_positions_cache(week1, WALLET)
        isolated_db.upsert_closed_positions_cache(week2, WALLET)
        isolated_db.upsert_closed_positions_cache(week3, WALLET)

        loaded = isolated_db.load_closed_positions_cache(WALLET, limit=500)
        assert len(loaded) == 150

    def test_redeem_events_available_for_1d_chart_on_startup(self, isolated_db):
        """REDEEM events saved in prior sessions must be loadable for the 1D chart."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        _ET = ZoneInfo("America/New_York")
        today = datetime.now(_ET).date()
        midnight_ts = int(datetime(today.year, today.month, today.day, 0, 0, 0, tzinfo=_ET).timestamp())

        # Save today's REDEEM events
        today_redeems = [_redeem(midnight_ts + i * 3600, usdc=float(10 + i * 5)) for i in range(5)]
        isolated_db.upsert_activity_cache(WALLET, today_redeems)

        loaded = isolated_db.load_activity_cache(WALLET)
        today_loaded = [a for a in loaded if a.type == "REDEEM"]
        assert len(today_loaded) == 5
