import { test, expect } from '@playwright/test';
import { authFile, API_URL } from '../lib/config';
import { api, adminToken, seededUser, selectMuiOption } from '../lib/helpers';

test.use({ storageState: authFile('admin') });

test.describe('case detail · team management', () => {
  test('add a team member and then remove them', async ({ page }) => {
    const c = await api.createCase(adminToken(), { title: `E2E Team ${Date.now()}` });
    const member = seededUser('user'); // "E2E User"

    await page.goto(`/cases/${c.id}`);
    await expect(page.getByRole('heading', { name: /Case Team/ })).toBeVisible();

    await page.getByRole('button', { name: 'Add Member' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'Add Team Member' })).toBeVisible();

    // UserPicker autocomplete → type the email; the backend searches by
    // name/email and the picker shows the match. Pick the option by its email.
    await dialog.getByLabel('Select User').fill(member.email);
    await page.getByRole('option').filter({ hasText: member.email }).first().click();

    // Role select — pick Reviewer (a role that keeps the remove control visible).
    await selectMuiOption(page, 'Role', 'Reviewer', dialog);

    await dialog.getByRole('button', { name: 'Add Member' }).click();

    // Member now shows in the team list.
    const memberItem = page.getByRole('listitem').filter({ hasText: member.name });
    await expect(memberItem).toBeVisible({ timeout: 15_000 });

    // Remove: the secondary-action delete button in that member's row. The
    // handler uses window.confirm(), which Playwright auto-dismisses unless we
    // opt in to accepting it.
    page.once('dialog', (d) => d.accept());
    await memberItem.getByRole('button').last().click();

    // The removed member disappears from the team list...
    await expect(page.getByRole('listitem').filter({ hasText: member.name })).toHaveCount(0, {
      timeout: 15_000,
    });
    // ...and from the team API response.
    const res = await fetch(`${API_URL}/cases/${c.id}/team`, {
      headers: { Authorization: `Bearer ${adminToken()}` },
    });
    const body = (await res.json()) as { team_members: Array<{ user_id: string }> };
    expect(body.team_members.some((x) => x.user_id === member.id)).toBeFalsy();
  });
});
