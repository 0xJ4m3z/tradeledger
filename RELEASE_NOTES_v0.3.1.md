# TradeLedger v0.3.1 — Cache, History, and P/L Accuracy Fixes

## What's new

### Realized P/L accuracy

The most significant fix in this release: **realized P/L figures are now correct**.

Polymarket's `/closed-positions` API returns `totalBought` as the number of shares purchased — not the USDC amount spent. The previous adapter treated it as dollars, which produced inflated cost basis values and incorrect P/L. The corrected calculation is:

```
cost_basis   = totalBought × avgPrice   (USDC actually spent)
redeem_value = cost_basis + realizedPnl  (USDC received on close)
```

For example, a trade with `totalBought=280.39 shares` at `avgPrice=$0.98` now correctly shows `cost_basis=$274.78` and `proceeds=$280.39` — matching the Polymarket activity feed exactly.

### Duplicate closed positions eliminated

The closed-position dedup key previously included `cost_basis`. Because the API and activity-derived sources compute cost_basis slightly differently due to float rounding (`274.782200` vs `274.780000`), the same real-world trade produced two separate database rows, two entries in the Closed Positions tab, and double-counted P/L. The key is now `market|outcome_held` only.

A startup migration deduplicates existing rows in place — no manual action required.

### SQLite cache migration fixes

- **Fixed composite unique constraint** — the closed positions cache now uses `UNIQUE(wallet_address, position_key)`. Older databases had a single-column `UNIQUE(position_key)` constraint that silently blocked all new inserts when any position key already existed.
- **Fixed orphaned rows** — legacy databases contained closed-position rows with an empty wallet address (from before wallet-scoping was added). A startup migration reassigns these rows to the correct wallet.
- **Fixed persistence across restarts** — scroll-loaded and backfill-loaded closed positions now correctly survive app restarts.

### Activity-derived closed positions

The activity feed is used as a supplementary source for closed positions when the `/closed-positions` API page limit is reached. REDEEM events in the activity feed often have an empty `outcome` field. The outcome is now correctly inferred from the corresponding BUY events for the same market. Stale zero-cost rows from earlier derivation passes are replaced when better data becomes available.

### Closed Positions tab and cache

- All closed positions loaded at startup from local SQLite cache — no waiting for a live API fetch
- Activity tab likewise hydrates from cache on startup
- Scroll-loaded pages persist to the database immediately and survive restarts
- Background backfill continues to populate historical pages and cache them locally

### P/L chart

- 1D chart uses actual close timestamps (not resolved dates) for intraday positioning
- Chart anchors at $0 at the range start; final value matches the Realized P/L card exactly
- Same-date positions are aggregated before building the cumulative series

### Range filter

- **1Y and YTD** range buttons added alongside 1D / 1W / 1M / All
- All calendar-day boundaries use **America/New_York (ET)** time
- Realized P/L and Trades cards show a `~` prefix when loaded data may not cover the full selected range

---

## Fixes

- `_to_closed` adapter: `totalBought` correctly interpreted as shares; `cost_basis = totalBought × avgPrice`
- Closed-position dedup key simplified to `market|outcome_held` (previously included `cost_basis`)
- UI in-memory dedup in `append_positions`, `merge_positions`, and `load_from_cache` updated to match
- SQLite closed-positions table rebuilt with correct composite unique index on old databases
- Orphaned empty-wallet rows reassigned to saved wallet address on startup
- `derive_closed_from_activity`: outcome inferred from BUY events when REDEEM has empty outcome field
- `upsert_activity_derived_closed_positions`: stale zero-cost rows replaced instead of skipped
- Same-wallet re-confirmation on startup no longer clears chart data seeded from cache
- Removed temporary always-on `[BACKFILL]`, `[SCROLL-PERSIST]`, `[STARTUP]` console prints

---

## Tests

**433 passing tests** (up from 324 at the start of the v0.3.1 audit branch). New coverage includes:

- `test_cache_hydration.py` — scroll-page persistence, startup hydration, in-memory merge logic, dedup correctness across wallet boundaries
- `test_closed_cache.py` — updated for new dedup key semantics
- `test_polymarket_adapter.py` — updated for correct `totalBought` / `avgPrice` / `realizedPnl` field semantics

---

## Safety

TradeLedger remains strictly read-only:

- No private keys, seed phrases, wallet signatures, or wallet connection permissions — ever
- No order placement, no transactions, no contract calls that write state
- Wallet lookup uses your public address only via public read-only APIs
- All data is stored locally in a gitignored SQLite database (`tradeledger.db`) — never sent to any external server

---

## Upgrading

Pull the latest and run the app. The SQLite migration runs automatically on startup — no manual steps required.

If you want to clear stale cached data and repull fresh:

```bash
python3 clear_cache.py
```

This wipes all position and activity cache tables while preserving your saved wallet address.
