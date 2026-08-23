import { test, expect } from '@playwright/test';

const NAV_LINKS: Array<{ testId: string; path: string; heading: RegExp }> = [
  { testId: 'nav-dashboard', path: '/', heading: /Dashboard/ },
  { testId: 'nav-active', path: '/positions/active', heading: /Active Positions/ },
  { testId: 'nav-resolved', path: '/positions/resolved', heading: /Resolved Positions/ },
  { testId: 'nav-closed', path: '/positions/closed', heading: /Closed Positions/ },
  { testId: 'nav-pnl', path: '/pnl', heading: /Realized P\/L/ },
  { testId: 'nav-total-value', path: '/total-tracked-value', heading: /Total Tracked Value/ },
];

test.describe('Navigation', () => {
  test('every nav link is present on the dashboard', async ({ page }) => {
    await page.goto('/');
    for (const link of NAV_LINKS) {
      await expect(page.getByTestId(link.testId)).toBeVisible();
    }
  });

  for (const link of NAV_LINKS) {
    test(`nav link "${link.testId}" navigates to ${link.path} and marks itself current`, async ({ page }) => {
      await page.goto('/');
      await page.getByTestId(link.testId).click();
      await expect(page).toHaveURL(new RegExp(`${link.path.replace(/[/]/g, '\\/')}$`));
      await expect(page.getByRole('heading', { level: 1 })).toHaveText(link.heading);
      await expect(page.getByTestId(link.testId)).toHaveAttribute('aria-current', 'page');
    });
  }

  test('only one nav link is marked current at a time', async ({ page }) => {
    await page.goto('/positions/active');
    const current = page.locator('.nav a[aria-current="page"]');
    await expect(current).toHaveCount(1);
    await expect(current).toHaveAttribute('data-testid', 'nav-active');
  });

  test('brand link returns to the dashboard from any page', async ({ page }) => {
    await page.goto('/pnl');
    await page.locator('.brand').click();
    await expect(page).toHaveURL(/\/$/);
  });
});
