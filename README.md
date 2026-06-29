# TradeLedger

A local, read-only desktop application for tracking Polymarket positions, wallet balance, and total account value.

## Overview

TradeLedger lets you monitor your open positions, resolved winnings, closed trade history, and activity feed — all locally, using public read-only APIs. No account login, no API key, no wallet connection required.

- **Overview** — wallet lookup, time-range filter (1D / 1W / 1M / All), metric cards (Total Tracked Value, Wallet USD Value, Positions Value, Loss Watch, Realized P/L, Trades), Total Tracked Value mini chart, live positions grid
- **Loss Watch** — list of open positions with negative unrealized P/L; acknowledge known losers to track new ones
- **Active Positions** — all open positions currently exposed to market movement
- **Resolved Positions** — won/resolved markets not yet redeemed; still counted in Positions Value
- **Closed Positions** — fully settled trades (redeemed or sold), with infinite scroll to load history
- **Activity** — full activity feed (trades, redeems, rewards, etc.), searchable, with infinite scroll
- **Total Tracked Value** — full-size chart with 1D / 1W / 1M / All range buttons

**Read-only by design.** TradeLedger never asks for private keys, seed phrases, wallet signatures, or wallet connection permissions. Wallet lookup uses your public address only — no order placement, no transactions, no trading of any kind.

---

## Screenshots

![TradeLedger v0.3 Overview](docs/screenshots/tradeledger_v0.3_overview.png)

---

## Terminology

| Term | Definition |
|------|------------|
| **Active Positions** | Positions in unresolved markets; still exposed to price movement |
| **Resolved Positions** | Won/resolved positions pending redemption; still counted in Positions Value |
| **Closed Positions** | Fully settled positions (redeemed or sold); historical only |
| **Positions Value** | Current value of Active + Resolved positions combined |
| **Total Tracked Value** | Wallet USD Value + Positions Value |
| **Realized P/L** | Net profit/loss from closed positions in the selected time range |

---

## Tech Stack

| Layer     | Library          |
|-----------|------------------|
| UI        | PySide6 (Qt6)    |
| Storage   | SQLite (sqlite3) |
| Data      | pandas           |
| Charts    | matplotlib       |
| HTTP      | requests         |
| Tests     | pytest           |

---

## Setup

### 1. Clone

