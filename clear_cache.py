#!/usr/bin/env python3
"""Wipe all cached position/activity data so the app repulls from scratch.

Preserves the settings table (saved wallet address).
Run from the tradeledger/ directory, with the app closed.
"""
import os
import sqlite3

db_path = os.path.join(os.path.dirname(__file__), "tradeledger.db")
print(f"DB: {db_path}")

conn = sqlite3.connect(db_path)

tables = [
    "closed_positions_cache",
    "active_positions_cache",
    "resolved_positions_cache",
    "activity_cache",
]

for table in tables:
    try:
        before = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        conn.execute(f"DELETE FROM {table}")
        print(f"  {table}: cleared {before} rows")
    except sqlite3.OperationalError as e:
        print(f"  {table}: skipped ({e})")

conn.commit()
conn.close()
print("Done. Restart the app to repull fresh data.")
