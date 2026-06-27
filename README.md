# TradeLedger

A local, read-only desktop application for tracking wallet-based trading positions, realized and unrealized P/L, active exposure, and performance history.

## Overview

TradeLedger helps you track open positions, review realized and unrealized P/L, and monitor trading history — all locally, without connecting to any exchange or wallet provider.

It loads position data from local files (v0.1) or read-only external APIs (future versions):

- **Active positions** — current value, unrealized P/L per position
- **Resolved positions** — realized P/L, win/loss status, redemption tracking
- **Dashboard summary** — eight key metrics at a glance
- **P/L chart** — cumulative performance over time

**Read-only by design.** This app never requests or stores private keys, seed phrases, wallet signatures, or login credentials. Wallet lookup by address only — no order placement, no transactions, no trading execution.

---

## Tech Stack

| Layer     | Library          |
|-----------|------------------|
| UI        | PySide6 (Qt6)    |
| Storage   | SQLite (sqlite3) |
| Data      | pandas           |
| Charts    | matplotlib       |
| Tests     | pytest           |
| API (v0.2+) | httpx / requests |

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

---

## Run the app

```bash
python run.py
```

The app launches in **sample data mode**. No wallet address or API key is required. Sample positions are loaded from `sample_data/`. Each launch saves a snapshot to `tradeledger.db` (gitignored).

---

## Run tests

```bash
pytest tests/ -v
```

---

## Project structure

```
tradeledger/
├── app/
│   ├── main.py                         # Entry point and app init
│   ├── database.py                     # SQLite snapshot storage
│   ├── models.py                       # ActivePosition, ResolvedPosition dataclasses
│   ├── services/
│   │   ├── pnl.py                      # P/L calculations and cumulative series
│   │   ├── metrics.py                  # Dashboard metric aggregation
│   │   └── positions.py                # Filter and sort helpers
│   ├── adapters/
│   │   ├── sample_adapter.py           # Loads from local JSON (v0.1)
│   │   └── chain_adapter.py            # Stub for future read-only API
│   └── ui/
│       ├── main_window.py              # QMainWindow, tabs, global styles
│       ├── dashboard.py                # Summary metric cards
│       ├── active_positions_table.py   # Active positions with unrealized P/L
│       ├── resolved_positions_table.py # Resolved positions with realized P/L
│       └── pnl_chart.py               # Cumulative P/L chart (matplotlib)
├── tests/
│   ├── test_pnl.py                     # P/L calculation tests
│   ├── test_positions.py               # Filter and sort tests
│   └── test_sample_adapter.py          # Sample data integrity tests
├── sample_data/
│   ├── sample_wallet_positions.json    # Example active positions
│   └── sample_resolved_positions.json  # Example resolved positions
├── conftest.py                         # pytest path setup
├── run.py                              # Launch script
├── requirements.txt
└── README.md
```

---

## Dashboard cards

| Card | Description |
|------|-------------|
| Active Positions Value | Current market value of all open positions |
| Realized P/L | Total profit/loss from resolved positions |
| Unrealized P/L | Floating profit/loss on active positions |
| Total Estimated Value | Active value + realized P/L |
| Win Count | Number of resolved positions that paid out |
| Loss Count | Number of resolved positions that paid zero |
| Largest Win | Highest single realized P/L |
| Largest Loss | Lowest single realized P/L |

---

## v0.1 scope

- [x] Sample data mode (no live API)
- [x] Dashboard summary cards
- [x] Active positions table with unrealized P/L
- [x] Resolved positions table with realized P/L and redemption status
- [x] Cumulative P/L chart
- [x] SQLite snapshot storage
- [x] pytest test suite
- [ ] Live API integration (planned for v0.2)
- [ ] Wallet address input (planned for v0.2)
- [ ] CSV export (planned)
