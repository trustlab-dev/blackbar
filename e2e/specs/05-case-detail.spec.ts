import { test, expect } from '@playwright/test';
import { authFile } from '../lib/config';
import { api, adminToken } from '../lib/helpers';

test.use({ storageState: authFile('admin') });

test.describe('case detail · view & inline edits', () => {
  test('view a case, change its status, and add an internal comment', async ({ page }) => {
    // Seed a case via API so the test is independent of the create-UI.
    const c = await api.createCase(adminToken(), {
      title: `E2E Detail ${Date.now()}`,
      description: 'Detail-view fixture.',
    });

    await page.goto(`/cases/${c.id}`);
    await expect(page.getByRole('heading', { name: c.title })).toBeVisible();
    await expect(page.getByText(c.tracking_number)).toBeVisible();

    // Sidebar status <select> (native) — change to In Progress; persists via PUT.
    const statusSelect = page.locator('select.status-select');
    await statusSelect.selectOption({ label: 'In Progress' });
    await expect(statusSelect).toHaveValue(/in.?progress/i);

    // Reload to confirm the change was persisted server-side.
    await page.reload();
    await expect(page.locator('select.status-select')).toHaveValue(/in.?progress/i);

    // Add an internal comment.
    const comment = `E2E note ${Date.now()}`;
    await page.getByRole('button', { name: 'Internal' }).click();
    await page.getByPlaceholder('Add internal comment...').fill(comment);
    await page.getByRole('button', { name: 'Add Comment' }).click();
    await expect(page.getByText(comment)).toBeVisible({ timeout: 15_000 });
  });

  test('a case can be opened from the queue row', async ({ page }) => {
    const c = await api.createCase(adminToken(), { title: `E2E Row Open ${Date.now()}` });
    await page.goto('/cases');
    await page.getByPlaceholder('Search by title, tracking number...').fill(c.title);
    const row = page.getByRole('row').filter({ hasText: c.title });
    await expect(row).toBeVisible({ timeout: 15_000 });
    await row.click();
    await expect(page).toHaveURL(new RegExp(`/cases/${c.id}$`));
    await expect(page.getByRole('heading', { name: c.title })).toBeVisible();
  });
});
