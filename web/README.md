# TradeLedger Web

A FastAPI web version of TradeLedger, built on top of the *exact same*
business logic, models, and SQLite data layer as the PySide6 desktop app —
see the "Architecture" section below for what's shared and what's new.

Starts in **sample data mode** (bundled fixtures, no network needed) and
switches to **live mode** the moment you enter a real Polygon wallet address
in the wallet bar at the top of any page — same read-only, public-address-only
model as the desktop app: no private keys, no signatures, no transactions.

## Run it

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r web/requirements.txt   # self-contained: no PySide6/matplotlib needed
python run_web.py
```

(If you're also working on the desktop app in the same venv, `pip install -r
requirements.txt` too — the two dependency lists don't conflict.)

Then open http://127.0.0.1:8000

On first run the app seeds the bundled `sample_data/` fixtures into a
dedicated SQLite file, `tradeledger_web.db` (gitignored, separate from the
desktop app's `tradeledger.db` — see below). No network access, no wallet
address, and no API key are required to start.

Enter a real Polygon wallet address into the wallet bar (top of any page) and
click **Fetch Wallet Value** to switch to live mode — it fetches your
stablecoin balance, open positions, resolved positions, closed positions, and
activity in one request, exactly like the desktop app's first launch. Click
**Refresh** afterwards to re-fetch the same wallet, or let it happen on its
own — auto-refresh is on by default in live mode (see below).

## Pages

| Route | Description |
|---|---|
| `/?range=1d\|1w\|1m\|1y\|ytd\|all` | Dashboard — range-filtered metric cards (Total Tracked Value, Wallet USD, Positions Value, Loss Watch, Realized P/L, Trades, Win/Loss), cumulative P/L chart, previews of Active/Closed positions |
| `/positions/active` | All open positions, filterable by market name |
| `/positions/resolved` | Won positions pending redemption (empty in sample mode — see note below) |
| `/positions/closed` | Fully settled positions (redeemed or resolved to $0) |
| `/positions/{kind}/{index}` | Position detail (asset info, cost basis, P/L, win/loss, Polymarket link if available) |
| `/pnl?range=1d\|1w\|1m\|1y\|ytd\|all` | Range-filtered realized P/L, cumulative chart, daily breakdown |
| `/total-tracked-value?range=...` | Total Tracked Value history chart + snapshot table |
| `POST /wallet/refresh` | Form target for the wallet bar — fetch a new address, or re-fetch the current one if `address` is blank |

### Dashboard range filter

The same 1D/1W/1M/1Y/YTD/All buttons as the desktop Overview tab, controlling
the Realized P/L, Trades, and Win/Loss cards, the cumulative P/L chart, and
the "Recently Closed" preview grid all at once (matches the desktop's
documented range-bar behavior). Total Tracked Value, Wallet USD Value,
Positions Value, and Loss Watch are range-independent, same as the desktop.

### Auto-refresh

Live mode only (nothing to refresh in sample mode). A checkbox next to the
wallet bar, **on by default**, refreshes the current wallet every 5 minutes —
same default as the desktop app since v0.3.2. Your on/off choice is
remembered in `localStorage`. Unlike the manual **Refresh** button (which
navigates to the dashboard so you see the confirmation banner), auto-refresh
reloads whichever page you're currently on in place, so it never interrupts
what you're looking at. "Last updated" next to the checkbox shows the most
recent successful fetch.

### Right-click Polymarket links

Right-click (or Ctrl/Cmd+click) any position row, in any table, or the
position detail page, to open that market's real Polymarket page in a new
tab — mirrors the desktop app's context-menu convention
(`app/ui/polymarket_menu.py`) across every table. If a position has no
captured slug (e.g. the bundled sample fixtures, which predate slug capture —
see below), the menu still appears but says so, rather than silently doing
nothing. The detail page also shows a visible **Open on Polymarket ↗** link
when a slug is available. The URL itself is always built server-side via
`app.services.polymarket_links.polymarket_url_for_slug` — the click-handling
JS (`static/js/polymarket_link.js`) only ever reads a pre-built URL out of a
`data-polymarket-url` attribute, never constructs one itself.

**Bug fixed along the way:** `active_positions_cache` and
`resolved_positions_cache` never had a `slug` column — only
`closed_positions_cache` did (added in the desktop app's v0.4.0). That's
invisible in the desktop app within a single session (its UI holds the
freshly-fetched in-memory objects, slug intact) but meant the slug was
silently dropped on every save/load round-trip through those two tables —
which is all the stateless web app ever does. Fixed in `app/database.py`
with the same migration-safe `ALTER TABLE` pattern already used for
`closed_positions_cache`, so the desktop app benefits too. Covered by new
regression tests in `tests/test_position_cache.py`.

## Architecture

```
app/                      ← existing desktop app — UNCHANGED except two additive extractions:
  services/refresh.py     ←   framework-agnostic port of _FetchThread's fetch/cache orchestration
  services/wallet_display.py ← the address-masking one-liner, promoted out of app/ui/wallet_panel.py
