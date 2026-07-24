/**
 * Shared spec helpers: reading seeded tokens, UI login, MUI-select handling,
 * and API shortcuts that reuse global-setup tokens (no extra logins).
 */
import fs from 'fs';
import path from 'path';
import { expect, type Page, type Locator } from '@playwright/test';
import { AUTH_DIR, type Role, type TestUser } from './config';
import * as api from './api';

interface SeededUser {
  id: string;
  email: string;
  name: string;
  role: string;
  token: string;
}
interface SeedFile {
  users: Record<string, SeededUser>;
}

let seedCache: SeedFile | null = null;

/** Read `.auth/seed.json` (written by global-setup). */
export function seed(): SeedFile {
  if (seedCache) return seedCache;
  const file = path.join(AUTH_DIR, 'seed.json');
  if (!fs.existsSync(file)) {
    throw new Error(`Missing ${file}. Did global-setup run? Start the stack and re-run.`);
  }
  seedCache = JSON.parse(fs.readFileSync(file, 'utf-8')) as SeedFile;
  return seedCache;
}

export function seededUser(role: Role): SeededUser {
  const u = seed().users[role];
  if (!u) throw new Error(`No seeded user for role "${role}" in seed.json`);
  return u;
}

/** A reusable admin token for API-based fixture setup (no login). */
export function adminToken(): string {
  return seededUser('admin').token;
}

/**
 * Log in through the real UI. Kept deliberately rare — the backend limits
 * /auth/login to 5/min per IP; most specs use pre-seeded storageState instead.
 */
export async function loginViaUi(page: Page, user: Pick<TestUser, 'email' | 'password'>): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Email').fill(user.email);
  await page.getByLabel('Password').fill(user.password);
  await page.getByRole('button', { name: 'Sign In' }).click();
}

/**
 * Select an option from a MUI `<Select>`.
 *
 * These Selects pair an `<InputLabel>` with the Select but omit the
 * `labelId`/`id` association, so `getByLabel` can't reach them. Instead we
 * locate the `.MuiFormControl-root` that contains the label text, click its
 * `.MuiSelect-select` control, then pick the option from the body-level portal.
 * Pass `scope` (e.g. a dialog locator) to disambiguate when several Selects
 * share a label on the page.
 */
export async function selectMuiOption(
  page: Page,
  labelText: string,
  optionName: string | RegExp,
  scope?: Locator,
): Promise<void> {
  const root = scope ?? page;
  const control = root.locator('.MuiFormControl-root').filter({ hasText: labelText }).first();
  await control.locator('.MuiSelect-select').first().click();
  await page.getByRole('option', { name: optionName }).click();
}

/** Assert we are authenticated and on the case queue. */
export async function expectOnCaseQueue(page: Page): Promise<void> {
  await expect(page.getByRole('heading', { name: 'Case Queue' })).toBeVisible();
}

export { api };
