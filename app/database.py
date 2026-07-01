import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from app.models import ActivePosition, ResolvedPosition, UserActivity

# Allow tests to override the path via TRADELEDGER_DB environment variable
_DEFAULT_DB = Path(__file__).parent.parent / "tradeledger.db"
DB_PATH = os.getenv("TRADELEDGER_DB", str(_DEFAULT_DB))


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at     TEXT NOT NULL,
                source         TEXT NOT NULL,
                active_count   INTEGER NOT NULL,
                resolved_count INTEGER NOT NULL,
                active_positions   TEXT NOT NULL,
                resolved_positions TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS wallet_snapshots (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at           TEXT NOT NULL,
                active_positions_value REAL NOT NULL DEFAULT 0.0,
                wallet_usd_value      REAL NOT NULL DEFAULT 0.0,
                total_tracked_value   REAL NOT NULL DEFAULT 0.0,
                unrealized_pnl        REAL NOT NULL DEFAULT 0.0,
                realized_pnl          REAL NOT NULL DEFAULT 0.0,
                wallet_address        TEXT NOT NULL DEFAULT ''
            )
        """)
        # Migration: add wallet_address to existing databases that pre-date this column
        try:
            conn.execute(
                "ALTER TABLE wallet_snapshots ADD COLUMN wallet_address TEXT NOT NULL DEFAULT ''"
            )
        except Exception:
            pass  # column already exists
        # Key-value store for app settings (last wallet, loss watch state, etc.)
        # Never commit this DB — it is gitignored via *.db
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        # Cache for closed positions — accumulates via backfill; deduped by (wallet, position_key)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS closed_positions_cache (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address  TEXT NOT NULL DEFAULT '',
                position_key    TEXT NOT NULL,
                market          TEXT NOT NULL,
                outcome_held    TEXT NOT NULL,
                winning_outcome TEXT NOT NULL,
                quantity        REAL NOT NULL,
                cost_basis      REAL NOT NULL,
                redeem_value    REAL NOT NULL,
                redeemed        INTEGER NOT NULL,
                resolved_date   TEXT,
                realized_pnl    REAL NOT NULL,
                fetched_at      TEXT NOT NULL,
                UNIQUE (wallet_address, position_key)
            )
        """)
        # Migration: add wallet_address to legacy single-column-unique tables
        try:
            conn.execute(
                "ALTER TABLE closed_positions_cache ADD COLUMN wallet_address TEXT NOT NULL DEFAULT ''"
            )
            conn.execute("DROP INDEX IF EXISTS sqlite_autoindex_closed_positions_cache_1")
        except Exception:
            pass
        # Migration: add closed_at (actual close epoch) if not present
        try:
            conn.execute(
                "ALTER TABLE closed_positions_cache ADD COLUMN closed_at INTEGER"
            )
        except Exception:
            pass
        # Migration: rebuild table if the old single-column UNIQUE(position_key) constraint
        # is still present.  That constraint makes inserts fail for any new row whose
        # position_key matches an old empty-wallet row, even when the wallet_address differs.
        # SQLite won't let us drop an autoindex, so we recreate the table with the correct
        # composite UNIQUE(wallet_address, position_key) and reassign orphaned rows.
        try:
            old_constraint = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type='index' AND name='sqlite_autoindex_closed_positions_cache_1' "
                "AND tbl_name='closed_positions_cache'"
            ).fetchone()[0]
            if old_constraint:
                conn.execute("DROP TABLE IF EXISTS _cpc_rebuild_tmp")
                conn.execute("""
                    CREATE TABLE _cpc_rebuild_tmp (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        wallet_address  TEXT NOT NULL DEFAULT '',
                        position_key    TEXT NOT NULL,
                        market          TEXT NOT NULL,
                        outcome_held    TEXT NOT NULL,
                        winning_outcome TEXT NOT NULL,
                        quantity        REAL NOT NULL,
                        cost_basis      REAL NOT NULL,
                        redeem_value    REAL NOT NULL,
                        redeemed        INTEGER NOT NULL,
                        resolved_date   TEXT,
                        closed_at       INTEGER,
                        realized_pnl    REAL NOT NULL,
                        fetched_at      TEXT NOT NULL,
                        UNIQUE (wallet_address, position_key)
                    )
                """)
                conn.execute("""
                    INSERT OR IGNORE INTO _cpc_rebuild_tmp
                        (id, wallet_address, position_key, market, outcome_held,
                         winning_outcome, quantity, cost_basis, redeem_value,
                         redeemed, resolved_date, closed_at, realized_pnl, fetched_at)
                    SELECT id, wallet_address, position_key, market, outcome_held,
                           winning_outcome, quantity, cost_basis, redeem_value,
                           redeemed, resolved_date, closed_at, realized_pnl, fetched_at
                    FROM closed_positions_cache
                """)
                conn.execute("DROP TABLE closed_positions_cache")
                conn.execute(
                    "ALTER TABLE _cpc_rebuild_tmp RENAME TO closed_positions_cache"
                )
                # Reassign orphaned empty-wallet rows to the saved wallet.
                # UPDATE OR IGNORE skips any that would collide with a real-wallet row;
                # DELETE removes the remaining empty-wallet rows (they are duplicates).
                wallet_row = conn.execute(
                    "SELECT value FROM settings WHERE key = 'last_wallet'"
                ).fetchone()
                if wallet_row and wallet_row[0]:
                    actual_wallet = wallet_row["value"]
                    conn.execute(
                        "UPDATE OR IGNORE closed_positions_cache "
                        "SET wallet_address = ? WHERE wallet_address = ''",
                        (actual_wallet,),
                    )
                    conn.execute(
                        "DELETE FROM closed_positions_cache WHERE wallet_address = ''"
                    )
                print(
                    "[MIGRATION] rebuilt closed_positions_cache with composite unique index",
                    flush=True,
                )
        except Exception as _exc:
            print(f"[MIGRATION] rebuild failed (non-fatal): {_exc}", flush=True)
        # Ensure the explicit composite unique index exists (complements the table constraint).
        try:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_closed_wallet_poskey "
                "ON closed_positions_cache(wallet_address, position_key)"
            )
        except Exception:
            pass
        # Migration: dedup existing rows and rewrite position_key to market|outcome_held format.
        # Previously position_key included cost_basis (market|outcome|cost:.6f), which caused
        # two DB rows for the same real-world position when the API and activity-derived sources
        # computed cost_basis slightly differently.  For each (wallet, market, outcome_held)
        # group keep the row with the highest cost_basis (tie-break: highest id), delete the
        # rest, then rewrite all position_keys to the new short format.
        try:
            needs_dedup = conn.execute(
                "SELECT COUNT(*) FROM closed_positions_cache "
                "WHERE position_key LIKE '%|%|%'"
            ).fetchone()[0]
            if needs_dedup:
                conn.execute("""
                    DELETE FROM closed_positions_cache
                    WHERE id NOT IN (
                        SELECT id FROM closed_positions_cache c1
                        WHERE NOT EXISTS (
                            SELECT 1 FROM closed_positions_cache c2
                            WHERE c2.wallet_address = c1.wallet_address
                              AND c2.market         = c1.market
                              AND c2.outcome_held   = c1.outcome_held
                              AND (c2.cost_basis > c1.cost_basis
                                   OR (c2.cost_basis = c1.cost_basis AND c2.id > c1.id))
                        )
                    )
                """)
                conn.execute(
                    "UPDATE closed_positions_cache "
                    "SET position_key = market || '|' || outcome_held"
                )
                print(
                    "[MIGRATION] deduped closed_positions_cache and rewrote position_keys",
                    flush=True,
                )
        except Exception as _exc:
            print(f"[MIGRATION] dedup failed (non-fatal): {_exc}", flush=True)

        # Active positions cache — replaced in full on each successful fetch
        conn.execute("""
            CREATE TABLE IF NOT EXISTS active_positions_cache (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT NOT NULL,
                market         TEXT NOT NULL,
                outcome        TEXT NOT NULL,
                quantity       REAL NOT NULL,
                avg_cost       REAL NOT NULL,
                current_price  REAL NOT NULL,
                saved_at       TEXT NOT NULL
            )
        """)

        # Resolved positions cache — replaced in full on each successful fetch
        conn.execute("""
            CREATE TABLE IF NOT EXISTS resolved_positions_cache (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address  TEXT NOT NULL,
                market          TEXT NOT NULL,
                outcome_held    TEXT NOT NULL,
                winning_outcome TEXT NOT NULL,
                quantity        REAL NOT NULL,
                cost_basis      REAL NOT NULL,
                redeem_value    REAL NOT NULL,
                redeemed        INTEGER NOT NULL,
                resolved_date   TEXT,
                saved_at        TEXT NOT NULL
            )
        """)

        # Activity cache — deduped by (wallet_address, event_key)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS activity_cache (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT NOT NULL,
                event_key      TEXT NOT NULL,
                timestamp      INTEGER NOT NULL,
                type           TEXT NOT NULL,
                title          TEXT NOT NULL,
                outcome        TEXT NOT NULL,
                side           TEXT NOT NULL,
                size           REAL NOT NULL,
                usdc_size      REAL NOT NULL,
                price          REAL NOT NULL,
                cached_at      TEXT NOT NULL,
                UNIQUE (wallet_address, event_key)
            )
        """)
        # Performance indexes for range queries and scroll pagination
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_closed_wallet_closed_at "
            "ON closed_positions_cache(wallet_address, closed_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_activity_wallet_ts "
            "ON activity_cache(wallet_address, timestamp DESC)"
        )
        # Migrate activity cache to v2 dedup key (adds title+outcome to the key).
        # Old key (ts|type|side|size) caused false dedup collisions when different
        # markets shared the same timestamp, type, side, and size, capping the cache
        # at ~2933 rows.  Clear the old rows; the backfill thread will re-hydrate.
        activity_schema = conn.execute(
            "SELECT value FROM settings WHERE key = 'activity_key_schema'"
        ).fetchone()
        if activity_schema is None or activity_schema["value"] < "2":
            conn.execute("DELETE FROM activity_cache")
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) "
                "VALUES ('activity_key_schema', '2')"
            )
        conn.commit()


# ── Legacy snapshot helpers (v0.1) ────────────────────────────────────────────

def save_snapshot(
    source: str,
    active: List[ActivePosition],
    resolved: List[ResolvedPosition],
) -> None:
    active_data = [
        {
            "market": p.market, "outcome": p.outcome, "quantity": p.quantity,
            "avg_cost": p.avg_cost, "current_price": p.current_price,
        }
        for p in active
    ]
    resolved_data = [
        {
            "market": p.market, "outcome_held": p.outcome_held,
            "winning_outcome": p.winning_outcome, "quantity": p.quantity,
            "cost_basis": p.cost_basis, "redeem_value": p.redeem_value,
            "redeemed": p.redeemed, "resolved_date": p.resolved_date,
        }
        for p in resolved
    ]
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO snapshots
                (created_at, source, active_count, resolved_count,
                 active_positions, resolved_positions)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.utcnow().isoformat(), source,
                len(active), len(resolved),
                json.dumps(active_data), json.dumps(resolved_data),
            ),
        )
        conn.commit()


# ── Wallet value snapshots ────────────────────────────────────────────────────

def save_wallet_snapshot(
    wallet_address: str,
    active_positions_value: float,
    wallet_usd_value: float,
    unrealized_pnl: float,
    realized_pnl: float,
) -> None:
    total = round(active_positions_value + wallet_usd_value, 2)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO wallet_snapshots
                (captured_at, active_positions_value, wallet_usd_value,
                 total_tracked_value, unrealized_pnl, realized_pnl, wallet_address)
            VALUES (datetime('now'), ?, ?, ?, ?, ?, ?)
            """,
            (active_positions_value, wallet_usd_value, total,
             unrealized_pnl, realized_pnl, wallet_address),
        )
        conn.commit()


