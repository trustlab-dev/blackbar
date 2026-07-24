/**
 * Central configuration + canonical test-user roster for the E2E suite.
 *
 * Everything is env-overridable (see ../.env.example). Defaults assume the
 * docker-compose stack from the repo root, bootstrapped per the README.
 */
import path from 'path';

function env(name: string, fallback: string): string {
  const v = process.env[name];
  return v === undefined || v === '' ? fallback : v;
}

export const BASE_URL = env('E2E_BASE_URL', 'http://localhost:3000');
export const API_URL = env('E2E_API_URL', 'http://localhost:8000/api/v1');

/** Directory where per-role Playwright storageState files are written. */
export const AUTH_DIR = path.join(__dirname, '..', '.auth');

export function authFile(role: Role): string {
  return path.join(AUTH_DIR, `${role}.json`);
}

export type Role = 'admin' | 'analyst' | 'user' | 'guest';

export interface TestUser {
  role: Role;
  email: string;
  name: string;
  password: string;
}

const USER_PASSWORD = env('E2E_USER_PASSWORD', 'E2eUser!2345');

/**
 * The pre-existing admin/owner. Must already exist in the stack — the harness
 * logs in as this account and creates the other role users from it.
 */
export const ADMIN: TestUser = {
  role: 'admin',
  email: env('E2E_ADMIN_EMAIL', 'admin@blackbar.test'),
  name: env('E2E_ADMIN_NAME', 'E2E Admin'),
  password: env('E2E_ADMIN_PASSWORD', 'E2eAdmin!2345'),
};

/**
 * Role users the harness seeds via the admin API on first run. Emails are
 * stable so re-runs are idempotent (create returns 400 "already exists",
 * which global-setup treats as success).
 */
export const SEEDED_USERS: TestUser[] = [
  { role: 'analyst', email: 'e2e-analyst@blackbar.test', name: 'E2E Analyst', password: USER_PASSWORD },
  { role: 'user', email: 'e2e-user@blackbar.test', name: 'E2E User', password: USER_PASSWORD },
  { role: 'guest', email: 'e2e-guest@blackbar.test', name: 'E2E Guest', password: USER_PASSWORD },
];

export const ALL_USERS: TestUser[] = [ADMIN, ...SEEDED_USERS];

export function userByRole(role: Role): TestUser {
  const u = ALL_USERS.find((x) => x.role === role);
  if (!u) throw new Error(`No seeded test user for role "${role}"`);
  return u;
}
