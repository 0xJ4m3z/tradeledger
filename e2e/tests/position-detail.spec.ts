import { test, expect } from '@playwright/test';
import { ACTIVE_POSITION_0, CLOSED_POSITION_LOSS } from '../fixtures/sample-data';

test.describe('Position detail — active', () => {
  test('shows full asset information for a known active position', async ({ page }) => {
    await page.goto('/positions/active/0');
    await expect(page.getByTestId('position-detail-market')).toHaveText(ACTIVE_POSITION_0.market);

    const detail = page.getByTestId('position-detail');
    await expect(detail).toContainText(ACTIVE_POSITION_0.outcome);
    await expect(page.getByTestId('detail-unrealized-pnl')).toHaveText('$110.00');
    await expect(page.getByTestId('detail-unrealized-pnl')).toHaveClass(/pnl-pos/);
  });

  test('has a working back link to the Active Positions list', async ({ page }) => {
    await page.goto('/positions/active/0');
    await page.getByTestId('back-to-list').click();
    await expect(page).toHaveURL(/\/positions\/active$/);
  });
});

test.describe('Position detail — closed', () => {
  test('shows a LOSS badge and negative realized P/L for a known losing position', async ({ page }) => {
    await page.goto('/positions/closed/8');
    await expect(page.getByTestId('position-detail-market')).toHaveText(CLOSED_POSITION_LOSS.market);
    await expect(page.getByTestId('detail-result')).toContainText('LOSS');
    await expect(page.getByTestId('detail-realized-pnl')).toHaveClass(/pnl-neg/);
  });

  test('shows redeemed status and close type for closed positions', async ({ page }) => {
    await page.goto('/positions/closed/0');
    const detail = page.getByTestId('position-detail');
    await expect(detail).toContainText('Redeemed');
    await expect(detail).toContainText('Resolved date');
  });
});
