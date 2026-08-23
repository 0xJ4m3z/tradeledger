import { test, expect } from '@playwright/test';

test.describe('Invalid and missing data handling', () => {
  test('unknown position kind returns a branded 404 page, not a stack trace', async ({ page }) => {
    const response = await page.goto('/positions/bogus-kind');
    expect(response?.status()).toBe(404);
    await expect(page.getByTestId('not-found-page')).toBeVisible();
    await expect(page.getByTestId('not-found-page')).toContainText('404');
    await page.getByRole('link', { name: /Back to Dashboard/ }).click();
    await expect(page).toHaveURL(/\/$/);
  });

  test('out-of-range position index returns 404', async ({ page }) => {
    const response = await page.goto('/positions/active/9999');
    expect(response?.status()).toBe(404);
    await expect(page.getByTestId('not-found-page')).toBeVisible();
  });

  test('negative position index returns 404, not a Python IndexError', async ({ page }) => {
    const response = await page.goto('/positions/active/-1');
    expect(response?.status()).toBe(404);
  });

  test('non-numeric position index is rejected by the route, not silently coerced', async ({ page }) => {
    const response = await page.goto('/positions/active/not-a-number');
    // FastAPI's path-parameter type validation (idx: int) rejects this before
    // our handler ever runs — distinct failure mode from the app-level 404s above.
    expect(response?.status()).toBe(422);
  });

  test('unknown P/L range query param falls back to "all" instead of 500ing', async ({ page }) => {
    const response = await page.goto('/pnl?range=not-a-real-range');
    expect(response?.status()).toBe(200);
    await expect(page.getByTestId('range-all')).toHaveClass(/active/);
  });

  test('unknown Total Tracked Value range query param falls back to "all"', async ({ page }) => {
    const response = await page.goto('/total-tracked-value?range=not-a-real-range');
    expect(response?.status()).toBe(200);
    await expect(page.getByTestId('tv-range-all')).toHaveClass(/active/);
  });

  test('nonexistent top-level route returns 404', async ({ page }) => {
    const response = await page.goto('/this-route-does-not-exist');
    expect(response?.status()).toBe(404);
    await expect(page.getByTestId('not-found-page')).toBeVisible();
  });
});
