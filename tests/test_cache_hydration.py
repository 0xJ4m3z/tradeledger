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


# ── Cache-first pagination (load_activity_cache_page / load_closed_positions_cache_page) ──


class TestActivityCachePage:
    """load_activity_cache_page returns the correct slice without touching the API."""

    def test_first_page_matches_load_cache(self, isolated_db):
        rows = [_act(i * 100) for i in range(200)]
        isolated_db.upsert_activity_cache(WALLET, rows)

        page0 = isolated_db.load_activity_cache_page(WALLET, offset=0, limit=100)
        full  = isolated_db.load_activity_cache(WALLET, limit=100)
        assert len(page0) == 100
        assert [a.timestamp for a in page0] == [a.timestamp for a in full]

    def test_second_page_is_disjoint_from_first(self, isolated_db):
        rows = [_act(i * 100) for i in range(200)]
        isolated_db.upsert_activity_cache(WALLET, rows)

        page0 = isolated_db.load_activity_cache_page(WALLET, offset=0, limit=100)
        page1 = isolated_db.load_activity_cache_page(WALLET, offset=100, limit=100)
        ts0 = {a.timestamp for a in page0}
        ts1 = {a.timestamp for a in page1}
        assert len(ts0) == 100
        assert len(ts1) == 100
        assert ts0.isdisjoint(ts1), "Consecutive pages must not overlap"

    def test_pages_cover_full_dataset(self, isolated_db):
        rows = [_act(i * 100) for i in range(250)]
        isolated_db.upsert_activity_cache(WALLET, rows)

        all_ts = []
        for offset in range(0, 300, 100):
            page = isolated_db.load_activity_cache_page(WALLET, offset=offset, limit=100)
            all_ts.extend(a.timestamp for a in page)

        assert len(set(all_ts)) == 250

    def test_offset_beyond_cache_returns_empty(self, isolated_db):
        """Empty result signals the caller should fall back to the API."""
        rows = [_act(i * 100) for i in range(50)]
        isolated_db.upsert_activity_cache(WALLET, rows)

        page = isolated_db.load_activity_cache_page(WALLET, offset=100, limit=100)
        assert page == []

    def test_wallet_isolation(self, isolated_db):
        wallet_b = "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB2"
        isolated_db.upsert_activity_cache(WALLET, [_act(i * 100) for i in range(50)])
        isolated_db.upsert_activity_cache(wallet_b, [_act(i * 100 + 5) for i in range(50)])

        page_a = isolated_db.load_activity_cache_page(WALLET, offset=0, limit=100)
        ts_a = {a.timestamp for a in page_a}
        assert not any(ts % 100 == 5 for ts in ts_a), "Wallet B rows must not appear for Wallet A"

    def test_count_activity_cache(self, isolated_db):
        isolated_db.upsert_activity_cache(WALLET, [_act(i * 100) for i in range(75)])
        assert isolated_db.count_activity_cache(WALLET) == 75

    def test_newest_first_ordering(self, isolated_db):
        rows = [_act(i * 100) for i in range(100)]
        isolated_db.upsert_activity_cache(WALLET, rows)

        page = isolated_db.load_activity_cache_page(WALLET, offset=0, limit=10)
        timestamps = [a.timestamp for a in page]
        assert timestamps == sorted(timestamps, reverse=True)


