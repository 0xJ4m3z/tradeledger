#!/usr/bin/env python3
"""Run from the tradeledger/ directory to inspect the local SQLite DB state."""
import os
import sqlite3

db_path = os.path.join(os.path.dirname(__file__), "tradeledger.db")
print(f"DB path: {db_path}")
print(f"DB size: {os.path.getsize(db_path):,} bytes")

conn = sqlite3.connect(db_path)

# Closed positions
count = conn.execute("SELECT COUNT(*) FROM closed_positions_cache").fetchone()[0]
print(f"\nclosed_positions_cache: {count} rows total")
for row in conn.execute(
    "SELECT wallet_address, COUNT(*) FROM closed_positions_cache GROUP BY wallet_address"
):
    w = row[0]
    masked = (w[:8] + "..." + w[-4:]) if len(w) > 12 else w
    print(f"  wallet {masked}: {row[1]} rows")

# Indexes
indexes = conn.execute(
    "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='closed_positions_cache'"
).fetchall()
print(f"  indexes: {[r[0] for r in indexes]}")

# Activity
act_count = conn.execute("SELECT COUNT(*) FROM activity_cache").fetchone()[0]
print(f"\nactivity_cache: {act_count} rows total")

conn.close()
