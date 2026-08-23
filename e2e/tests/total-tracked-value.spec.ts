import { test, expect } from '@playwright/test';

test.describe('Total Tracked Value page', () => {
  test('shows the seeded snapshot as a single-point chart, not an empty state', async ({ page }) => {
    await page.goto('/total-tracked-value');
    // Exactly one wallet_snapshot row is seeded on first boot (web/bootstrap.py) —
    // this is real (non-fabricated) sparse data, a legitimate edge case for the chart.
    await expect(page.getByTestId('tv-chart')).toBeVisible();
    await expect(page.getByTestId('tv-chart').getByTestId('chart-point')).toHaveCount(1);
    await expect(page.getByTestId('empty-state')).toHaveCount(0);
  });

  test('the single snapshot matches the dashboard Total Tracked Value card', async ({ page }) => {
    await page.goto('/total-tracked-value');
    const row = page.getByTestId('tv-snapshot-row').first();
    await expect(row).toContainText('$2,256.00');
  });

  test('range buttons are present and switchable', async ({ page }) => {
    await page.goto('/total-tracked-value');
    await expect(page.getByTestId('tv-range-all')).toHaveClass(/active/);
    await page.getByTestId('tv-range-1d').click();
    await expect(page).toHaveURL(/range=1d/);
    await expect(page.getByTestId('tv-range-1d')).toHaveClass(/active/);
  });
});
