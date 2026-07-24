/**
 * Playwright globalSetup — seeds deterministic state ONCE before any spec:
 *
 *   1. Verify the stack is up and already bootstrapped (an admin exists).
 *   2. Log in as the admin.
 *   3. Create the analyst/user/guest role users (idempotent).
 *   4. Log in each role and persist:
 *        - a storageState file per role (so specs start authenticated), and
 *        - `.auth/seed.json` with each role's { id, token } so specs can seed
 *          via the API WITHOUT logging in again.
 *
 * Backend login is rate-limited to 5/min per IP, so we log in exactly four
 * times here (admin + 3 roles) and never again during the run — specs reuse
 * the tokens from seed.json. The one spec that exercises the login UI does a
 * couple of real logins and tolerates a rate-limit response.
 *
 * The app authenticates via localStorage (not cookies): AuthContext reads
 * `token` and re-fetches the user from /auth/me; UserContext reads the
 * singular `userRole`. Login sets `token`/`userId`/`userRoles` but NOT
 * `userRole`, so we set `userRole` explicitly to make role-gated UI
 * (e.g. the guest's Shared-Documents home) render deterministically.
 */
import fs from 'fs';
import path from 'path';
import type { FullConfig } from '@playwright/test';
import { ADMIN, SEEDED_USERS, AUTH_DIR, BASE_URL, authFile, type TestUser } from './lib/config';
import * as api from './lib/api';
import type { LoginResult } from './lib/api';

export interface SeededUser {
  id: string;
  email: string;
  name: string;
  role: string;
  token: string;
}
export interface SeedFile {
  users: Record<string, SeededUser>; // keyed by role
}

export const SEED_FILE = path.join(AUTH_DIR, 'seed.json');

function writeStorageState(user: TestUser, login: LoginResult): void {
  const origin = new URL(BASE_URL).origin;
  const state = {
    cookies: [],
    origins: [
      {
        origin,
        localStorage: [
          { name: 'token', value: login.access_token },
          { name: 'userId', value: login.user_id },
          { name: 'userRoles', value: JSON.stringify(login.roles) },
          { name: 'userRole', value: user.role },
          { name: 'username', value: user.name },
        ],
      },
    ],
  };
  fs.writeFileSync(authFile(user.role), JSON.stringify(state, null, 2));
}

export default async function globalSetup(_config: FullConfig): Promise<void> {
  // 1. Stack up + bootstrapped?
  let h;
  try {
    h = await api.health();
  } catch (e) {
    throw new Error(
      `Could not reach the backend health endpoint. Is the stack running ` +
        `(\`docker compose up\`) and E2E_API_URL correct?\n  ${(e as Error).message}`,
    );
  }
  if (h.setup_required) {
    throw new Error(
      `The stack has no users yet (setup_required). The E2E harness cannot ` +
        `create the first owner via API. Bootstrap it first — see e2e/README.md ` +
        `"Prerequisites". Hint from backend: ${h.setup_hint ?? ''}`,
    );
  }

  // 2. Admin login (reused for seeding + admin storageState + seed.json).
  let admin: LoginResult;
  try {
    admin = await api.login(ADMIN.email, ADMIN.password);
  } catch (e) {
    throw new Error(
      `Admin login failed for "${ADMIN.email}". Set E2E_ADMIN_EMAIL / ` +
        `E2E_ADMIN_PASSWORD to an existing admin, or bootstrap the stack with ` +
        `the credentials in e2e/.env.example.\n  ${(e as Error).message}`,
    );
  }

  // 3. Seed role users (idempotent).
  for (const u of SEEDED_USERS) {
    await api.ensureUser(admin.access_token, u);
  }

  // 4. Storage states + seed.json.
  fs.mkdirSync(AUTH_DIR, { recursive: true });
  const seed: SeedFile = { users: {} };

  writeStorageState(ADMIN, admin);
  seed.users[ADMIN.role] = {
    id: admin.user_id,
    email: ADMIN.email,
    name: ADMIN.name,
    role: ADMIN.role,
    token: admin.access_token,
  };

  for (const u of SEEDED_USERS) {
    const login = await api.login(u.email, u.password);
    writeStorageState(u, login);
    seed.users[u.role] = {
      id: login.user_id,
      email: u.email,
      name: u.name,
      role: u.role,
      token: login.access_token,
    };
  }

  fs.writeFileSync(SEED_FILE, JSON.stringify(seed, null, 2));
  // eslint-disable-next-line no-console
  console.log(`[global-setup] Seeded ${Object.keys(seed.users).length} users → ${AUTH_DIR}`);
}
