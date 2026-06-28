import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List

from app.models import ActivePosition, ResolvedPosition

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
                realized_pnl          REAL NOT NULL DEFAULT 0.0
            )
        """)
        # Key-value store for app settings (last wallet, loss watch state, etc.)
        # Never commit this DB — it is gitignored via *.db
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        # Cache for closed positions — accumulates via backfill; deduped by position_key
        conn.execute("""
            CREATE TABLE IF NOT EXISTS closed_positions_cache (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                position_key   TEXT UNIQUE NOT NULL,
                market         TEXT NOT NULL,
                outcome_held   TEXT NOT NULL,
                winning_outcome TEXT NOT NULL,
                quantity       REAL NOT NULL,
                cost_basis     REAL NOT NULL,
                redeem_value   REAL NOT NULL,
                redeemed       INTEGER NOT NULL,
                resolved_date  TEXT,
                realized_pnl   REAL NOT NULL,
                fetched_at     TEXT NOT NULL
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
                 total_tracked_value, unrealized_pnl, realized_pnl)
            VALUES (datetime('now'), ?, ?, ?, ?, ?)
            """,
            (active_positions_value, wallet_usd_value, total, unrealized_pnl, realized_pnl),
        )
        conn.commit()


def load_wallet_snapshots() -> List[dict]:
    with get_connection() as conn:
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
    """Deterministic dedup key for a closed position."""
    return f"{p.market}|{p.outcome_held}|{p.cost_basis:.6f}"


def upsert_closed_positions_cache(positions: List[ResolvedPosition]) -> None:
    """Insert or update cached closed positions. Safe to call repeatedly."""
    with get_connection() as conn:
        for p in positions:
            key = _position_key(p)
            conn.execute(
                """
                INSERT INTO closed_positions_cache
                    (position_key, market, outcome_held, winning_outcome, quantity,
                     cost_basis, redeem_value, redeemed, resolved_date, realized_pnl,
                     fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT (position_key) DO UPDATE SET
                    winning_outcome = excluded.winning_outcome,
                    quantity        = excluded.quantity,
                    redeem_value    = excluded.redeem_value,
                    realized_pnl    = excluded.realized_pnl,
                    fetched_at      = excluded.fetched_at
                """,
                (key, p.market, p.outcome_held, p.winning_outcome, p.quantity,
                 p.cost_basis, p.redeem_value, int(p.redeemed),
                 p.resolved_date, p.realized_pnl),
            )
        conn.commit()


def load_closed_positions_cache(limit: int = 500) -> List[ResolvedPosition]:
    """Load cached closed positions, newest first."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT market, outcome_held, winning_outcome, quantity, cost_basis,
                   redeem_value, redeemed, resolved_date
            FROM closed_positions_cache
            ORDER BY fetched_at DESC
            LIMIT ?
            """,
            (limit,),
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


def count_closed_positions_cache() -> int:
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM closed_positions_cache").fetchone()
    return row["n"] if row else 0
