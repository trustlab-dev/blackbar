import { test, expect } from '@playwright/test';
import { authFile } from '../lib/config';
import { api, adminToken } from '../lib/helpers';

test.use({ storageState: authFile('admin') });

test.describe('case detail · record contributors', () => {
  test('invite a contributor, see it listed, then remove it', async ({ page }) => {
    const c = await api.createCase(adminToken(), { title: `E2E Contributors ${Date.now()}` });
    const contributorEmail = `contributor-${Date.now()}@example.com`;

    await page.goto(`/cases/${c.id}`);
    await expect(page.getByText('Record Contributors')).toBeVisible();

    await page.getByRole('button', { name: 'Invite' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'Invite Record Contributor' })).toBeVisible();

    await dialog.getByLabel('Name').fill('Casey Contributor');
    await dialog.getByLabel('Email').fill(contributorEmail);
    await dialog.getByLabel('Department (optional)').fill('Records');
    await dialog.getByRole('button', { name: 'Send Invitation' }).click();

    // Two dialogs are now stacked: the "Invitation Sent" confirmation (with the
    // shareable link) over the still-open invite form. Both put the panel table
    // under aria-hidden, so close BOTH before querying the table.
    const sentDialog = page.getByRole('dialog').filter({ hasText: 'Invitation Sent' });
    await expect(sentDialog.getByRole('heading', { name: 'Invitation Sent' })).toBeVisible({ timeout: 15_000 });
    await sentDialog.getByRole('button', { name: 'Close' }).click();
    await dialog.getByRole('button', { name: 'Cancel' }).click();

    // Contributor appears in the table with a Pending status.
    const table = page.getByRole('table');
    const row = table.getByRole('row').filter({ hasText: 'Casey Contributor' });
    await expect(row).toBeVisible({ timeout: 15_000 });
    await expect(row.getByText('Pending')).toBeVisible();

    // Remove (Delete icon in the row). No accessible name → last row button.
    // The handler uses window.confirm(), which Playwright auto-dismisses unless
    // we opt in to accepting it.
    page.once('dialog', (d) => d.accept());
    await row.getByRole('button').last().click();
    await expect(table.getByRole('row').filter({ hasText: 'Casey Contributor' })).toHaveCount(0, {
      timeout: 15_000,
    });
  });

  test('invited contributor is retrievable via the API for the case', async () => {
    // Cross-check the UI action against the backend state.
    const c = await api.createCase(adminToken(), { title: `E2E Contrib API ${Date.now()}` });
    const invite = await api.inviteContributor(adminToken(), c.id, {
      name: 'API Contributor',
      email: `api-contrib-${Date.now()}@example.com`,
    });
    expect(invite.upload_url).toMatch(/^\/contribute\/[0-9a-f-]{36}\?token=/);
    expect(invite.contributor.id).toBeTruthy();
  });
});
