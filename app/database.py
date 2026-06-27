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
        conn.commit()


def save_snapshot(
    source: str,
    active: List[ActivePosition],
    resolved: List[ResolvedPosition],
) -> None:
    active_data = [
        {
            "market": p.market,
            "outcome": p.outcome,
            "quantity": p.quantity,
            "avg_cost": p.avg_cost,
            "current_price": p.current_price,
        }
        for p in active
    ]
    resolved_data = [
        {
            "market": p.market,
            "outcome_held": p.outcome_held,
            "winning_outcome": p.winning_outcome,
            "quantity": p.quantity,
            "cost_basis": p.cost_basis,
            "redeem_value": p.redeem_value,
            "redeemed": p.redeemed,
            "resolved_date": p.resolved_date,
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
                datetime.utcnow().isoformat(),
                source,
                len(active),
                len(resolved),
                json.dumps(active_data),
                json.dumps(resolved_data),
            ),
        )
        conn.commit()


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
