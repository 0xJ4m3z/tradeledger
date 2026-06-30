import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List

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
    """Deterministic dedup key for a closed position (wallet-independent part)."""
    return f"{p.market}|{p.outcome_held}|{p.cost_basis:.6f}"


def upsert_closed_positions_cache(
    positions: List[ResolvedPosition],
    wallet_address: str = "",
) -> None:
    """Insert or update cached closed positions keyed by (wallet_address, position_key)."""
    with get_connection() as conn:
        for p in positions:
            key = _position_key(p)
            conn.execute(
                """
                INSERT INTO closed_positions_cache
                    (wallet_address, position_key, market, outcome_held, winning_outcome,
                     quantity, cost_basis, redeem_value, redeemed, resolved_date, closed_at,
                     realized_pnl, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT (wallet_address, position_key) DO UPDATE SET
                    winning_outcome = excluded.winning_outcome,
                    quantity        = excluded.quantity,
                    redeem_value    = excluded.redeem_value,
                    realized_pnl    = excluded.realized_pnl,
                    closed_at       = COALESCE(excluded.closed_at, closed_positions_cache.closed_at),
                    fetched_at      = excluded.fetched_at
                """,
                (wallet_address, key, p.market, p.outcome_held, p.winning_outcome,
                 p.quantity, p.cost_basis, p.redeem_value, int(p.redeemed),
                 p.resolved_date, p.closed_at, p.realized_pnl),
            )
        conn.commit()


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
    """Deterministic dedup key for an activity event."""
    return f"{a.timestamp}|{a.type}|{a.side}|{a.size:.6f}"


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