def load_wallet_snapshots(wallet_address: str = "") -> List[dict]:
    """Load wallet snapshots for the given address, oldest first.

    Pass wallet_address="" to load all snapshots regardless of address (avoid
    in the UI — this returns old dummy/sample data too).
    """
    with get_connection() as conn:
        if wallet_address:
            rows = conn.execute(
                """
                SELECT captured_at, active_positions_value, wallet_usd_value,
                       total_tracked_value, unrealized_pnl, realized_pnl
                FROM wallet_snapshots
                WHERE wallet_address = ?
                ORDER BY captured_at ASC
                """,
                (wallet_address,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT captured_at, active_positions_value, wallet_usd_value,
                       total_tracked_value, unrealized_pnl, realized_pnl
                FROM wallet_snapshots
                ORDER BY captured_at ASC
                """
            ).fetchall()
    return [dict(row) for row in rows]


# ── Settings (key-value) ──────────────────────────────────────────────────────

def _save_setting(key: str, value: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        conn.commit()


def _load_setting(key: str, default: str = "") -> str:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else default


# ── Last wallet address ───────────────────────────────────────────────────────

def save_last_wallet(wallet: str) -> None:
    """Persist the last-used wallet address to local DB (gitignored)."""
    _save_setting("last_wallet", wallet)


def load_last_wallet() -> str:
    """Return the last-used wallet address, or '' if none stored."""
    return _load_setting("last_wallet")


# ── Loss Watch acknowledged state ─────────────────────────────────────────────

def save_loss_watch_acknowledged(markets: List[str]) -> None:
    """Store the set of market titles the user has acknowledged as known losses."""
    _save_setting("loss_watch_acknowledged", json.dumps(markets))


def load_loss_watch_acknowledged() -> List[str]:
    """Return list of acknowledged loss market titles."""
    raw = _load_setting("loss_watch_acknowledged", "[]")
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return []


# ── Closed positions cache ────────────────────────────────────────────────────

def _position_key(p: ResolvedPosition) -> str:
    """Deterministic dedup key for a closed position (wallet-independent part).

    Intentionally excludes cost_basis: the API and activity-derived sources compute
    cost_basis slightly differently (API: totalBought×avgPrice with float rounding;
    activity: sum of BUY usdc_size rows).  Including cost_basis caused two DB rows
    for the same real-world position, producing duplicates in the UI and double-
    counted P/L.
    """
    return f"{p.market}|{p.outcome_held}"


def upsert_closed_positions_cache(
    positions: List[ResolvedPosition],
    wallet_address: str = "",
) -> None:
    """Insert or update cached closed positions keyed by (wallet_address, position_key).

    Uses explicit SELECT + INSERT/UPDATE instead of ON CONFLICT so the upsert
    works regardless of which unique indexes exist on the table (the ON CONFLICT
    syntax requires a UNIQUE index on exactly those columns to be present at
    the time the statement executes, which was unreliable across schema versions).
    """
    if not positions:
        return
    with get_connection() as conn:
        for p in positions:
            key = _position_key(p)
            existing = conn.execute(
                "SELECT id FROM closed_positions_cache "
                "WHERE wallet_address = ? AND position_key = ? LIMIT 1",
                (wallet_address, key),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE closed_positions_cache SET "
                    "winning_outcome = ?, quantity = ?, redeem_value = ?, realized_pnl = ?, "
                    "closed_at = COALESCE(?, closed_at), fetched_at = datetime('now') "
                    "WHERE wallet_address = ? AND position_key = ?",
                    (p.winning_outcome, p.quantity, p.redeem_value, p.realized_pnl,
                     p.closed_at, wallet_address, key),
                )
            else:
                conn.execute(
                    "INSERT INTO closed_positions_cache "
                    "(wallet_address, position_key, market, outcome_held, winning_outcome, "
                    "quantity, cost_basis, redeem_value, redeemed, resolved_date, closed_at, "
                    "realized_pnl, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                    (wallet_address, key, p.market, p.outcome_held, p.winning_outcome,
                     p.quantity, p.cost_basis, p.redeem_value, int(p.redeemed),
                     p.resolved_date, p.closed_at, p.realized_pnl),
                )
        conn.commit()


def upsert_activity_derived_closed_positions(
    positions: List[ResolvedPosition],
    wallet_address: str,
) -> int:
    """Insert activity-derived closed positions, skipping any (market, outcome_held)
    that already has a good API-sourced record in the cache.

    If an existing row has cost_basis=0 (stale derivation where REDEEM outcome
    was empty so BUY costs couldn't be matched), it is replaced with the newly
    derived row which now carries a real cost_basis via the per-title fallback.

    Returns the number of rows inserted or corrected.
    """
    if not positions or not wallet_address:
        return 0
    inserted = 0
    with get_connection() as conn:
        for p in positions:
            existing = conn.execute(
                # Match by market only — a wallet cannot hold both sides of the
                # same market, so one row per market is the expected invariant.
                # Matching on outcome_held too would miss stale rows where the
                # REDEEM event had outcome="" (stored as outcome_held="") while
                # the BUY event had outcome="Yes" (stored in earlier rows).
                "SELECT id, cost_basis FROM closed_positions_cache "
                "WHERE wallet_address = ? AND market = ? LIMIT 1",
                (wallet_address, p.market),
            ).fetchone()
            if existing:
                # Replace stale zero-cost rows with the corrected derivation.
                # cost_basis=0 means a prior derivation failed to match BUY costs;
                # if we now have a positive cost, delete and re-insert with correct data.
                if existing["cost_basis"] == 0.0 and p.cost_basis > 0:
                    conn.execute(
                        "DELETE FROM closed_positions_cache WHERE id = ?",
                        (existing["id"],),
                    )
                    # fall through to INSERT below
                else:
                    continue  # has good data; preserve it
            key = _position_key(p)
            conn.execute(
                "INSERT OR IGNORE INTO closed_positions_cache "
                "(wallet_address, position_key, market, outcome_held, winning_outcome, "
                "quantity, cost_basis, redeem_value, redeemed, resolved_date, closed_at, "
                "realized_pnl, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                (wallet_address, key, p.market, p.outcome_held, p.winning_outcome,
                 p.quantity, p.cost_basis, p.redeem_value, int(p.redeemed),
                 p.resolved_date, p.closed_at, p.realized_pnl),
            )
            inserted += 1
        conn.commit()
    return inserted


def load_closed_positions_cache(
    wallet_address: str = "",
    limit: int = 500,
) -> List[ResolvedPosition]:
    """Load cached closed positions for wallet, most-recently-resolved first."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT market, outcome_held, winning_outcome, quantity, cost_basis,
                   redeem_value, redeemed, resolved_date, closed_at
            FROM closed_positions_cache
            WHERE wallet_address = ?
            ORDER BY COALESCE(closed_at, 0) DESC, resolved_date DESC, fetched_at DESC
            LIMIT ?
            """,
            (wallet_address, limit),
        ).fetchall()
    return [
        ResolvedPosition(
            market=r["market"],
            outcome_held=r["outcome_held"],
            winning_outcome=r["winning_outcome"],
            quantity=r["quantity"],
            cost_basis=r["cost_basis"],
            redeem_value=r["redeem_value"],
            redeemed=bool(r["redeemed"]),
            resolved_date=r["resolved_date"],
            closed_at=r["closed_at"],
        )
        for r in rows
    ]


def clear_wallet_snapshots() -> None:
    """Delete all wallet snapshots."""
    with get_connection() as conn:
        conn.execute("DELETE FROM wallet_snapshots")
        conn.commit()


def clear_wallet_snapshots_today(wallet_address: str) -> None:
    """Delete today's snapshots for this wallet (local date).

    Called at the start of each session's first positions fetch so any snapshots
    saved before real position data arrived (using stale sample values) are wiped,
    giving the chart a clean baseline for the current day.
    """
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM wallet_snapshots WHERE wallet_address = ? AND date(captured_at, 'localtime') = date('now', 'localtime')",
            (wallet_address,),
        )
        conn.commit()


def load_closed_positions_cache_page(
    wallet_address: str,
    offset: int,
    limit: int = 50,
) -> List[ResolvedPosition]:
    """Load one page of cached closed positions at offset, newest-first.

    Used by the cache-first scroll handler so the UI can page through the local
    SQLite cache without hitting the API until the cache is exhausted.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT market, outcome_held, winning_outcome, quantity, cost_basis,
                   redeem_value, redeemed, resolved_date, closed_at
            FROM closed_positions_cache
            WHERE wallet_address = ?
            ORDER BY COALESCE(closed_at, 0) DESC, resolved_date DESC, fetched_at DESC
            LIMIT ? OFFSET ?
            """,
            (wallet_address, limit, offset),
        ).fetchall()
    return [
        ResolvedPosition(
            market=r["market"],
            outcome_held=r["outcome_held"],
            winning_outcome=r["winning_outcome"],
            quantity=r["quantity"],
            cost_basis=r["cost_basis"],
            redeem_value=r["redeem_value"],
            redeemed=bool(r["redeemed"]),
            resolved_date=r["resolved_date"],
            closed_at=r["closed_at"],
        )
        for r in rows
    ]


def count_closed_positions_cache(wallet_address: str = "") -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM closed_positions_cache WHERE wallet_address = ?",
            (wallet_address,),
        ).fetchone()
    return row["n"] if row else 0


# ── Active positions cache ────────────────────────────────────────────────────

def save_active_positions_cache(
    wallet_address: str,
    positions: List[ActivePosition],
) -> None:
    """Replace active positions cache for this wallet with the current fetch result."""
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM active_positions_cache WHERE wallet_address = ?",
            (wallet_address,),
        )
        for p in positions:
            conn.execute(
                """
                INSERT INTO active_positions_cache
                    (wallet_address, market, outcome, quantity, avg_cost, current_price, saved_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (wallet_address, p.market, p.outcome, p.quantity, p.avg_cost, p.current_price),
            )
        conn.commit()


def load_active_positions_cache(wallet_address: str) -> List[ActivePosition]:
    """Load cached active positions for wallet. Returns [] if no cache."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT market, outcome, quantity, avg_cost, current_price
            FROM active_positions_cache
            WHERE wallet_address = ?
            ORDER BY market ASC
            """,
            (wallet_address,),
        ).fetchall()
    return [
        ActivePosition(
            market=r["market"],
            outcome=r["outcome"],
            quantity=r["quantity"],
            avg_cost=r["avg_cost"],
            current_price=r["current_price"],
        )
        for r in rows
    ]


# ── Resolved positions cache ──────────────────────────────────────────────────

def save_resolved_positions_cache(
    wallet_address: str,
    positions: List[ResolvedPosition],
) -> None:
    """Replace resolved positions cache for this wallet with the current fetch result."""
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM resolved_positions_cache WHERE wallet_address = ?",
            (wallet_address,),
        )
        for p in positions:
            conn.execute(
                """
                INSERT INTO resolved_positions_cache
                    (wallet_address, market, outcome_held, winning_outcome, quantity,
                     cost_basis, redeem_value, redeemed, resolved_date, saved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (wallet_address, p.market, p.outcome_held, p.winning_outcome,
                 p.quantity, p.cost_basis, p.redeem_value, int(p.redeemed),
                 p.resolved_date),
            )
        conn.commit()


def load_resolved_positions_cache(wallet_address: str) -> List[ResolvedPosition]:
    """Load cached resolved positions for wallet. Returns [] if no cache."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT market, outcome_held, winning_outcome, quantity, cost_basis,
                   redeem_value, redeemed, resolved_date
            FROM resolved_positions_cache
            WHERE wallet_address = ?
            ORDER BY market ASC
            """,
            (wallet_address,),
        ).fetchall()
    return [
        ResolvedPosition(
            market=r["market"],
            outcome_held=r["outcome_held"],
            winning_outcome=r["winning_outcome"],
            quantity=r["quantity"],
            cost_basis=r["cost_basis"],
            redeem_value=r["redeem_value"],
            redeemed=bool(r["redeemed"]),
            resolved_date=r["resolved_date"],
        )
        for r in rows
    ]


# ── Activity cache ────────────────────────────────────────────────────────────

def _activity_event_key(a: UserActivity) -> str:
    """Deterministic dedup key for an activity event.

    Includes title+outcome so two different markets that happen to share the
    same timestamp, type, side, and size are stored as distinct rows (v2 key).
    """
    return f"{a.timestamp}|{a.type}|{a.title}|{a.outcome}|{a.side}|{a.size:.6f}"


def upsert_activity_cache(
    wallet_address: str,
    activity: List[UserActivity],
) -> None:
    """Insert new activity rows for wallet; skip duplicates by event_key."""
    with get_connection() as conn:
        for a in activity:
            key = _activity_event_key(a)
            conn.execute(
                """
                INSERT OR IGNORE INTO activity_cache
                    (wallet_address, event_key, timestamp, type, title, outcome,
                     side, size, usdc_size, price, cached_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (wallet_address, key, a.timestamp, a.type, a.title,
                 a.outcome, a.side, a.size, a.usdc_size, a.price),
            )
        conn.commit()


def load_activity_cache_page(
    wallet_address: str,
    offset: int,
    limit: int = 100,
) -> List[UserActivity]:
    """Load one page of cached activity at offset, newest-first.

    Used by the cache-first scroll handler so the UI can page through the local
    SQLite cache without hitting the API until the cache is exhausted.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT timestamp, type, title, outcome, side, size, usdc_size, price
            FROM activity_cache
            WHERE wallet_address = ?
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
            """,
            (wallet_address, limit, offset),
        ).fetchall()
    return [
        UserActivity(
            timestamp=r["timestamp"],
            type=r["type"],
            title=r["title"],
            outcome=r["outcome"],
            side=r["side"],
            size=r["size"],
            usdc_size=r["usdc_size"],
            price=r["price"],
        )
        for r in rows
    ]


def count_activity_cache(wallet_address: str) -> int:
    """Return total number of cached activity rows for this wallet."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM activity_cache WHERE wallet_address = ?",
            (wallet_address,),
        ).fetchone()
    return row["n"] if row else 0


def load_all_activity_for_wallet(wallet_address: str) -> List[UserActivity]:
    """Load ALL cached activity for wallet, newest first. No row limit."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT timestamp, type, title, outcome, side, size, usdc_size, price
            FROM activity_cache WHERE wallet_address = ?
            ORDER BY timestamp DESC
            """,
            (wallet_address,),
        ).fetchall()
    return [
        UserActivity(
            timestamp=r["timestamp"], type=r["type"], title=r["title"],
            outcome=r["outcome"], side=r["side"], size=r["size"],
            usdc_size=r["usdc_size"], price=r["price"],
        )
        for r in rows
    ]


def load_all_closed_for_wallet(wallet_address: str) -> List[ResolvedPosition]:
    """Load ALL cached closed positions for wallet, newest first. No row limit."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT market, outcome_held, winning_outcome, quantity, cost_basis,
                   redeem_value, redeemed, resolved_date, closed_at
            FROM closed_positions_cache WHERE wallet_address = ?
            ORDER BY COALESCE(closed_at, 0) DESC, resolved_date DESC, fetched_at DESC
            """,
            (wallet_address,),
        ).fetchall()
    return [
        ResolvedPosition(
            market=r["market"], outcome_held=r["outcome_held"],
            winning_outcome=r["winning_outcome"], quantity=r["quantity"],
            cost_basis=r["cost_basis"], redeem_value=r["redeem_value"],
            redeemed=bool(r["redeemed"]), resolved_date=r["resolved_date"],
            closed_at=r["closed_at"],
        )
        for r in rows
    ]


def count_trades_from_activity_cache(wallet_address: str, range_key: str) -> int:
    """Count distinct market titles in activity cache for the given range.

    'Trades' = distinct market windows with any activity in the range.
    """
    if not wallet_address:
        return 0
    since_epoch = _range_start_epoch(range_key)
    with get_connection() as conn:
        if since_epoch is None:
            row = conn.execute(
                "SELECT COUNT(DISTINCT title) AS n FROM activity_cache "
                "WHERE wallet_address = ?",
                (wallet_address,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(DISTINCT title) AS n FROM activity_cache "
                "WHERE wallet_address = ? AND timestamp >= ?",
                (wallet_address, since_epoch),
            ).fetchone()
    return row["n"] if row else 0


def load_activity_for_range(
    wallet_address: str, range_key: str
) -> List[UserActivity]:
    """Load all activity for wallet in the given time range, newest first."""
    since_epoch = _range_start_epoch(range_key)
    with get_connection() as conn:
        if since_epoch is None:
            rows = conn.execute(
                "SELECT timestamp, type, title, outcome, side, size, usdc_size, price "
                "FROM activity_cache WHERE wallet_address = ? ORDER BY timestamp DESC",
                (wallet_address,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT timestamp, type, title, outcome, side, size, usdc_size, price "
                "FROM activity_cache WHERE wallet_address = ? AND timestamp >= ? "
                "ORDER BY timestamp DESC",
                (wallet_address, since_epoch),
            ).fetchall()
    return [
        UserActivity(
            timestamp=r["timestamp"], type=r["type"], title=r["title"],
            outcome=r["outcome"], side=r["side"], size=r["size"],
            usdc_size=r["usdc_size"], price=r["price"],
        )
        for r in rows
    ]


def load_closed_for_range(
    wallet_address: str, range_key: str
) -> List[ResolvedPosition]:
    """Load closed positions for wallet in the given time range, newest first."""
    since_epoch = _range_start_epoch(range_key)
    since_date  = _range_start_date(range_key)
    with get_connection() as conn:
        if since_epoch is None:
            rows = conn.execute(
                "SELECT market, outcome_held, winning_outcome, quantity, cost_basis, "
                "redeem_value, redeemed, resolved_date, closed_at "
                "FROM closed_positions_cache WHERE wallet_address = :w "
                "ORDER BY COALESCE(closed_at, 0) DESC",
                {"w": wallet_address},
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT market, outcome_held, winning_outcome, quantity, cost_basis, "
                "redeem_value, redeemed, resolved_date, closed_at "
                "FROM closed_positions_cache WHERE wallet_address = :w AND" + _RANGE_WHERE +
                " ORDER BY COALESCE(closed_at, 0) DESC",
                {"w": wallet_address, "epoch": since_epoch, "date": since_date},
            ).fetchall()
    return [
        ResolvedPosition(
            market=r["market"], outcome_held=r["outcome_held"],
            winning_outcome=r["winning_outcome"], quantity=r["quantity"],
            cost_basis=r["cost_basis"], redeem_value=r["redeem_value"],
            redeemed=bool(r["redeemed"]), resolved_date=r["resolved_date"],
            closed_at=r["closed_at"],
        )
        for r in rows
    ]


# Aliases for external callers that use the spec-requested names
get_activity_cache_count = count_activity_cache
get_closed_cache_count   = count_closed_positions_cache


def load_activity_cache(
    wallet_address: str,
    limit: int = 500,
) -> List[UserActivity]:
    """Load cached activity for wallet, newest first."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT timestamp, type, title, outcome, side, size, usdc_size, price
            FROM activity_cache
            WHERE wallet_address = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (wallet_address, limit),
        ).fetchall()
    return [
        UserActivity(
            timestamp=r["timestamp"],
            type=r["type"],
            title=r["title"],
            outcome=r["outcome"],
            side=r["side"],
            size=r["size"],
            usdc_size=r["usdc_size"],
            price=r["price"],
        )
        for r in rows
    ]


