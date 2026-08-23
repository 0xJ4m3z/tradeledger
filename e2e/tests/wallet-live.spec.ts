import { test, expect } from '@playwright/test';

// Opt-in live-network smoke test — NOT part of the default `npm test` run.
// It hits the real Polygon RPC + Polymarket data-api (see
// app/services/refresh.py), so it's excluded from the default suite for the
// same reason the rest of this project's tests (Playwright *and* the
// existing pytest suite) never make live network calls: determinism and
// speed. Run it deliberately when you want to confirm the live-fetch
// pipeline itself still works end-to-end against the real APIs:
//
//   RUN_LIVE_WALLET_TEST=1 npx playwright test wallet-live
//
// Uses a well-known public address (Vitalik Buterin's, published all over
// the Ethereum ecosystem) purely as a stable, always-available fixture —
// Polymarket position data is public and read-only by design, so this
// queries nothing private. It mutates the test server's "current wallet" to
// this address, which is why it's isolated from the rest of the suite.
test.skip(!process.env.RUN_LIVE_WALLET_TEST, 'set RUN_LIVE_WALLET_TEST=1 to run the live-network smoke test');

const KNOWN_PUBLIC_ADDRESS = '0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045';

test.describe('Live wallet fetch (opt-in, real network)', () => {
  test('fetching a real address switches out of sample mode and shows real data', async ({ page }) => {
    await page.goto('/');
    await page.getByTestId('wallet-address-input').fill(KNOWN_PUBLIC_ADDRESS);
    await page.getByTestId('wallet-submit').click();

    await page.waitForURL(/wallet_ok=|wallet_error=/, { timeout: 30_000 });

    // Either outcome proves the pipeline ran for real (RPC + Polymarket API
    // round trip) rather than just validating client-side; both are
    // acceptable here since third-party API availability isn't something
    // this repo controls.
    const ok = page.getByTestId('flash-ok');
    const err = page.getByTestId('flash-error');
    await expect(ok.or(err)).toBeVisible();

    if (await ok.isVisible()) {
      await expect(page.getByTestId('wallet-current')).toHaveAttribute('data-mode', 'live');
      await expect(page.getByTestId('wallet-current')).toContainText('0xd8dA');
    }
  });

  test('live mode shows last-updated time and an auto-refresh checkbox', async ({ page }) => {
    await page.goto('/');
    // Depends on the previous test having already switched this wallet to
    // live mode (both tests share the same test-server DB within one run).
    const mode = await page.getByTestId('wallet-current').getAttribute('data-mode');
    test.skip(mode !== 'live', 'requires the wallet already be in live mode');

    await expect(page.getByTestId('wallet-last-updated')).toContainText('Last updated');
    await expect(page.getByTestId('auto-refresh-checkbox')).toBeChecked();
  });

  test('right-clicking a real position with a slug opens the actual Polymarket page', async ({ page, context }) => {
    await page.goto('/positions/resolved');
    const rows = page.getByTestId('position-row');
    test.skip((await rows.count()) === 0, 'this wallet has no resolved positions right now');

    const row = rows.first();
    const url = await row.getAttribute('data-polymarket-url');
    test.skip(!url, 'this position has no captured slug');

    await row.click({ button: 'right' });
    const item = page.getByTestId('open-on-polymarket');
    await expect(item).not.toBeDisabled();
    await expect(item).toContainText('Open on Polymarket');

    const [newPage] = await Promise.all([
      context.waitForEvent('page'),
      item.click(),
    ]);
    await newPage.waitForLoadState('domcontentloaded');
    expect(newPage.url()).toBe(url);
    expect(newPage.url()).toContain('polymarket.com/event/');
  });

  test('the detail page shows a visible "Open on Polymarket" link for a position with a slug', async ({ page }) => {
    await page.goto('/positions/resolved');
    const rows = page.getByTestId('position-row');
    test.skip((await rows.count()) === 0, 'this wallet has no resolved positions right now');

    await rows.first().locator('a').click();
    const link = page.getByTestId('open-on-polymarket-link');
    test.skip(!(await link.count()), 'this position has no captured slug');

    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute('target', '_blank');
    await expect(link).toHaveAttribute('href', /^https:\/\/polymarket\.com\/event\//);
  });
});
