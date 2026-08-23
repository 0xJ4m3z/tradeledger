import { test, expect } from '@playwright/test';
import { SAMPLE } from '../fixtures/sample-data';

test.describe('Active Positions list', () => {
  test('shows all active positions with a correct result count', async ({ page }) => {
    await page.goto('/positions/active');
    await expect(page.getByTestId('result-count')).toHaveText(`${SAMPLE.activeCount} positions`);
    await expect(page.getByTestId('position-row')).toHaveCount(SAMPLE.activeCount);
  });

  test('filters rows by market name as you type', async ({ page }) => {
    await page.goto('/positions/active');
    await page.getByTestId('position-filter').fill('gold');
    const visibleRows = page.locator('tbody tr[data-testid="position-row"]:not([hidden])');
    await expect(visibleRows).toHaveCount(1);
    await expect(page.getByTestId('result-count')).toHaveText('1 position');
    await expect(visibleRows).toContainText('Gold Price Above $2400');
  });

  test('filter is case-insensitive and clears back to full list', async ({ page }) => {
    await page.goto('/positions/active');
    const filter = page.getByTestId('position-filter');

    await filter.fill('FEDERAL RESERVE');
    await expect(page.getByTestId('result-count')).toHaveText('1 position');

    await filter.fill('');
    await expect(page.getByTestId('result-count')).toHaveText(`${SAMPLE.activeCount} positions`);
  });

  test('filtering to a non-existent market shows zero results, not an error', async ({ page }) => {
    await page.goto('/positions/active');
    await page.getByTestId('position-filter').fill('nonexistent-market-xyz');
    await expect(page.getByTestId('result-count')).toHaveText('0 positions');
    await expect(page.locator('tbody tr:not([hidden])')).toHaveCount(0);
  });

  test('clicking a market name navigates to its detail page', async ({ page }) => {
    await page.goto('/positions/active');
    const firstMarketLink = page.getByTestId('position-row').first().locator('a');
    const marketName = await firstMarketLink.textContent();
    await firstMarketLink.click();
    await expect(page).toHaveURL(/\/positions\/active\/\d+$/);
    await expect(page.getByTestId('position-detail-market')).toHaveText(marketName!.trim());
  });
});

test.describe('Resolved Positions list', () => {
  test('shows an honest empty state — sample data has no pending-redemption positions', async ({ page }) => {
    await page.goto('/positions/resolved');
    await expect(page.getByTestId('empty-state')).toBeVisible();
    await expect(page.getByTestId('empty-state')).toContainText('No resolved positions');
    await expect(page.getByTestId('position-row')).toHaveCount(0);
    await expect(page.getByTestId('position-filter')).toBeHidden();
  });
});

test.describe('Closed Positions list', () => {
  test('shows all closed positions with win/loss badges', async ({ page }) => {
    await page.goto('/positions/closed');
    await expect(page.getByTestId('result-count')).toHaveText(`${SAMPLE.closedCount} positions`);
    await expect(page.getByTestId('position-row')).toHaveCount(SAMPLE.closedCount);

    const badges = page.getByTestId('win-loss-badge');
    await expect(badges).toHaveCount(SAMPLE.closedCount);

    const wins = page.locator('.badge-win');
    const losses = page.locator('.badge-loss');
    await expect(wins).toHaveCount(SAMPLE.winCount);
    await expect(losses).toHaveCount(SAMPLE.lossCount);
  });

  test('clicking a closed position navigates to its detail page with result badge', async ({ page }) => {
    await page.goto('/positions/closed');
    await page.getByTestId('position-row').first().locator('a').click();
    await expect(page).toHaveURL(/\/positions\/closed\/\d+$/);
    await expect(page.getByTestId('detail-result')).toBeVisible();
    await expect(page.getByTestId('detail-realized-pnl')).toBeVisible();
  });
});
