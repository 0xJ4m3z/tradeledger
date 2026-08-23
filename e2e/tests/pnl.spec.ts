import { test, expect } from '@playwright/test';
import { SAMPLE } from '../fixtures/sample-data';

test.describe('P/L page', () => {
  test('defaults to the "All" range with correct totals', async ({ page }) => {
    await page.goto('/pnl');
    await expect(page.getByTestId('range-all')).toHaveClass(/active/);
    await expect(page.getByTestId('metric-realized-pnl-range')).toContainText('$680.50');
    await expect(page.getByTestId('metric-trade-count')).toContainText(String(SAMPLE.closedCount));
  });

  test('renders the cumulative P/L chart with one point per closed position plus the zero anchor', async ({ page }) => {
    await page.goto('/pnl?range=all');
    await expect(page.getByTestId('pnl-chart').getByTestId('chart-point')).toHaveCount(
      SAMPLE.allTimePnlChartPointCount
    );
  });

  test('daily breakdown table lists one row per trading day, newest first', async ({ page }) => {
    await page.goto('/pnl?range=all');
    const rows = page.getByTestId('daily-pnl-row');
    await expect(rows).toHaveCount(SAMPLE.closedCount); // 10 distinct dates in the fixture
    await expect(rows.first()).toContainText(SAMPLE.lastClosedDate);
    await expect(rows.last()).toContainText(SAMPLE.firstClosedDate);
  });

  test('switching range updates the URL and the active button', async ({ page }) => {
    await page.goto('/pnl');
    await page.getByTestId('range-1w').click();
    await expect(page).toHaveURL(/range=1w/);
    await expect(page.getByTestId('range-1w')).toHaveClass(/active/);
    await expect(page.getByTestId('range-all')).not.toHaveClass(/active/);
  });

  test('1D range has no data — sample fixture predates "today" — shows honest empty state', async ({ page }) => {
    await page.goto('/pnl?range=1d');
    await expect(page.getByTestId('metric-realized-pnl-range')).toContainText('$0.00');
    await expect(page.getByTestId('metric-trade-count')).toContainText('0');
    await expect(page.getByTestId('empty-state')).toContainText('No closed positions in this range');
  });

  test('an unknown range value falls back to "All" instead of erroring', async ({ page }) => {
    const response = await page.goto('/pnl?range=bogus');
    expect(response?.status()).toBe(200);
    await expect(page.getByTestId('range-all')).toHaveClass(/active/);
  });
});
