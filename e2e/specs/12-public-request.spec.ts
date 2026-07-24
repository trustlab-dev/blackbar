import { test, expect } from '@playwright/test';

/**
 * Public FOI request submission (no auth). Requires `enable_public_requests`
 * (on by default). Skips gracefully if the org has disabled the feature.
 */
test.describe('public · submit an FOI request', () => {
  test('a member of the public can submit a request and get a tracking number', async ({ page }) => {
    await page.goto('/public/request/new');

    // Feature may be disabled by config — don't fail the suite over policy.
    if (await page.getByText(/not available|disabled/i).first().isVisible().catch(() => false)) {
      test.skip(true, 'Public requests are disabled on this instance.');
    }

    await expect(page.getByRole('heading', { name: /Submit|Request/i }).first()).toBeVisible();

    await page.getByLabel('Request Title').fill(`E2E Public Request ${Date.now()}`);
    await page.getByLabel('Detailed Description').fill('Please release all records regarding the E2E test program.');
    await page.getByLabel('Full Name').fill('Pat Public');
    await page.getByLabel('Email Address').fill(`pat.public-${Date.now()}@example.com`);

    await page.getByRole('button', { name: 'Submit Request' }).click();

    await expect(page.getByRole('heading', { name: 'Request Submitted Successfully!' })).toBeVisible({
      timeout: 15_000,
    });
    // A tracking number is shown for the requester to follow up with.
    await expect(page.locator('.tracking-number')).toBeVisible();
  });
});