web/
  config.py     ← points app.database at a separate SQLite file; current_wallet() resolution
  bootstrap.py  ← one-time seed of sample_data/ into the shared cache tables
  data.py       ← composes app.database loaders + app.services pure functions per page
  charts.py     ← shapes chart data for the frontend (still just app.services.pnl_series)
  main.py       ← FastAPI app, routing, 404 handling
  routers/      ← one module per page group (wallet.py = the refresh form handler)
  templates/    ← Jinja2, server-rendered
  static/       ← plain CSS + vanilla JS (no build step, no React)
```

**Nothing pre-existing in `app/` was modified** — `app/services/refresh.py`
and `app/services/wallet_display.py` are new, additive modules, not edits to
existing files. The web app imports `app.models`, `app.services.*`,
`app.adapters.*`, and `app.database` directly — the same P/L math, range
filters, loss-watch logic, live-fetch adapters, and SQLite schema the desktop
app uses. The (now 633) tests in `tests/` cover that layer, including the new
orchestration (`tests/test_refresh.py`, mocked — no live network in the
default suite).

### How "current wallet" works

Single-tenant, matching the desktop app: `web/config.py`'s `current_wallet()`
reads the same `last_wallet` setting the desktop app persists
(`app.database.load_last_wallet()`). `web/bootstrap.py` seeds sample data
under the placeholder address `"sample"` and marks it as the last wallet on
first boot, so a fresh install starts in sample mode with no special-casing
anywhere else in the app. The moment `POST /wallet/refresh` succeeds for a
real address, it calls `save_last_wallet()`, and every route picks up the
new wallet on its next request — no session/cookie state to manage.

### Live fetch scope

`app/services/refresh.py` fetches the same *initial* page of data the
desktop app shows on first launch, before its background `_BackfillThread`
kicks in: wallet balance, all active/resolved positions, the most recent 100
closed positions, and the most recent 100 activity events. Each of the three
phases (wallet balance / positions / activity) fails independently — e.g. if
every public Polygon RPC is down, you still get your Polymarket positions,
and the dashboard shows Wallet USD Value as $0 with an error banner rather
than losing the whole refresh. Deep-history backfill (paging through
thousands of older closed positions in the background, like the desktop
app's `_BackfillThread`) isn't implemented yet — a natural next increment.

### Why `/positions/resolved` is empty in sample mode

`sample_data/sample_resolved_positions.json` predates the current
Active/Resolved/Closed three-way split — every position in it already has a
`resolved_date` and is either redeemed-for-value or resolved to $0, i.e. it's
"Closed" by today's terminology, not "Resolved" (won, pending redemption).
`web/bootstrap.py` seeds it into `closed_positions_cache` accordingly. This
means `/positions/resolved` is a genuine, honest empty state rather than
fabricated filler data — and doubles as a real Phase 2 test fixture for
"empty state" coverage.

### Chart implementation

Both charts are hand-rolled SVG (`static/js/linechart.js`), not a charting
library — data points are real DOM nodes (`data-testid="chart-point"`,
`data-date`, `data-value`) rather than canvas pixels, which matters for
Playwright assertions later. Color (green ≥ $0, red < $0), the dashed
zero-line, and the hover crosshair mirror the desktop app's matplotlib chart
conventions documented in the top-level README.

## Not implemented yet

- **Deep-history backfill** for closed positions / activity beyond the first
  ~100 records (see "Live fetch scope" above).
- Settings, credentials/WebSocket streaming, notes, and Loss Watch
  acknowledgement UI (the data/logic exist in `app/services` and are used for
  the Loss Watch metric card, but there's no page to acknowledge losers yet).
- Switching back to sample mode once you've fetched a real wallet — there's
  no button for it (the sample fixture data is still there in the DB under
  the `"sample"` wallet address, just not pointed at by `current_wallet()`
  anymore).
