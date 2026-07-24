import { test, expect } from '@playwright/test';
import { authFile } from '../lib/config';
import { api, adminToken } from '../lib/helpers';

test.use({ storageState: authFile('admin') });

test.describe('case detail · transfer to another public body', () => {
  test('transfer a case and see it recorded', async ({ page }) => {
    const c = await api.createCase(adminToken(), { title: `E2E Transfer ${Date.now()}` });

    await page.goto(`/cases/${c.id}`);
    await expect(page.getByText('Request Transfer')).toBeVisible();

    await page.getByRole('button', { name: 'Transfer', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(
      dialog.getByRole('heading', { name: 'Transfer Request to Another Public Body' }),
    ).toBeVisible();

    await dialog.getByLabel('Recipient Organization').fill('Ministry of Records');
    await dialog.getByLabel('Recipient Email').fill('records@other.gov.example');
    await dialog.getByLabel('Reason for Transfer').fill('Wrong jurisdiction — belongs to the Ministry.');

    await dialog.getByRole('button', { name: 'Transfer Request' }).click();

    // Confirm server-side via the transfers API (avoids UI-copy coupling).
    await expect(async () => {
      const token = adminToken();
      const res = await fetch(`${process.env.E2E_API_URL || 'http://localhost:8000/api/v1'}/cases/${c.id}/transfers`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      expect(res.ok).toBeTruthy();
      const transfers = (await res.json()) as Array<{ recipient_organization: string }>;
      expect(transfers.some((t) => t.recipient_organization === 'Ministry of Records')).toBeTruthy();
    }).toPass({ timeout: 15_000 });
  });
});
