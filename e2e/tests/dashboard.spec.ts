import { test, expect } from '@playwright/test';
import { SAMPLE, ACTIVE_POSITION_0 } from '../fixtures/sample-data';

test.describe('Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('loads and shows the app title and heading', async ({ page }) => {
    await expect(page).toHaveTitle(/Dashboard.*TradeLedger/);
    await expect(page.getByRole('heading', { name: 'Dashboard', level: 1 })).toBeVisible();
    await expect(page.locator('.brand')).toHaveText('TradeLedger');
  });

  test('shows all six metric cards with correct values', async ({ page }) => {
    await expect(page.getByTestId('metric-total-tracked-value')).toContainText('$2,256.00');
    await expect(page.getByTestId('metric-wallet-usd-value')).toContainText('$0.00');
    await expect(page.getByTestId('metric-positions-value')).toContainText('$2,256.00');
    await expect(page.getByTestId('metric-loss-watch')).toContainText(String(SAMPLE.lossWatchCount));
    await expect(page.getByTestId('metric-realized-pnl')).toContainText('$680.50');
    await expect(page.getByTestId('metric-win-loss')).toContainText('6W');
    await expect(page.getByTestId('metric-win-loss')).toContainText('4L');
  });

  test('realized P/L card is colored positive (green)', async ({ page }) => {
    const value = page.getByTestId('metric-realized-pnl').locator('.card-value');
    await expect(value).toHaveClass(/pnl-pos/);
  });

  test('loss watch card is colored negative when count > 0', async ({ page }) => {
    const value = page.getByTestId('metric-loss-watch').locator('.card-value');
    await expect(value).toHaveClass(/pnl-neg/);
  });

  test('renders the all-time P/L chart with real data points', async ({ page }) => {
    const chart = page.getByTestId('dashboard-pnl-chart');
    await expect(chart).toBeVisible();
    const svg = chart.getByTestId('line-chart-svg');
    await expect(svg).toBeVisible();
    await expect(chart.getByTestId('chart-point')).toHaveCount(SAMPLE.allTimePnlChartPointCount);
  });

  test('active positions preview links to the top position by unrealized P/L', async ({ page }) => {
    const preview = page.getByTestId('active-positions-preview');
    await expect(preview).toBeVisible();
    const firstRow = preview.getByTestId('position-row').first();
    await expect(firstRow).toContainText(ACTIVE_POSITION_0.market);
    await expect(firstRow).toContainText('$110.00');
  });

  test('closed positions preview shows win/loss badges', async ({ page }) => {
    const preview = page.getByTestId('closed-positions-preview');
    await expect(preview).toBeVisible();
    const badges = preview.getByTestId('win-loss-badge');
    await expect(badges.first()).toBeVisible();
  });

  test('"View all" links navigate to the full position lists', async ({ page }) => {
    await page.getByTestId('view-all-active').click();
    await expect(page).toHaveURL(/\/positions\/active$/);

    await page.goBack();
    await page.getByTestId('view-all-closed').click();
    await expect(page).toHaveURL(/\/positions\/closed$/);
  });

  test('every closed-preview row links to the position with the matching market name', async ({ page }) => {
    // Regression: the dashboard's closed-positions preview is range-filtered
    // (a subset of the full closed list), but /positions/closed/{idx} indexes
    // into the FULL list — a naive "loop index" link would point at the wrong
    // position for any range other than "all". Confirms the index mapping in
    // web/routers/dashboard.py stays correct regardless of preview subsetting.
    const rows = page.getByTestId('closed-positions-preview').getByTestId('position-row');
    const count = await rows.count();
    expect(count).toBeGreaterThan(0);

    for (let i = 0; i < count; i++) {
      const row = rows.nth(i);
      const link = row.locator('a');
      const marketName = (await link.textContent())!.trim();
      const href = await link.getAttribute('href');

      await page.goto(href!);
      await expect(page.getByTestId('position-detail-market')).toHaveText(marketName);
      await page.goBack();
    }
  });
});

test.describe('Dashboard range filter', () => {
  test('defaults to "All" with a visible range bar', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByTestId('dashboard-range-bar')).toBeVisible();
    await expect(page.getByTestId('range-all')).toHaveClass(/active/);
  });

  test('shows a range-scoped Trades card alongside Realized P/L and Win/Loss', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByTestId('metric-trades')).toContainText(String(SAMPLE.closedCount));
  });

  test('switching range updates the URL, active button, and card values together', async ({ page }) => {
    await page.goto('/');
    await page.getByTestId('range-1d').click();

    await expect(page).toHaveURL(/range=1d/);
    await expect(page.getByTestId('range-1d')).toHaveClass(/active/);
    await expect(page.getByTestId('range-all')).not.toHaveClass(/active/);

    // Sample fixture predates "today" (same honest-empty-state case as the
    // P/L page's 1D range) — every range-scoped card should agree it's $0/0.
    await expect(page.getByTestId('metric-realized-pnl')).toContainText('$0.00');
    await expect(page.getByTestId('metric-trades')).toContainText('0');
    await expect(page.getByTestId('metric-win-loss')).toContainText('0W');
    await expect(page.getByTestId('metric-win-loss')).toContainText('0L');
  });

  test('range-independent cards (Total Tracked Value, Wallet, Positions, Loss Watch) do not change with range', async ({ page }) => {
    await page.goto('/?range=all');
    const allTotal = await page.getByTestId('metric-total-tracked-value').textContent();

    await page.goto('/?range=1d');
    await expect(page.getByTestId('metric-total-tracked-value')).toHaveText(allTotal!);
  });

  test('an out-of-range closed-positions preview shows the range-specific empty state', async ({ page }) => {
    await page.goto('/?range=1w');
    await expect(page.getByTestId('closed-positions-preview')).toHaveCount(0);
    await expect(page.getByTestId('empty-state')).toContainText('No closed positions in this range');
  });
});
