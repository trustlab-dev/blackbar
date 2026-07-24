import { test, expect } from '@playwright/test';
import { authFile } from '../lib/config';
import { api, adminToken, selectMuiOption } from '../lib/helpers';

test.use({ storageState: authFile('admin') });

test.describe('case detail · statutory clock', () => {
  test('pause then resume the clock', async ({ page }) => {
    const c = await api.createCase(adminToken(), { title: `E2E Clock ${Date.now()}` });

    await page.goto(`/cases/${c.id}`);
    await expect(page.getByText('Statutory Clock')).toBeVisible();
    await expect(page.getByText('RUNNING', { exact: true })).toBeVisible();

    // Pause — opens a dialog requiring a reason.
    await page.getByRole('button', { name: 'Pause Clock' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'Pause Statutory Clock' })).toBeVisible();
    await selectMuiOption(page, 'Reason for Pause', 'Fee Payment Pending', dialog);
    await dialog.getByLabel('Notes (optional)').fill('Awaiting fee — E2E.');
    await dialog.getByRole('button', { name: 'Pause Clock' }).click();

    await expect(page.getByText('PAUSED', { exact: true })).toBeVisible({ timeout: 15_000 });

    // Resume.
    await page.getByRole('button', { name: 'Resume Clock' }).click();
    await expect(page.getByText('RUNNING', { exact: true })).toBeVisible({ timeout: 15_000 });
  });
});
