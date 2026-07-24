import path from 'path';
import { test, expect } from '@playwright/test';
import { api, adminToken } from '../lib/helpers';

/**
 * Token-based contributor portal (no login). We seed a case + contributor via
 * the admin API, then drive the public upload URL exactly as an invited
 * contributor would from their email link.
 */
const SAMPLE_PDF = path.join(__dirname, '..', 'fixtures', 'sample.pdf');

test.describe('public · contributor upload portal', () => {
  test('a contributor uploads a document via their magic link and confirms completion', async ({ page }) => {
    const c = await api.createCase(adminToken(), { title: `E2E Portal ${Date.now()}` });
    const invite = await api.inviteContributor(adminToken(), c.id, {
      name: 'Portal Contributor',
      email: `portal-${Date.now()}@example.com`,
    });

    // upload_url is relative: "/contribute/<id>?token=<raw>"
    await page.goto(invite.upload_url);
    await expect(page.getByRole('heading', { name: 'Records Upload Portal' })).toBeVisible();

    // Hidden file input behind the "Select Files to Upload" label.
    await page.locator('#file-upload').setInputFiles(SAMPLE_PDF);

    await expect(page.getByText(/Successfully uploaded/i)).toBeVisible({ timeout: 60_000 });
    await expect(page.getByRole('table').getByText('sample.pdf')).toBeVisible({ timeout: 60_000 });

    // With at least one document uploaded, the confirm control appears.
    const confirm = page.getByRole('button', { name: 'Confirm All Records Submitted' });
    await expect(confirm).toBeVisible();
    await confirm.click();
    await expect(page.getByText(/records submission has been confirmed/i)).toBeVisible({ timeout: 15_000 });
  });
});
