/**
 * Thin backend-API client used for deterministic seeding — both by
 * global-setup (bootstrap users + auth state) and by individual specs
 * (create a case/contributor via API, then drive the UI against it).
 *
 * Uses global `fetch` (Node >= 18, which Playwright requires). All calls hit
 * API_URL directly on the host (bypassing the Vite proxy).
 */
import { API_URL } from './config';

export interface LoginResult {
  access_token: string;
  user_id: string;
  role: string;
  roles: string[];
}

async function request(
  method: string,
  path: string,
  opts: { token?: string; body?: unknown } = {},
): Promise<Response> {
  const headers: Record<string, string> = {};
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
  if (opts.token) headers['Authorization'] = `Bearer ${opts.token}`;
  return fetch(`${API_URL}${path}`, {
    method,
    headers,
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
  });
}

async function json<T>(res: Response, context: string): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${context} failed: ${res.status} ${res.statusText} — ${text}`);
  }
  return (await res.json()) as T;
}

/** GET /health — includes `setup_required: true` when no users exist yet. */
export async function health(): Promise<{ status?: string; setup_required?: boolean; setup_hint?: string }> {
  // /health lives at the app root, not under /api/v1.
  const root = API_URL.replace(/\/api\/v1\/?$/, '');
  const res = await fetch(`${root}/health`);
  return json(res, 'health');
}

export async function login(email: string, password: string): Promise<LoginResult> {
  // The backend limits /auth/login to 5/min per IP. Retry through a 429 with
  // backoff so seeding survives a briefly-saturated window (e.g. rapid re-runs).
  const maxAttempts = 5;
  for (let attempt = 1; ; attempt++) {
    const res = await request('POST', '/auth/login', { body: { email, password } });
    if (res.status === 429 && attempt < maxAttempts) {
      await new Promise((r) => setTimeout(r, 15_000));
      continue;
    }
    return json<LoginResult>(res, `login(${email})`);
  }
}

/**
 * Create a user via the admin endpoint with a password (=> ACTIVE immediately).
 * Idempotent: a 400 "already exists" is swallowed so re-runs are safe.
 */
export async function ensureUser(
  adminToken: string,
  user: { email: string; name: string; role: string; password: string },
): Promise<void> {
  const res = await request('POST', '/auth/users', {
    token: adminToken,
    body: {
      email: user.email,
      full_name: user.name,
      role: user.role,
      password: user.password,
    },
  });
  if (res.ok) return;
  const text = await res.text().catch(() => '');
  if (res.status === 400 && /exist/i.test(text)) return; // already seeded
  throw new Error(`ensureUser(${user.email}) failed: ${res.status} — ${text}`);
}

export interface CaseResult {
  id: string;
  tracking_number: string;
  title: string;
  case_team: Array<{ user_id: string; role: string; status: string }>;
}

/** POST /cases/ — only `title` is required by the backend. */
export async function createCase(
  token: string,
  data: { title: string; description?: string; assigned_user_ids?: string[] },
): Promise<CaseResult> {
  const res = await request('POST', '/cases/', { token, body: data });
  return json<CaseResult>(res, `createCase(${data.title})`);
}

/** POST /cases/:id/team/members — add a case-team member. */
export async function addTeamMember(
  token: string,
  caseId: string,
  member: { user_id: string; role: string; department?: string; notes?: string },
): Promise<void> {
  const res = await request('POST', `/cases/${caseId}/team/members`, { token, body: member });
  await json(res, `addTeamMember(${caseId})`);
}

export interface ContributorInvite {
  contributor: { id: string; name: string; email: string };
  upload_url: string; // "/contribute/<id>?token=<raw>"
  expires_at: string;
}

/** POST /cases/:id/contributors — returns the shareable upload_url (with token). */
export async function inviteContributor(
  token: string,
  caseId: string,
  data: { name: string; email: string; department?: string; notes?: string },
): Promise<ContributorInvite> {
  const res = await request('POST', `/cases/${caseId}/contributors`, { token, body: data });
  return json<ContributorInvite>(res, `inviteContributor(${caseId})`);
}