class TestClosedCachePage:
    """load_closed_positions_cache_page returns the correct slice."""

    def test_first_page_matches_load_closed_cache(self, isolated_db):
        positions = [_closed(f"M{i}", cost=float(i)) for i in range(100)]
        isolated_db.upsert_closed_positions_cache(positions, WALLET)

        page0 = isolated_db.load_closed_positions_cache_page(WALLET, offset=0, limit=50)
        full  = isolated_db.load_closed_positions_cache(WALLET, limit=50)
        assert len(page0) == 50
        assert [(p.market, p.cost_basis) for p in page0] == [(p.market, p.cost_basis) for p in full]

    def test_pages_cover_full_dataset(self, isolated_db):
        positions = [_closed(f"M{i}", cost=float(i)) for i in range(130)]
        isolated_db.upsert_closed_positions_cache(positions, WALLET)

        seen_markets = set()
        for offset in range(0, 200, 50):
            page = isolated_db.load_closed_positions_cache_page(WALLET, offset=offset, limit=50)
            for p in page:
                seen_markets.add(p.market)

        assert len(seen_markets) == 130

    def test_offset_beyond_cache_returns_empty(self, isolated_db):
        positions = [_closed(f"M{i}") for i in range(30)]
        isolated_db.upsert_closed_positions_cache(positions, WALLET)

        page = isolated_db.load_closed_positions_cache_page(WALLET, offset=100, limit=50)
        assert page == []

    def test_consecutive_pages_disjoint(self, isolated_db):
        positions = [_closed(f"M{i}", cost=float(i)) for i in range(100)]
        isolated_db.upsert_closed_positions_cache(positions, WALLET)

        page0 = isolated_db.load_closed_positions_cache_page(WALLET, offset=0,  limit=50)
        page1 = isolated_db.load_closed_positions_cache_page(WALLET, offset=50, limit=50)
        markets0 = {p.market for p in page0}
        markets1 = {p.market for p in page1}
        assert markets0.isdisjoint(markets1)

    def test_wallet_isolation(self, isolated_db):
        wallet_b = "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB2"
        isolated_db.upsert_closed_positions_cache([_closed("WalletA-Market")], WALLET)
        isolated_db.upsert_closed_positions_cache([_closed("WalletB-Market")], wallet_b)

        page = isolated_db.load_closed_positions_cache_page(WALLET, offset=0, limit=50)
        assert all(p.market != "WalletB-Market" for p in page)


# ── Scroll _has_more: fresh rows always enable further scrolling ───────────────

def _scroll_merge_closed(existing: list, incoming: list) -> tuple:
    """Replica of fixed append_positions merge logic. Returns (merged, has_more)."""
    seen  = {(p.market, p.outcome_held, p.cost_basis) for p in existing}
    fresh = [p for p in incoming if (p.market, p.outcome_held, p.cost_basis) not in seen]
    if not fresh:
        return existing, False
    return existing + fresh, True   # has_more=True: partial page mustn't stop scroll


def _scroll_merge_activity(existing: list, incoming: list) -> tuple:
    """Replica of fixed append_activity merge logic. Returns (merged, has_more)."""
    seen  = {(a.timestamp, a.type, a.side, a.size) for a in existing}
    fresh = [a for a in incoming if (a.timestamp, a.type, a.side, a.size) not in seen]
    if not fresh:
        return existing, False
    return existing + fresh, True


class TestScrollHasMore:
    def test_full_page_keeps_scroll_enabled(self):
        existing = [_closed(f"M{i}") for i in range(50)]
        incoming = [_closed(f"New-{i}") for i in range(50)]
        _, has_more = _scroll_merge_closed(existing, incoming)
        assert has_more is True

    def test_partial_cache_page_keeps_scroll_enabled(self):
        """A partial cache page (< 50 rows) must NOT stop scrolling."""
        existing = [_closed(f"M{i}") for i in range(50)]
        incoming = [_closed(f"New-{i}") for i in range(20)]   # only 20 fresh
        _, has_more = _scroll_merge_closed(existing, incoming)
        assert has_more is True

    def test_zero_fresh_stops_scroll(self):
        """All-duplicate page: both cache and API exhausted — scroll must stop."""
        existing = [_closed(f"M{i}") for i in range(50)]
        incoming = [_closed(f"M{i}") for i in range(50)]       # exact duplicates
        _, has_more = _scroll_merge_closed(existing, incoming)
        assert has_more is False

    def test_activity_partial_cache_page_keeps_scroll_enabled(self):
        existing = [_act(i * 100) for i in range(100)]
        incoming = [_act((100 + i) * 100) for i in range(30)]  # 30 fresh
        _, has_more = _scroll_merge_activity(existing, incoming)
        assert has_more is True

    def test_activity_zero_fresh_stops_scroll(self):
        existing = [_act(i * 100) for i in range(100)]
        incoming = [_act(i * 100) for i in range(100)]          # duplicates
        _, has_more = _scroll_merge_activity(existing, incoming)
        assert has_more is False


