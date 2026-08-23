# TradeLedger E2E Tests (Playwright)

End-to-end test suite against the web app in [`web/`](../web/), covering
dashboard rendering, navigation, position lists/filtering/detail pages, P/L
and Total Tracked Value charts, and invalid/missing-data edge cases.

## Setup

```bash
# From the repo root, one time:
python3 -m venv .venv && source .venv/bin/activate
pip install -r web/requirements.txt

cd e2e
npm install
npx playwright install --with-deps chromium
```

## Run

```bash
cd e2e
npm test              # headless, all tests
npm run test:headed   # watch it click through the app in a real browser window
npm run test:ui       # Playwright's interactive UI mode — best for writing/debugging
npm run test:debug    # step through with the Playwright inspector
npm run report        # open the last HTML report
```

No manual server start needed — `playwright.config.ts` launches the FastAPI
app itself for the test run (see "How the test server works" below) and
tears it down after.

## How the test server works

Tests never touch the app instance you might have running for manual poking
around (typically `python run_web.py` on port 8000). Instead,
`playwright.config.ts`'s `webServer` block:

1. Deletes any existing `tradeledger_e2e.db` at the repo root
2. Starts a fresh `python run_web.py` bound to `127.0.0.1:8010`, pointed at
   that (now-empty) database via the `TRADELEDGER_DB` env var
3. Waits for it to respond, runs the suite, then shuts it down

Since `web/main.py`'s startup hook reseeds sample data into an empty
database automatically, every test run starts from the exact same, known
fixture state — see [`fixtures/sample-data.ts`](fixtures/sample-data.ts) for
the hand-verified values (total tracked value, win/loss counts, chart point
counts, etc.) tests assert against. If you ever regenerate or edit
`sample_data/*.json`, update that file to match.

## What's covered

| File | Covers |
|---|---|
| `dashboard.spec.ts` | Metric cards, P/L chart rendering, position previews, positive/negative coloring |
| `navigation.spec.ts` | Every nav link, active-page (`aria-current`) state, brand link |
| `positions.spec.ts` | Active/Resolved/Closed lists, market-name filtering, result counts, the empty Resolved-list state |
| `position-detail.spec.ts` | Asset info fields, win/loss badge, back link |
| `pnl.spec.ts` | Range buttons (1D/1W/1M/1Y/YTD/All), cumulative chart point count, daily breakdown table, the honest empty 1D range |
| `total-tracked-value.spec.ts` | Single-snapshot sparse-data chart state, snapshot table |
| `edge-cases.spec.ts` | Unknown position kind, out-of-range/negative/non-numeric position index, unknown range query params, unmatched routes — all asserted for the *right* status code and a branded error page, not a stack trace |
| `wallet.spec.ts` | Wallet bar presence on every page, malformed-address rejection, blank-address handling, submit-button disable-on-click, auto-refresh UI absent in sample mode — client-side/validation only, no live network |
| `polymarket-link.spec.ts` | Right-click context menu on position rows and the detail page, Escape/click-elsewhere dismissal, graceful "no link available" state (sample data has no slugs), Ctrl+click fallback behavior |
| `wallet-live.spec.ts` | **Opt-in** — a real fetch against a real (public) address through `app/services/refresh.py`, including the auto-refresh UI appearing and a real right-click opening the actual polymarket.com page. Skipped by default; run with `RUN_LIVE_WALLET_TEST=1 npx playwright test wallet-live` |

### Why the live wallet fetch isn't tested by default

`wallet.spec.ts` covers everything about the wallet form that's under this
app's control (validation, error messages, disable-on-submit) without ever
calling the real Polygon RPC / Polymarket API — consistent with the rest of
this suite, and with the existing pytest suite's "no live API access
required" rule (see `tests/test_refresh.py`, which mocks the same adapters).
A full live fetch also mutates the test server's current wallet away from
the seeded sample fixture that every other spec file's assertions depend on,
so it needs to run in isolation. `wallet-live.spec.ts` exists specifically so
that isolation is explicit and opt-in rather than accidental.

## Why plain SVG charts, not `<canvas>`

The charts (`web/static/js/linechart.js`) render real `<svg>`/`<circle>`
elements with `data-testid="chart-point"` and `data-date`/`data-value`
attributes, specifically so tests can assert on chart *data* — see
`dashboard.spec.ts`'s and `pnl.spec.ts`'s point-count checks — rather than
only being able to check that a canvas exists.

## CI note

`forbidOnly`, `retries: 2`, and `workers: 1` are gated behind `process.env.CI`
in `playwright.config.ts` — set `CI=true` in whatever CI runner you wire up
(see the top-level README's Phase 3 notes for a suggested GitHub Actions
setup) so failing `test.only()` calls fail the build and flaky network/timing
issues get retried.