# ── DB-backed range stat helpers ──────────────────────────────────────────────

def _range_start_epoch(range_key: str) -> Optional[int]:
    """Return the Unix timestamp (ET, midnight-aligned for 1D) for the range start.

    Returns None for 'all' (no time filter).
    """
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/New_York")
    except Exception:
        from datetime import timezone, timedelta as _td
        tz = timezone(_td(hours=-5))

    now   = datetime.now(tz)
    today = now.date()

    if range_key == "1d":
        start = datetime(today.year, today.month, today.day, 0, 0, 0, tzinfo=tz)
    elif range_key == "1w":
        start = now - timedelta(days=7)
    elif range_key == "1m":
        start = now - timedelta(days=30)
    elif range_key == "1y":
        start = now - timedelta(days=365)
    elif range_key == "ytd":
        start = datetime(today.year, 1, 1, 0, 0, 0, tzinfo=tz)
    else:
        return None  # "all" — no filter

    return int(start.timestamp())


def _range_start_date(range_key: str) -> Optional[str]:
    """Return ISO date string (ET) for the range start, for use in resolved_date fallback.

    Returns None for 'all'.  Derived from _range_start_epoch so both stay in sync.
    """
    since = _range_start_epoch(range_key)
    if since is None:
        return None
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/New_York")
    except Exception:
        from datetime import timezone, timedelta as _td
        tz = timezone(_td(hours=-5))
    return datetime.fromtimestamp(since, tz=tz).date().isoformat()


