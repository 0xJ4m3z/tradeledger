import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List

from app.models import ActivePosition, ResolvedPosition

DB_PATH = Path(__file__).parent.parent / "tradeledger.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at    TEXT NOT NULL,
                source        TEXT NOT NULL,
                active_count  INTEGER NOT NULL,
                resolved_count INTEGER NOT NULL,
                active_positions   TEXT NOT NULL,
                resolved_positions TEXT NOT NULL
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
                (created_at, source, active_count, resolved_count, active_positions, resolved_positions)
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