# ── DB-backed range stat helpers ──────────────────────────────────────────────

def _et_midnight_today() -> int:
    """Return Unix timestamp for midnight ET today."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    tz  = ZoneInfo("America/New_York")
    today = datetime.now(tz).date()
    return int(datetime(today.year, today.month, today.day, 0, 0, 0, tzinfo=tz).timestamp())


def _closed_ts(
    market: str,
    pnl: float = 10.0,
    cost: float = 50.0,
    closed_at: int | None = None,
) -> ResolvedPosition:
    return ResolvedPosition(
        market=market, outcome_held="Yes", winning_outcome="Yes",
        quantity=100.0, cost_basis=cost, redeem_value=cost + pnl,
        redeemed=True, resolved_date="2025-01-01", closed_at=closed_at,
    )


class TestRangeStatsFromDB:
    """compute_pnl_for_range / count_closed_for_range query SQLite directly —
    no in-memory cap, correct time-filtering via closed_at epoch (ET)."""

    def test_compute_pnl_today_includes_today(self, isolated_db):
        midnight = _et_midnight_today()
        p = _closed_ts("M", pnl=15.0, closed_at=midnight + 3600)  # 1 AM ET today
        isolated_db.upsert_closed_positions_cache([p], WALLET)
        assert isolated_db.compute_pnl_for_range(WALLET, "1d") == 15.0

    def test_compute_pnl_today_excludes_yesterday(self, isolated_db):
        midnight = _et_midnight_today()
        p = _closed_ts("M", pnl=15.0, closed_at=midnight - 3600)  # 11 PM ET yesterday
        isolated_db.upsert_closed_positions_cache([p], WALLET)
        assert isolated_db.compute_pnl_for_range(WALLET, "1d") == 0.0

    def test_count_closed_today(self, isolated_db):
        midnight = _et_midnight_today()
        today_positions = [
            _closed_ts(f"Today-{i}", pnl=10.0, closed_at=midnight + (i + 1) * 3600)
            for i in range(3)
        ]
        yesterday_pos = _closed_ts("Yesterday", pnl=10.0, closed_at=midnight - 3600)
        isolated_db.upsert_closed_positions_cache(today_positions + [yesterday_pos], WALLET)
        assert isolated_db.count_closed_for_range(WALLET, "1d") == 3

    def test_compute_pnl_all_includes_all_positions(self, isolated_db):
        midnight = _et_midnight_today()
        positions = [
            _closed_ts(f"M{i}", pnl=10.0, closed_at=midnight - i * 86400)
            for i in range(5)
        ]
        isolated_db.upsert_closed_positions_cache(positions, WALLET)
        assert isolated_db.compute_pnl_for_range(WALLET, "all") == 50.0

    def test_pnl_sum_includes_losses(self, isolated_db):
        midnight = _et_midnight_today()
        win  = _closed_ts("Win",  pnl= 20.0, closed_at=midnight + 3600)
        loss = _closed_ts("Loss", pnl=-5.0,  closed_at=midnight + 7200)
        isolated_db.upsert_closed_positions_cache([win, loss], WALLET)
        assert isolated_db.compute_pnl_for_range(WALLET, "1d") == 15.0

    def test_empty_wallet_returns_zero(self, isolated_db):
        assert isolated_db.compute_pnl_for_range("", "1d") == 0.0
        assert isolated_db.count_closed_for_range("", "1d") == 0

    def test_positions_without_closed_at_use_resolved_date_fallback(self, isolated_db):
        """closed_at=None rows fall back to resolved_date for range filtering.

        If resolved_date matches today the position appears in 1d stats.
        If resolved_date is old it is excluded from 1d (but included in 'all').
        """
        from app.services.pnl_today import today_date_et
        today_str = today_date_et().isoformat()

        p_today = _closed_ts("Today", pnl=30.0, closed_at=None)
        # Override resolved_date to today so it matches the 1d fallback filter
        p_today = ResolvedPosition(
            market="Today", outcome_held="Yes", winning_outcome="Yes",
            quantity=100.0, cost_basis=50.0, redeem_value=80.0,
            redeemed=True, resolved_date=today_str, closed_at=None,
        )
        p_old = _closed_ts("Old", pnl=20.0, closed_at=None)  # resolved_date="2025-01-01"

        isolated_db.upsert_closed_positions_cache([p_today, p_old], WALLET)

        # Today's position (resolved_date=today) IS counted via the fallback
        assert isolated_db.count_closed_for_range(WALLET, "1d")  == 1
        assert isolated_db.compute_pnl_for_range(WALLET,  "1d")  == 30.0
        # Old position not in 1d but in 'all'
        assert isolated_db.compute_pnl_for_range(WALLET, "all") == 50.0
        assert isolated_db.count_closed_for_range(WALLET, "all") == 2

    def test_wallet_isolation(self, isolated_db):
        wallet_b = "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB2"
        midnight = _et_midnight_today()
        p_a = _closed_ts("Ma", pnl=50.0,  closed_at=midnight + 3600)
        p_b = _closed_ts("Mb", pnl=100.0, closed_at=midnight + 3600)
        isolated_db.upsert_closed_positions_cache([p_a], WALLET)
        isolated_db.upsert_closed_positions_cache([p_b], wallet_b)
        assert isolated_db.compute_pnl_for_range(WALLET,   "1d") == 50.0
        assert isolated_db.count_closed_for_range(WALLET,  "1d") == 1
        assert isolated_db.compute_pnl_for_range(wallet_b, "1d") == 100.0

    def test_range_start_epoch_1d_is_midnight_et(self, isolated_db):
        """_range_start_epoch('1d') must equal midnight ET today (not trailing 24h)."""
        from app.database import _range_start_epoch
        epoch = _range_start_epoch("1d")
        assert epoch is not None
        midnight = _et_midnight_today()
        assert epoch == midnight

    def test_range_start_epoch_all_returns_none(self, isolated_db):
        from app.database import _range_start_epoch
        assert _range_start_epoch("all") is None


# ── filter_closed_by_range: uses closed_at not resolved_date ──────────────────

class TestFilterClosedByRangeClosedAt:
    """filter_closed_by_range must use closed_at (actual close time) for 1D filtering,
    not resolved_date (market end date) which caused cross-day confusion."""

    def test_1d_uses_closed_at_ignores_old_resolved_date(self):
        """Position closed today (closed_at=today) with far-past resolved_date still appears in 1D."""
        from app.services.pnl_today import filter_closed_by_range
        midnight = _et_midnight_today()
        p = ResolvedPosition(
            market="M", outcome_held="Yes", winning_outcome="Yes",
            quantity=1.0, cost_basis=50.0, redeem_value=60.0,
            redeemed=True, resolved_date="2020-01-01",    # old resolved_date
            closed_at=midnight + 3600,                     # closed 1 AM ET today
        )
        assert len(filter_closed_by_range([p], "1d")) == 1

    def test_1d_excludes_yesterday_closed_at_even_with_future_resolved_date(self):
        """Position closed yesterday (closed_at=yesterday) must NOT appear in 1D."""
        from app.services.pnl_today import filter_closed_by_range
        midnight = _et_midnight_today()
        p = ResolvedPosition(
            market="M", outcome_held="Yes", winning_outcome="Yes",
            quantity=1.0, cost_basis=50.0, redeem_value=60.0,
            redeemed=True, resolved_date="2099-12-31",    # future resolved_date
            closed_at=midnight - 3600,                     # closed 11 PM ET yesterday
        )
        assert len(filter_closed_by_range([p], "1d")) == 0

    def test_1d_fallback_to_resolved_date_when_no_closed_at(self):
        """Legacy positions without closed_at use resolved_date as fallback."""
        from app.services.pnl_today import filter_closed_by_range, today_date_et
        today_str = today_date_et().isoformat()
        p = ResolvedPosition(
            market="M", outcome_held="Yes", winning_outcome="Yes",
            quantity=1.0, cost_basis=50.0, redeem_value=60.0,
            redeemed=True, resolved_date=today_str, closed_at=None,
        )
        assert len(filter_closed_by_range([p], "1d")) == 1

    def test_1w_includes_6_days_ago_excludes_8_days_ago(self):
        """For 1W (7-day trailing window), positions within range are included."""
        import time
        from app.services.pnl_today import filter_closed_by_range
        now = int(time.time())
        p_in  = _closed_ts("In",  pnl=10.0, closed_at=now - 6 * 86400)   # 6 days ago
        p_out = _closed_ts("Out", pnl=10.0, closed_at=now - 8 * 86400)   # 8 days ago
        result = filter_closed_by_range([p_in, p_out], "1w")
        assert {p.market for p in result} == {"In"}

    def test_all_range_returns_everything(self):
        """'all' bypasses closed_at filtering entirely."""
        from app.services.pnl_today import filter_closed_by_range
        midnight = _et_midnight_today()
        positions = [
            _closed_ts("Old",     pnl=1.0, closed_at=midnight - 365 * 86400),
            _closed_ts("Recent",  pnl=2.0, closed_at=midnight + 3600),
            _closed_ts("NoDate",  pnl=3.0, closed_at=None),
        ]
        result = filter_closed_by_range(positions, "all")
        assert len(result) == 3


# ── Trades counting: distinct market titles in activity ───────────────────────

class TestTradesCounting:
    """count_trades uses activity list and counts distinct market titles per range."""

    def test_count_trades_all_distinct_titles(self):
        from app.services.pnl_today import count_trades
        activity = [
            UserActivity(timestamp=1000, type="TRADE", title="Market A", outcome="Yes",
                         side="BUY", size=50.0, usdc_size=50.0, price=0.5),
            UserActivity(timestamp=2000, type="TRADE", title="Market A", outcome="Yes",
                         side="SELL", size=50.0, usdc_size=55.0, price=0.55),
            UserActivity(timestamp=3000, type="TRADE", title="Market B", outcome="No",
                         side="BUY", size=30.0, usdc_size=30.0, price=0.5),
        ]
        assert count_trades(activity, "all") == 2  # A and B are distinct

    def test_multiple_rows_same_market_count_as_one(self):
        import time
        from app.services.pnl_today import count_trades
        now = int(time.time())
        activity = [
            UserActivity(timestamp=now,       type="TRADE",  title="Same Market", outcome="Yes",
                         side="BUY",  size=10.0, usdc_size=10.0, price=0.5),
            UserActivity(timestamp=now - 100, type="TRADE",  title="Same Market", outcome="Yes",
                         side="SELL", size=10.0, usdc_size=11.0, price=0.55),
            UserActivity(timestamp=now - 200, type="REDEEM", title="Same Market", outcome="Yes",
                         side="",     size=10.0, usdc_size=10.0, price=1.0),
        ]
        assert count_trades(activity, "all") == 1

    def test_empty_activity_returns_zero(self):
        from app.services.pnl_today import count_trades
        assert count_trades([], "1w") == 0
        assert count_trades([], "all") == 0

    def test_1d_excludes_yesterday(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from app.services.pnl_today import count_trades
        tz = ZoneInfo("America/New_York")
        midnight = int(datetime.now(tz).replace(
            hour=0, minute=0, second=0, microsecond=0).timestamp())
        activity = [
            UserActivity(timestamp=midnight + 3600, type="TRADE", title="Today Market",
                         outcome="Yes", side="BUY", size=1.0, usdc_size=1.0, price=0.5),
            UserActivity(timestamp=midnight - 3600, type="TRADE", title="Yesterday Market",
                         outcome="Yes", side="BUY", size=1.0, usdc_size=1.0, price=0.5),
        ]
        assert count_trades(activity, "1d") == 1

    def test_trades_from_activity_cache_db(self, isolated_db):
        """DB helper counts distinct titles in activity cache."""
        activities = [
            UserActivity(timestamp=1_700_000_000, type="TRADE", title="Alpha", outcome="Yes",
                         side="BUY",  size=50.0, usdc_size=50.0, price=0.5),
            UserActivity(timestamp=1_700_000_001, type="TRADE", title="Alpha", outcome="Yes",
                         side="SELL", size=50.0, usdc_size=55.0, price=0.55),
            UserActivity(timestamp=1_700_000_002, type="TRADE", title="Beta",  outcome="No",
                         side="BUY",  size=30.0, usdc_size=30.0, price=0.4),
        ]
        isolated_db.upsert_activity_cache(WALLET, activities)
        count = isolated_db.count_trades_from_activity_cache(WALLET, "all")
        assert count == 2  # Alpha and Beta

    def test_trades_from_activity_cache_1w_excludes_old(self, isolated_db):
        import time
        now = int(time.time())
        activities = [
            UserActivity(timestamp=now - 3 * 86400, type="TRADE", title="Recent",
                         outcome="Yes", side="BUY", size=1.0, usdc_size=1.0, price=0.5),
            UserActivity(timestamp=now - 10 * 86400, type="TRADE", title="OldMarket",
                         outcome="Yes", side="BUY", size=1.0, usdc_size=1.0, price=0.5),
        ]
        isolated_db.upsert_activity_cache(WALLET, activities)
        count = isolated_db.count_trades_from_activity_cache(WALLET, "1w")
        assert count == 1  # only "Recent" is within 7 days


# ── Loss accounting: close_type classification ────────────────────────────────

class TestLossAccounting:
    """classify_closed_positions sets close_type using Activity SELL cross-reference."""

    def test_positive_pnl_is_redeemed_win(self):
        from app.services.pnl_today import classify_closed_positions
        p = ResolvedPosition(
            market="M", outcome_held="Yes", winning_outcome="Yes",
            quantity=100.0, cost_basis=50.0, redeem_value=65.0,
            redeemed=True,
        )
        classify_closed_positions([p], [])
        assert p.close_type == "REDEEMED_WIN"

    def test_zero_redeem_value_is_resolved_loss(self):
        from app.services.pnl_today import classify_closed_positions
        p = ResolvedPosition(
            market="M", outcome_held="Yes", winning_outcome="No",
            quantity=100.0, cost_basis=50.0, redeem_value=0.0,
            redeemed=True,
        )
        classify_closed_positions([p], [])
        assert p.close_type == "RESOLVED_LOSS"

    def test_partial_recovery_is_sold(self):
        from app.services.pnl_today import classify_closed_positions
        p = ResolvedPosition(
            market="M", outcome_held="Yes", winning_outcome="No",
            quantity=100.0, cost_basis=50.0, redeem_value=30.0,
            redeemed=True,
        )
        classify_closed_positions([p], [])
        # redeem_value > 0, realized_pnl < 0 → SOLD
        assert p.close_type == "SOLD"

    def test_activity_sell_overrides_to_sold(self):
        from app.services.pnl_today import classify_closed_positions
        p = ResolvedPosition(
            market="Alpha Market", outcome_held="Yes", winning_outcome="No",
            quantity=100.0, cost_basis=50.0, redeem_value=0.0,
            redeemed=True,
        )
        sell_activity = UserActivity(
            timestamp=9999, type="TRADE", title="Alpha Market", outcome="Yes",
            side="SELL", size=100.0, usdc_size=20.0, price=0.2,
        )
        classify_closed_positions([p], [sell_activity])
        # Activity SELL match → SOLD even though redeem_value=0
        assert p.close_type == "SOLD"

    def test_losing_position_no_sell_is_resolved_loss(self):
        from app.services.pnl_today import classify_closed_positions
        p = ResolvedPosition(
            market="Loser", outcome_held="Yes", winning_outcome="No",
            quantity=100.0, cost_basis=50.0, redeem_value=0.0,
            redeemed=True,
        )
        unrelated_sell = UserActivity(
            timestamp=9999, type="TRADE", title="Different Market", outcome="Yes",
            side="SELL", size=100.0, usdc_size=20.0, price=0.2,
        )
        classify_closed_positions([p], [unrelated_sell])
        assert p.close_type == "RESOLVED_LOSS"

    def test_resolved_loss_pnl_equals_negative_cost_basis(self):
        """For a full loss (redeem_value=0), realized_pnl == -cost_basis by formula."""
        p = ResolvedPosition(
            market="M", outcome_held="Yes", winning_outcome="No",
            quantity=100.0, cost_basis=75.0, redeem_value=0.0,
            redeemed=True,
        )
        assert p.realized_pnl == -75.0

    def test_close_type_default_unknown(self):
        """Default close_type before classification is UNKNOWN."""
        p = ResolvedPosition(
            market="M", outcome_held="Yes", winning_outcome="Yes",
            quantity=1.0, cost_basis=50.0, redeem_value=60.0, redeemed=True,
        )
        assert p.close_type == "UNKNOWN"

    def test_classify_runs_on_all_positions(self):
        from app.services.pnl_today import classify_closed_positions
        positions = [
            ResolvedPosition(market="W", outcome_held="Yes", winning_outcome="Yes",
                             quantity=1.0, cost_basis=50.0, redeem_value=60.0, redeemed=True),
            ResolvedPosition(market="L", outcome_held="Yes", winning_outcome="No",
                             quantity=1.0, cost_basis=50.0, redeem_value=0.0,  redeemed=True),
        ]
        classify_closed_positions(positions, [])
        assert positions[0].close_type == "REDEEMED_WIN"
        assert positions[1].close_type == "RESOLVED_LOSS"


# ── Cache preload: load_all_* functions ───────────────────────────────────────

class TestCachePreload:
    def test_load_all_activity_no_limit(self, isolated_db):
        """load_all_activity_for_wallet returns all rows with no row cap."""
        rows = [
            UserActivity(timestamp=i * 100, type="TRADE", title=f"M{i}", outcome="Yes",
                         side="BUY", size=1.0, usdc_size=1.0, price=0.5)
            for i in range(3000)
        ]
        isolated_db.upsert_activity_cache(WALLET, rows)
        loaded = isolated_db.load_all_activity_for_wallet(WALLET)
        assert len(loaded) == 3000

    def test_load_all_closed_no_limit(self, isolated_db):
        """load_all_closed_for_wallet returns all rows with no row cap."""
        positions = [_closed(f"M{i}", cost=float(i + 1), pnl=10.0) for i in range(5000)]
        isolated_db.upsert_closed_positions_cache(positions, WALLET)
        loaded = isolated_db.load_all_closed_for_wallet(WALLET)
        assert len(loaded) == 5000

    def test_load_all_activity_wallet_isolated(self, isolated_db):
        wallet_b = "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB3"
        isolated_db.upsert_activity_cache(WALLET, [
            UserActivity(timestamp=i, type="TRADE", title="MA", outcome="Yes",
                         side="BUY", size=1.0, usdc_size=1.0, price=0.5)
            for i in range(100)
        ])
        isolated_db.upsert_activity_cache(wallet_b, [
            UserActivity(timestamp=i, type="TRADE", title="MB", outcome="Yes",
                         side="BUY", size=1.0, usdc_size=1.0, price=0.5)
            for i in range(50)
        ])
        assert len(isolated_db.load_all_activity_for_wallet(WALLET))   == 100
        assert len(isolated_db.load_all_activity_for_wallet(wallet_b)) == 50

    def test_load_all_closed_wallet_isolated(self, isolated_db):
        wallet_b = "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB4"
        isolated_db.upsert_closed_positions_cache(
            [_closed(f"A{i}", cost=float(i + 1)) for i in range(200)], WALLET)
        isolated_db.upsert_closed_positions_cache(
            [_closed(f"B{i}", cost=float(i + 1)) for i in range(100)], wallet_b)
        assert len(isolated_db.load_all_closed_for_wallet(WALLET))   == 200
        assert len(isolated_db.load_all_closed_for_wallet(wallet_b)) == 100

    def test_load_all_activity_newest_first(self, isolated_db):
        rows = [
            UserActivity(timestamp=i * 100, type="TRADE", title="M", outcome="Yes",
                         side="BUY", size=1.0, usdc_size=1.0, price=0.5)
            for i in range(10)
        ]
        isolated_db.upsert_activity_cache(WALLET, rows)
        loaded = isolated_db.load_all_activity_for_wallet(WALLET)
        timestamps = [a.timestamp for a in loaded]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_activity_dedup_key_includes_title(self, isolated_db):
        """Two events at same ts with different titles must both be stored (new v2 key)."""
        a1 = UserActivity(timestamp=9999, type="TRADE", title="Market A", outcome="Yes",
                          side="BUY", size=50.0, usdc_size=50.0, price=0.5)
        a2 = UserActivity(timestamp=9999, type="TRADE", title="Market B", outcome="Yes",
                          side="BUY", size=50.0, usdc_size=50.0, price=0.5)
        isolated_db.upsert_activity_cache(WALLET, [a1, a2])
        loaded = isolated_db.load_all_activity_for_wallet(WALLET)
        # Both must be stored — old key would have deduped them
        assert len(loaded) == 2
        titles = {a.title for a in loaded}
        assert titles == {"Market A", "Market B"}


# ── filter_activity_by_range ──────────────────────────────────────────────────

class TestFilterActivityByRange:
    def test_all_returns_everything(self):
        from app.services.pnl_today import filter_activity_by_range
        activity = [
            UserActivity(timestamp=1000, type="TRADE", title="M", outcome="Yes",
                         side="BUY",  size=1.0, usdc_size=1.0, price=0.5),
            UserActivity(timestamp=2000, type="TRADE", title="M", outcome="Yes",
                         side="SELL", size=1.0, usdc_size=1.0, price=0.5),
        ]
        assert len(filter_activity_by_range(activity, "all")) == 2

    def test_1d_excludes_yesterday(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from app.services.pnl_today import filter_activity_by_range
        tz = ZoneInfo("America/New_York")
        midnight = int(datetime.now(tz).replace(
            hour=0, minute=0, second=0, microsecond=0).timestamp())
        today_row = UserActivity(timestamp=midnight + 100, type="TRADE", title="T",
                                 outcome="Yes", side="BUY", size=1.0, usdc_size=1.0, price=0.5)
        yest_row  = UserActivity(timestamp=midnight - 100, type="TRADE", title="Y",
                                 outcome="Yes", side="BUY", size=1.0, usdc_size=1.0, price=0.5)
        result = filter_activity_by_range([today_row, yest_row], "1d")
        assert len(result) == 1
        assert result[0].title == "T"

    def test_1w_includes_recent_excludes_old(self):
        import time
        from app.services.pnl_today import filter_activity_by_range
        now = int(time.time())
        a_in  = UserActivity(timestamp=now - 5 * 86400, type="TRADE", title="In",
                             outcome="Yes", side="BUY", size=1.0, usdc_size=1.0, price=0.5)
        a_out = UserActivity(timestamp=now - 9 * 86400, type="TRADE", title="Out",
                             outcome="Yes", side="BUY", size=1.0, usdc_size=1.0, price=0.5)
        result = filter_activity_by_range([a_in, a_out], "1w")
        assert {a.title for a in result} == {"In"}

    def test_empty_input_returns_empty(self):
        from app.services.pnl_today import filter_activity_by_range
        assert filter_activity_by_range([], "1w") == []
