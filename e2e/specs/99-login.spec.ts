import { test, expect } from '@playwright/test';
import { userByRole } from '../lib/config';
import { loginViaUi } from '../lib/helpers';

/**
 * Real UI login/logout. These are the only specs that POST /auth/login through
 * the browser — kept minimal because the backend limits login to 5/min per IP.
 * The failure case tolerates a rate-limit response (both 401 and 429 surface an
 * error to the user).
 */
test.describe('login & logout', () => {
  test('a valid user can sign in and reach the case queue', async ({ page }) => {
    const analyst = userByRole('analyst');
    await loginViaUi(page, analyst);

    // Login redirects to the app root ("/"), which renders the case queue for
    // an authenticated non-guest user.
    await expect(page.getByRole('heading', { name: 'Case Queue' })).toBeVisible();
    await expect(page).toHaveURL(/\/(cases)?$/);
    // Header greets the logged-in user by name.
    await expect(page.getByText(analyst.name)).toBeVisible();
  });

  test('invalid credentials show an error and stay on the login page', async ({ page }) => {
    await loginViaUi(page, { email: 'e2e-analyst@blackbar.test', password: 'WrongPassword!1' });

    await expect(page).toHaveURL(/\/login$/);
    // `.error-message` renders on any failed attempt (401 invalid, or 429 rate-limited).
    await expect(page.locator('.error-message')).toBeVisible();
  });

  test('logging out returns to the login page and clears the session', async ({ page }) => {
    const analyst = userByRole('analyst');
    await loginViaUi(page, analyst);
    await expect(page.getByRole('heading', { name: 'Case Queue' })).toBeVisible();

    // Open the user menu. The avatar IconButton has no accessible name, so
    // target the last button in the header, then click the Logout item.
    await page.locator('header button').last().click();
    await page.getByRole('menuitem', { name: 'Logout' }).click();

    await expect(page).toHaveURL(/\/login$/);
    // Session cleared — visiting a protected route bounces back to login.
    await page.goto('/cases');
    await expect(page).toHaveURL(/\/login$/);
  });
});
