import path from 'path';
import { test, expect } from '@playwright/test';
import { authFile } from '../lib/config';
import { api, adminToken } from '../lib/helpers';

test.use({ storageState: authFile('admin') });

const SAMPLE_PDF = path.join(__dirname, '..', 'fixtures', 'sample.pdf');

test.describe('case documents · upload', () => {
  test('upload a PDF into a case and see it in the documents table', async ({ page }) => {
    const c = await api.createCase(adminToken(), { title: `E2E Docs ${Date.now()}` });

    await page.goto(`/cases/${c.id}/documents`);
    await expect(page.getByRole('heading', { name: 'Documents' })).toBeVisible();

    // Open the upload modal, stage the file on the hidden input, then confirm.
    await page.getByRole('button', { name: 'Upload Documents' }).click();
    await page.locator('input[type="file"]').setInputFiles(SAMPLE_PDF);

    // After staging, the modal shows the selection + an "Upload N File(s)" button.
    const confirm = page.getByRole('button', { name: /Upload \d+ File/i });
    await expect(confirm).toBeVisible({ timeout: 10_000 });
    await confirm.click();

    // Processing runs server-side (conversion/OCR); allow generous time for the
    // row to appear. Documents render as <tr data-doc-id="...">.
    const docRow = page.locator('tr[data-doc-id]').filter({ hasText: 'sample.pdf' });
    await expect(docRow).toBeVisible({ timeout: 60_000 });
  });
});
