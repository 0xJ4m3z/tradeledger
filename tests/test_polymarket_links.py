"""
Tests for v0.4.0 Polymarket market-link feature.

Covers:
- polymarket_url_for_slug helper
- Adapter slug capture (eventSlug / slug fallback)
- Database migration safety (slug column added idempotently)
- Store, load, and update_slugs_for_positions DB operations
- Backfill non-destructive behaviour (existing slugs are preserved)
"""

from unittest.mock import MagicMock, patch

import pytest

from app.models import ResolvedPosition
from app.services.polymarket_links import polymarket_url_for_slug


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _rpos(
    market: str = "Test Market",
    outcome: str = "Yes",
    cost: float = 100.0,
    pnl: float = 10.0,
    slug: str | None = None,
    closed_at: int | None = None,
) -> ResolvedPosition:
    return ResolvedPosition(
        market=market,
        outcome_held=outcome,
        winning_outcome=outcome if pnl >= 0 else "No",
        quantity=1_000.0,
        cost_basis=cost,
        redeem_value=cost + pnl,
        redeemed=True,
        resolved_date="2025-06-01",
        closed_at=closed_at,
        slug=slug,
    )


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch, tmp_path):
    db_file = str(tmp_path / "test_links.db")
    monkeypatch.setattr("app.database.DB_PATH", db_file)
    import app.database as db
    db.init_db()
    yield db


_WALLET = "0x" + "b" * 40


# ── URL helper ─────────────────────────────────────────────────────────────────

class TestPolymarketUrlForSlug:
    def test_returns_url_for_valid_slug(self):
        assert polymarket_url_for_slug("will-btc-hit-100k") == \
            "https://polymarket.com/event/will-btc-hit-100k"

    def test_returns_none_for_none(self):
        assert polymarket_url_for_slug(None) is None

    def test_returns_none_for_empty_string(self):
        assert polymarket_url_for_slug("") is None

    def test_slug_with_numbers_and_hyphens(self):
        slug = "will-eth-reach-5000-by-2025-12-31"
        assert polymarket_url_for_slug(slug) == f"https://polymarket.com/event/{slug}"

    def test_url_starts_with_base(self):
        url = polymarket_url_for_slug("any-slug")
        assert url is not None
        assert url.startswith("https://polymarket.com/event/")


# ── Adapter slug capture ───────────────────────────────────────────────────────

class TestAdapterSlugCapture:
    """Verify _to_closed() picks up slug from the API row."""

    def _make_response(self, data):
        m = MagicMock()
        m.raise_for_status.return_value = None
        m.json.return_value = data
        return m

    def _closed_row(self, **kwargs):
        base = {
            "title": "Test Market",
            "outcome": "Yes",
            "oppositeOutcome": "No",
            "avgPrice": "0.8",
            "totalBought": "100",
            "realizedPnl": "20",
            "timestamp": "1735689600",
            "endDate": "2025-01-01",
        }
        base.update(kwargs)
        return base

    def test_captures_event_slug(self):
        from app.adapters.polymarket_adapter import fetch_closed_positions_page
        row = self._closed_row(eventSlug="will-btc-hit-100k")
        with patch("app.adapters.polymarket_adapter._get_with_retry",
                   return_value=self._make_response([row])):
            positions = fetch_closed_positions_page(_WALLET, 0)
        assert len(positions) == 1
        assert positions[0].slug == "will-btc-hit-100k"

    def test_falls_back_to_slug_field(self):
        from app.adapters.polymarket_adapter import fetch_closed_positions_page
        row = self._closed_row(slug="fallback-slug")
        with patch("app.adapters.polymarket_adapter._get_with_retry",
                   return_value=self._make_response([row])):
            positions = fetch_closed_positions_page(_WALLET, 0)
        assert positions[0].slug == "fallback-slug"

    def test_event_slug_takes_priority_over_slug(self):
        from app.adapters.polymarket_adapter import fetch_closed_positions_page
        row = self._closed_row(eventSlug="primary-slug", slug="secondary-slug")
        with patch("app.adapters.polymarket_adapter._get_with_retry",
                   return_value=self._make_response([row])):
            positions = fetch_closed_positions_page(_WALLET, 0)
        assert positions[0].slug == "primary-slug"

    def test_slug_is_none_when_absent(self):
        from app.adapters.polymarket_adapter import fetch_closed_positions_page
        row = self._closed_row()
        with patch("app.adapters.polymarket_adapter._get_with_retry",
                   return_value=self._make_response([row])):
            positions = fetch_closed_positions_page(_WALLET, 0)
        assert positions[0].slug is None


