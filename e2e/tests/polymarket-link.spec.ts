import { test, expect } from '@playwright/test';

// Sample-mode positions have no Polymarket slug (see web/README.md — the
// bundled fixtures predate slug capture), so these tests cover the
// *graceful* no-link path: the context menu still appears, but says so
// instead of silently doing nothing or erroring. The real-link path (right
// click / Ctrl+click actually opening polymarket.com) is covered by the
// opt-in wallet-live.spec.ts, which fetches real data that does have slugs.
test.describe('Polymarket right-click link (sample mode — no slug available)', () => {
  test('right-clicking a position row shows a disabled "no link" menu item', async ({ page }) => {
    await page.goto('/positions/active');
    const row = page.getByTestId('position-row').first();
    await row.click({ button: 'right' });

    const menu = page.getByTestId('polymarket-context-menu');
    await expect(menu).toBeVisible();
    const item = page.getByTestId('open-on-polymarket');
    await expect(item).toContainText('No Polymarket link available');
    await expect(item).toBeDisabled();
  });

  test('clicking elsewhere dismisses the context menu', async ({ page }) => {
    await page.goto('/positions/active');
    await page.getByTestId('position-row').first().click({ button: 'right' });
    await expect(page.getByTestId('polymarket-context-menu')).toBeVisible();

    await page.locator('h1').click();
    await expect(page.getByTestId('polymarket-context-menu')).toHaveCount(0);
  });

  test('pressing Escape dismisses the context menu', async ({ page }) => {
    await page.goto('/positions/active');
    await page.getByTestId('position-row').first().click({ button: 'right' });
    await expect(page.getByTestId('polymarket-context-menu')).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(page.getByTestId('polymarket-context-menu')).toHaveCount(0);
  });

  test('right-click works the same on the Closed Positions table', async ({ page }) => {
    await page.goto('/positions/closed');
    await page.getByTestId('position-row').first().click({ button: 'right' });
    await expect(page.getByTestId('polymarket-context-menu')).toBeVisible();
  });

  test('right-click works on the position detail page', async ({ page }) => {
    await page.goto('/positions/active/0');
    await page.getByTestId('position-detail').click({ button: 'right' });
    await expect(page.getByTestId('polymarket-context-menu')).toBeVisible();
  });

  test('no visible "Open on Polymarket" button on the detail page without a slug', async ({ page }) => {
    await page.goto('/positions/active/0');
    await expect(page.getByTestId('open-on-polymarket-link')).toHaveCount(0);
  });

  test('Ctrl+click on a row without a link falls through to the browser\'s native new-tab behavior', async ({ page, context }) => {
    await page.goto('/positions/active');
    const link = page.getByTestId('position-row').first().locator('a');
    const href = await link.getAttribute('href');
    const marketName = (await link.textContent())!.trim();

    // No slug → our handler declines to intercept (see polymarket_link.js's
    // `if (!target.dataset.polymarketUrl) return`), so the click falls
    // through to the browser's own Ctrl+click-opens-new-tab behavior for a
    // real <a href> — opening our *own* detail page in a new tab, not
    // Polymarket, and not navigating the original tab.
    const [newPage] = await Promise.all([
      context.waitForEvent('page'),
      link.click({ modifiers: ['Control'] }),
    ]);
    await newPage.waitForLoadState();
    expect(newPage.url()).toContain(href);
    await expect(newPage.getByTestId('position-detail-market')).toHaveText(marketName);

    // Original tab never navigated away.
    await expect(page.getByTestId('active-positions-table')).toBeVisible();
  });
});
