import { test, expect } from '@playwright/test';
import { authFile, API_URL } from '../lib/config';
import { api, adminToken, seededUser } from '../lib/helpers';

/**
 * Role- and object-level access control — the UI-facing counterpart to the
 * backend authz work (ISSUE-018). A `user` is team-scoped; a `guest` sees only
 * shared documents; neither sees the admin console.
 */

test.describe('guest access', () => {
  test.use({ storageState: authFile('guest') });

  test('guest home shows Shared Documents, not the case queue', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('link', { name: 'Shared Documents' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Admin' })).toHaveCount(0);
  });

  test('guest cannot open the admin console', async ({ page }) => {
    await page.goto('/admin');
    await expect(page.getByText('User Management')).toHaveCount(0);
  });
});

test.describe('team-scoped user access', () => {
  test.use({ storageState: authFile('user') });

  test('a user OFF the case team cannot open the case (UI + API both deny)', async ({ page }) => {
    // Admin creates a case; the seeded `user` is deliberately not on its team.
    const c = await api.createCase(adminToken(), { title: `E2E OffTeam ${Date.now()}` });

    // API: the user's own token is refused object-level (403).
    const res = await fetch(`${API_URL}/cases/${c.id}`, {
      headers: { Authorization: `Bearer ${seededUser('user').token}` },
    });
    expect(res.status).toBe(403);

    // UI: the detail view never renders the (inaccessible) case title.
    await page.goto(`/cases/${c.id}`);
    await expect(page.getByRole('heading', { name: c.title })).toHaveCount(0);
  });

  test('a user ON the case team can open the case', async ({ page }) => {
    const c = await api.createCase(adminToken(), { title: `E2E OnTeam ${Date.now()}` });
    await api.addTeamMember(adminToken(), c.id, {
      user_id: seededUser('user').id,
      role: 'reviewer',
    });

    await page.goto(`/cases/${c.id}`);
    await expect(page.getByRole('heading', { name: c.title })).toBeVisible({ timeout: 15_000 });
  });

  test('a plain user does not see the Admin nav link', async ({ page }) => {
    await page.goto('/cases');
    await expect(page.getByRole('link', { name: 'Admin' })).toHaveCount(0);
  });
});
