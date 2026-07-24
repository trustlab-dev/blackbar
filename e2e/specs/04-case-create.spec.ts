import { test, expect } from '@playwright/test';
import { authFile } from '../lib/config';

test.use({ storageState: authFile('admin') });

test.describe('case creation', () => {
  test('create a case via the Case Queue dialog → lands on the case detail', async ({ page }) => {
    const title = `E2E Queue Case ${Date.now()}`;
    await page.goto('/cases');
    await expect(page.getByRole('heading', { name: 'Case Queue' })).toBeVisible();

    await page.getByRole('button', { name: 'Create Case' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'Create New Case' })).toBeVisible();

    await dialog.getByLabel('Request Title').fill(title);
    await dialog.getByLabel('Description').fill('Created by the E2E suite.');
    await dialog.getByLabel('Requester Name').fill('Jamie Requester');
    await dialog.getByLabel('Requester Email').fill('jamie.requester@example.com');

    await dialog.getByRole('button', { name: 'Create Case' }).click();

    // Redirects straight to /cases/:id
    await expect(page).toHaveURL(/\/cases\/[0-9a-f-]{36}$/);
    await expect(page.getByRole('heading', { name: title })).toBeVisible();
  });

  test('create a case via the /cases/new form', async ({ page }) => {
    const title = `E2E Form Case ${Date.now()}`;
    await page.goto('/cases/new');
    await expect(page.getByRole('heading', { name: 'Create New Case' })).toBeVisible();

    await page.getByLabel('Title').fill(title);
    await page.getByLabel('Description').fill('Simple internal case.');
    await page.getByRole('button', { name: 'Create Case' }).click();

    await expect(page.getByText(/Case created successfully/i)).toBeVisible();
    await expect(page).toHaveURL(/\/cases\/[0-9a-f-]{36}$/, { timeout: 15_000 });
  });

  test('the created case is searchable in the queue', async ({ page }) => {
    const title = `E2E Searchable ${Date.now()}`;
    await page.goto('/cases/new');
    await page.getByLabel('Title').fill(title);
    await page.getByRole('button', { name: 'Create Case' }).click();
    await expect(page).toHaveURL(/\/cases\/[0-9a-f-]{36}$/, { timeout: 15_000 });

    await page.goto('/cases');
    await page.getByPlaceholder('Search by title, tracking number...').fill(title);
    await expect(page.getByRole('row').filter({ hasText: title })).toBeVisible({ timeout: 15_000 });
  });
});