# Common WHERE clause for time-filtered range queries.
# Prefers closed_at (actual close epoch) when set; falls back to resolved_date
# (market end date) for legacy rows that pre-date the closed_at column.
_RANGE_WHERE = """
    (
        (closed_at IS NOT NULL AND closed_at >= :epoch)
        OR (closed_at IS NULL AND resolved_date >= :date)
    )
"""


def compute_pnl_for_range(wallet_address: str, range_key: str) -> float:
    """Sum realized_pnl for closed positions in the range, querying SQLite directly.

    For time-filtered ranges (1D, 1W, …):
      • rows WITH closed_at: filtered by closed_at epoch (correct actual close time)
      • rows WITHOUT closed_at: filtered by resolved_date string (legacy fallback)

    This means legacy rows (inserted before the closed_at column was added) are still
    counted, using the market resolution date as an approximation.

    Bypasses the in-memory scroll list so stats are not capped at 2000 rows.
    """
    if not wallet_address:
        return 0.0
    since_epoch = _range_start_epoch(range_key)
    since_date  = _range_start_date(range_key)
    with get_connection() as conn:
        if since_epoch is None:
            row = conn.execute(
                "SELECT COALESCE(SUM(realized_pnl), 0.0) AS total "
                "FROM closed_positions_cache WHERE wallet_address = :w",
                {"w": wallet_address},
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COALESCE(SUM(realized_pnl), 0.0) AS total "
                "FROM closed_positions_cache WHERE wallet_address = :w AND" + _RANGE_WHERE,
                {"w": wallet_address, "epoch": since_epoch, "date": since_date},
            ).fetchone()
    return round(float(row["total"]), 2) if row else 0.0


def count_closed_for_range(wallet_address: str, range_key: str) -> int:
    """Count closed positions in the range by querying SQLite directly."""
    if not wallet_address:
        return 0
    since_epoch = _range_start_epoch(range_key)
    since_date  = _range_start_date(range_key)
    with get_connection() as conn:
        if since_epoch is None:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM closed_positions_cache WHERE wallet_address = :w",
                {"w": wallet_address},
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM closed_positions_cache "
                "WHERE wallet_address = :w AND" + _RANGE_WHERE,
                {"w": wallet_address, "epoch": since_epoch, "date": since_date},
            ).fetchone()
    return row["n"] if row else 0