# ── Database migration safety ──────────────────────────────────────────────────

class TestDatabaseMigration:
    def test_init_db_is_idempotent(self, isolated_db):
        """Calling init_db() twice must not raise (slug column already exists)."""
        isolated_db.init_db()   # second call
        isolated_db.init_db()   # third call — still fine

    def test_slug_column_exists_after_init(self, isolated_db):
        """Verify the slug column is present in the schema."""
        with isolated_db.get_connection() as conn:
            row = conn.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type='table' AND name='closed_positions_cache'"
            ).fetchone()
        assert row is not None
        assert "slug" in row["sql"]


# ── Store and load slug ────────────────────────────────────────────────────────

class TestStoreAndLoadSlug:
    def test_slug_stored_on_upsert(self, isolated_db):
        p = _rpos(slug="my-slug")
        isolated_db.upsert_closed_positions_cache([p], _WALLET)
        loaded = isolated_db.load_closed_positions_cache(_WALLET)
        assert loaded[0].slug == "my-slug"

    def test_null_slug_stored_as_none(self, isolated_db):
        p = _rpos(slug=None)
        isolated_db.upsert_closed_positions_cache([p], _WALLET)
        loaded = isolated_db.load_closed_positions_cache(_WALLET)
        assert loaded[0].slug is None

    def test_existing_slug_preserved_on_upsert(self, isolated_db):
        p = _rpos(slug="original-slug")
        isolated_db.upsert_closed_positions_cache([p], _WALLET)

        # Upsert same position with a different (falsy) slug — should NOT overwrite
        p_no_slug = _rpos(slug=None)
        isolated_db.upsert_closed_positions_cache([p_no_slug], _WALLET)

        loaded = isolated_db.load_closed_positions_cache(_WALLET)
        assert loaded[0].slug == "original-slug"


# ── update_slugs_for_positions ─────────────────────────────────────────────────

class TestUpdateSlugsForPositions:
    def test_updates_null_slug_rows(self, isolated_db):
        p = _rpos(slug=None)
        isolated_db.upsert_closed_positions_cache([p], _WALLET)

        p_with_slug = _rpos(slug="new-slug")
        updated = isolated_db.update_slugs_for_positions([p_with_slug], _WALLET)
        assert updated == 1

        loaded = isolated_db.load_closed_positions_cache(_WALLET)
        assert loaded[0].slug == "new-slug"

    def test_does_not_overwrite_existing_slug(self, isolated_db):
        p = _rpos(slug="keep-this")
        isolated_db.upsert_closed_positions_cache([p], _WALLET)

        p_new = _rpos(slug="different-slug")
        updated = isolated_db.update_slugs_for_positions([p_new], _WALLET)
        assert updated == 0

        loaded = isolated_db.load_closed_positions_cache(_WALLET)
        assert loaded[0].slug == "keep-this"

    def test_skips_positions_with_no_slug(self, isolated_db):
        p = _rpos(slug=None)
        isolated_db.upsert_closed_positions_cache([p], _WALLET)

        updated = isolated_db.update_slugs_for_positions([_rpos(slug=None)], _WALLET)
        assert updated == 0

    def test_returns_zero_on_empty_list(self, isolated_db):
        assert isolated_db.update_slugs_for_positions([], _WALLET) == 0

    def test_does_not_delete_any_rows(self, isolated_db):
        positions = [_rpos(f"Market {i}", slug=None) for i in range(5)]
        isolated_db.upsert_closed_positions_cache(positions, _WALLET)

        isolated_db.update_slugs_for_positions(
            [_rpos(f"Market {i}", slug=f"slug-{i}") for i in range(5)],
            _WALLET,
        )

        assert isolated_db.count_closed_positions_cache(_WALLET) == 5

    def test_count_null_slug_positions(self, isolated_db):
        p_null = _rpos("A", slug=None)
        p_slug = _rpos("B", outcome="No", slug="some-slug")
        isolated_db.upsert_closed_positions_cache([p_null, p_slug], _WALLET)

        null_count = isolated_db.count_null_slug_positions(_WALLET)
        assert null_count == 1
