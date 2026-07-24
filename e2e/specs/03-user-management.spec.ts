import { test, expect } from '@playwright/test';
import { authFile } from '../lib/config';
import { selectMuiOption, adminToken } from '../lib/helpers';

/** Admin user-management flows. Runs as the seeded admin (storageState). */
test.use({ storageState: authFile('admin') });

test.describe('admin · user management', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/admin');
    await page.getByText('User Management').click();
    await expect(page.getByRole('button', { name: 'Add User' })).toBeVisible();
  });

  test('the user table lists the seeded role accounts', async ({ page }) => {
    const table = page.getByRole('table');
    await expect(table).toBeVisible();
    await expect(table.getByText('e2e-analyst@blackbar.test')).toBeVisible();
    await expect(table.getByText('e2e-user@blackbar.test')).toBeVisible();
  });

  test('admin can invite a new user via the dialog', async ({ page }) => {
    // Unique email so re-runs don't collide.
    const email = `e2e-invitee-${Date.now()}@blackbar.test`;

    await page.getByRole('button', { name: 'Add User' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'Invite New User' })).toBeVisible();

    await dialog.getByLabel('Email Address').fill(email);
    await dialog.getByLabel('Full Name').fill('E2E Invitee');
    // Role select — pick Analyst (also the default, but assert the interaction).
    await selectMuiOption(page, 'Role', 'Analyst', dialog);

    await dialog.getByRole('button', { name: 'Send Invitation' }).click();

    // Success panel then auto-close + table refetch.
    await expect(page.getByRole('heading', { name: /Invitation Sent/i })).toBeVisible();
    await expect(page.getByRole('table').getByText(email)).toBeVisible({ timeout: 15_000 });
  });

  test('inviting a duplicate email surfaces an error', async ({ page }) => {
    await page.getByRole('button', { name: 'Add User' }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('Email Address').fill('e2e-analyst@blackbar.test'); // already exists
    await dialog.getByLabel('Full Name').fill('Dupe');
    await dialog.getByRole('button', { name: 'Send Invitation' }).click();

    // The invite is rejected: the success panel never appears and the form
    // stays open. (The exact error copy depends on the API error envelope.)
    await expect(page.getByRole('heading', { name: /Invitation Sent/i })).toHaveCount(0);
    await expect(dialog.getByLabel('Email Address')).toBeVisible();
  });

  test('duplicate creation is rejected by the API', async () => {
    // Belt-and-suspenders: confirm the backend refuses the duplicate directly.
    const res = await fetch(`${process.env.E2E_API_URL || 'http://localhost:8000/api/v1'}/auth/users`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${adminToken()}`,
      },
      body: JSON.stringify({
        email: 'e2e-analyst@blackbar.test',
        full_name: 'Dupe',
        role: 'analyst',
        password: 'E2eUser!2345',
      }),
    });
    expect(res.status).toBe(400);
  });
});