```bash
git clone https://github.com/0xJ4m3z/tradeledger.git
cd tradeledger
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment (optional)

```bash
cp .env.example .env
# Edit .env if you want a custom Polygon RPC endpoint
```

No API key is required. Wallet lookup uses public Polygon RPCs; position and activity lookup use the public Polymarket Data API.

---

## Run the app

```bash
python run.py
```

The app launches in **sample data mode** — positions are loaded from `sample_data/`. Each launch saves a snapshot to `tradeledger.db` (gitignored).

To load live data: enter your Polygon wallet address in the Overview panel and click **Fetch Wallet Value**. This fetches your stablecoin balance, open positions, resolved positions, closed positions, and activity feed in one pass. The button becomes **Refresh** after the first successful fetch. Your wallet address is masked in the UI (`0x1234...abcde`) after a successful fetch.

**Your wallet address is remembered.** On next launch the masked address prefills automatically and a live fetch starts immediately. Address is stored only in the local `tradeledger.db` file (gitignored).

**Auto-refresh (optional).** Enable the "Auto-refresh every 5 min" checkbox to keep data current. The last-updated time is shown next to the checkbox. Refreshes merge new data without wiping scroll-loaded history.

---

## Run tests

```bash
pytest tests/ -v
```

All tests use mocked network calls — no live API access required.

---

## Project structure

```
tradeledger/
├── app/
│   ├── main.py                         # Entry point and app init
│   ├── database.py                     # SQLite: snapshots, settings, closed positions cache
│   ├── models.py                       # ActivePosition, ResolvedPosition, UserActivity dataclasses
│   ├── services/
│   │   ├── pnl.py                      # P/L calculations and cumulative series
│   │   ├── pnl_today.py                # Range-aware realized P/L from closed positions
│   │   ├── metrics.py                  # Dashboard metric aggregation, Total Tracked Value
│   │   ├── loss_watch.py               # Loss Watch: filter losing positions, count unacknowledged
│   │   ├── positions.py                # Filter and sort helpers
│   │   └── chart_ranges.py             # filter_snapshots_by_range (1D/1W/1M/All)
│   ├── adapters/
│   │   ├── sample_adapter.py           # Loads from local JSON (sample data)
│   │   ├── wallet_adapter.py           # Read-only Polygon stablecoin balance lookup
│   │   ├── polymarket_adapter.py       # Read-only Polymarket position + activity lookup
│   │   └── chain_adapter.py            # Stub for future read-only chain API
│   └── ui/
│       ├── main_window.py              # QMainWindow, tabs, global styles
│       ├── overview.py                 # Overview tab: range filter, cards, chart, positions grid
│       ├── wallet_panel.py             # Wallet input, fetch/refresh, auto-refresh, background threads
│       ├── total_value_chart.py        # Total Tracked Value chart widget (with range buttons)
│       ├── active_positions_table.py   # Active Positions tab with search filter
│       ├── resolved_positions_table.py # Resolved / Closed Positions tabs with infinite scroll
│       ├── activity_table.py           # Activity tab with infinite scroll and color-coded types
│       └── loss_watch_tab.py           # Loss Watch tab with acknowledge controls
├── tests/
│   ├── test_pnl.py                     # P/L calculation tests
│   ├── test_pnl_today.py               # Range-aware realized P/L tests
│   ├── test_positions.py               # Filter and sort tests
│   ├── test_sample_adapter.py          # Sample data integrity tests
│   ├── test_metrics_v2.py              # Total Tracked Value calculation tests
│   ├── test_wallet_adapter.py          # Wallet lookup tests (mocked network)
│   ├── test_wallet_snapshot.py         # Wallet snapshot storage and address isolation tests
│   ├── test_wallet_persistence.py      # Last wallet and Loss Watch acknowledgement persistence
│   ├── test_polymarket_adapter.py      # Polymarket position + activity lookup tests (mocked)
│   ├── test_closed_cache.py            # Closed positions cache: upsert, dedup, limit tests
│   ├── test_loss_watch.py              # Loss Watch filter and count tests
│   └── test_chart_ranges.py            # Chart range filter tests
├── sample_data/
│   ├── sample_wallet_positions.json    # Example active positions
│   └── sample_resolved_positions.json  # Example resolved positions
├── docs/
│   └── screenshots/
│       └── tradeledger_v0.2_overview.png
├── .env.example                        # Environment variable template
├── conftest.py                         # pytest path setup
├── run.py                              # Launch script
├── requirements.txt
└── README.md
```

---

## Overview cards

| Card | Description |
|------|-------------|
| Total Tracked Value | Wallet USD Value + Positions Value |
| Wallet USD Value | Polygon wallet USDC.e + pUSD balance (live, read-only) |
| Positions Value | Current value of all Active + Resolved positions |
| Loss Watch | Count of open positions with negative unrealized P/L that have not been acknowledged. "Acknowledge All" marks current losers as known; new losers still appear. |
| Realized P/L | Net profit/loss from closed positions in the selected time range (1D / 1W / 1M / All). Uses `redeem_value − cost_basis` so losses (redeem at $0) are correctly counted. |
| Trades | Number of closed positions in the selected time range |

The **1D / 1W / 1M / All** range buttons above the cards and chart control all three at once: the closed positions grid in the overview, the Realized P/L card, and the Trades card.

---

## Wallet and position lookup

TradeLedger fetches data using public, read-only APIs — no authentication required:

- **Wallet USD value** — sum of USDC.e + pUSD balances via Polygon JSON-RPC `balanceOf()` calls
- **Active positions** — all open positions via `data-api.polymarket.com/positions`
- **Resolved positions** — won markets pending redemption via the same endpoint
- **Closed positions** — fully settled trades via `data-api.polymarket.com/closed-positions`; initial 100 on fetch, then infinite scroll in the Closed Positions tab; a background thread backfills older pages and caches them locally
- **Activity feed** — recent activity events via `data-api.polymarket.com/activity`; initial 100 on fetch, then infinite scroll loads more as you scroll down

Tries multiple public Polygon RPCs automatically if one fails. Wallet address is masked in the UI after a successful fetch. The last-used address is saved locally (gitignored SQLite DB) so it prefills on the next launch.

**Refresh behavior:** auto-refresh and manual refresh only prepend new records — existing scroll-loaded data is preserved. Switching range buttons or waiting for backfill to complete does not reset loaded history.

---

## Privacy and safety

- **Read-only only.** No order placement, no transactions, no contract calls that write state.
- **Public address only.** TradeLedger never asks for private keys, seed phrases, wallet signatures, or wallet connection permissions.
- **No secrets committed.** `.env`, local database files (`*.db`), and virtual environments are gitignored.
- **Address masking.** After a successful fetch, the wallet address is displayed in shortened form (`0x1234...abcde`) in the UI.
- **Local storage only.** The wallet address is stored only in the gitignored local `tradeledger.db` file — never sent to any TradeLedger server (there is none).

---

## Roadmap

**v0.1 — Sample dashboard** ✓
- Sample data mode (no live API or wallet required)
- Overview tab: metric cards, active and resolved position lists
- Individual tabs for Active Positions and Resolved Positions with search filter
- Local SQLite snapshot storage
- pytest test suite

**v0.2 — Live wallet + position + activity tracking** ✓
- Read-only Polygon wallet value (USDC.e + pUSD, no API key required)
- Live Polymarket position lookup: active, resolved, closed (most recent 100)
- Activity tab: full activity feed (trades, redeems, rewards, etc.), searchable
- Total Tracked Value = Wallet USD Value + Positions Value
- Total Tracked Value Over Time chart with 1D / 1W / 1M / All range buttons
- Full-size Total Tracked Value chart tab
- Wallet address masked in UI after fetch for privacy
- 130 passing tests

**v0.3 — Daily monitoring** ✓
- **Remembered wallet address** — prefills masked on next launch; immediate auto-fetch on startup
- **Auto-refresh** — optional 5-minute auto-refresh checkbox; shows last-updated timestamp
- **Loss Watch tab and card** — open positions with negative unrealized P/L; "Acknowledge All" button
- **Realized P/L card** — net profit/loss from closed positions using `redeem_value − cost_basis`; correctly counts losses where winning outcome pays $0
- **Trades card** — count of closed positions in the selected range
- **1D / 1W / 1M / All range filter** — controls overview closed positions grid, Realized P/L, and Trades cards simultaneously
- **Active / Resolved / Closed terminology** — positions are exactly one of: active (open), resolved (won, not yet redeemed), or closed (settled); never shown in two categories at once
- **Resolved Positions tab** — shows won markets pending redemption; counted in Positions Value
- **Closed positions infinite scroll** — Closed Positions tab loads more pages on scroll-to-bottom, identical to Activity tab
- **Activity infinite scroll** — Activity tab loads additional pages as you scroll down
- **Background backfill** — closed position history is fetched in the background and cached locally (SQLite); cache survives restarts
- **Merge-on-refresh** — refresh prepends new records without wiping scroll-loaded data; range filters continue working on the full loaded history
- **REDEEM event display** — Activity tab shows Win/Loss for REDEEM events (Polymarket API returns empty outcome/side for redeems)
- **Wallet-address-tagged snapshots** — chart never shows data from a different wallet; stale same-day snapshots are cleared on first fetch
- 196 passing tests

**v0.4 — Planned**
- Notes per market
- Export to CSV
- Cumulative realized P/L chart
- No trading execution, no order placement, no private key storage
