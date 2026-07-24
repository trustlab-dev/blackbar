import { test, expect } from '@playwright/test';
import { api } from '../lib/helpers';

/**
 * Smoke + unauthenticated-access guards. No storageState → anonymous browser.
 */
test.describe('health & anonymous access', () => {
  test('backend health endpoint reports the stack is up and bootstrapped', async () => {
    const h = await api.health();
    expect(h.status).toBe('healthy');
    // If this is set, global-setup would have already failed with guidance.
    expect(h.setup_required).toBeFalsy();
  });

  test('unauthenticated /cases redirects to the login page', async ({ page }) => {
    await page.goto('/cases');
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole('heading', { name: 'Sign In' })).toBeVisible();
  });

  test('unauthenticated /admin does not expose the admin console', async ({ page }) => {
    await page.goto('/admin');
    // ProtectedRoute blocks unauthenticated access; we must NOT see admin nav.
    await expect(page.getByText('User Management')).toHaveCount(0);
  });

  test('the login screen renders its form', async ({ page }) => {
    await page.goto('/login');
    await expect(page.getByLabel('Email')).toBeVisible();
    await expect(page.getByLabel('Password')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Sign In' })).toBeVisible();
  });
});
