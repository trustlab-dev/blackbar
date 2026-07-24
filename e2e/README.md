# BlackBar End-to-End Tests (Playwright)

Real browser tests that drive the **actual docker-compose stack** — frontend
(`:3000`) → backend (`:8000`) → MongoDB. No mocking: every assertion goes
through the real UI, API, database, and authorization layer.

## What's covered

| Spec | Scenario |
|------|----------|
| `01-health-and-access` | Backend health; unauthenticated routes bounce to `/login`; admin console hidden when logged out |
| `99-login` | UI sign-in success, bad-credential error, logout clears the session (runs **last** so its real logins don't share global-setup's rate-limit window) |
| `03-user-management` | Admin lists users; invites a new user; duplicate-email error |
| `04-case-create` | Create a case via the queue dialog **and** the `/cases/new` form; search it in the queue |
| `05-case-detail` | Open a case, change status (persisted), add an internal comment |
| `06-case-team` | Add a case-team member, then remove them |
| `07-contributors` | Invite a record contributor, see it listed, remove it |
| `08-clock` | Pause and resume the statutory clock |
| `09-documents` | Upload a PDF into a case; it appears in the documents table |
| `10-transfers` | Transfer a case to another public body |
| `11-access-control` | Guest sees only shared docs; **team-scoped `user` is denied off-team cases (UI + API), allowed on-team**; no admin link for non-admins |
| `12-public-request` | A member of the public submits an FOI request and gets a tracking number |
| `13-contributor-portal` | Token-based contributor uploads a document and confirms completion |

`11-access-control` is the UI-facing regression for the object-level
authorization work (ISSUE-018).

## Prerequisites

1. **Docker + docker compose** (the stack) and **Node 18+** (Playwright).

2. **A bootstrapped stack with a known admin.** The harness cannot create the
   first owner over the public API (owner activation needs an emailed token),
   so bootstrap once from the repo root. The command below matches the default
   credentials in `.env.example`:

   ```bash
   cd ..   # repo root
   ADMIN_EMAIL=admin@blackbar.test ADMIN_PASSWORD='E2eAdmin!2345' \
   ADMIN_NAME='E2E Admin' ORG_NAME='BlackBar E2E' \
   SEED_DEMO=n SEED_TRUSTLAB=n bash setup.sh
   docker compose up -d
   ```

   Already have a stack? Skip `setup.sh` and instead point the harness at your
   admin via `E2E_ADMIN_EMAIL` / `E2E_ADMIN_PASSWORD` (see below).

## Install & run

```bash
cd e2e
cp .env.example .env          # optional: edit if your creds/ports differ
npm install
npm run install:browsers      # one-time: downloads the Chromium runtime
npm test                      # run everything
```

Useful variants:

```bash
npm run test:headed                 # watch it drive a real browser
npm run test:ui                     # Playwright's interactive UI mode
npx playwright test specs/11-access-control.spec.ts   # one file
npx playwright test --list          # list all tests without running
npm run report                      # open the last HTML report
```

## How it works

- **`global-setup.ts`** runs once before any spec. It checks `/health`, logs in
  as the admin, creates the `analyst` / `user` / `guest` role accounts
  (idempotent), and writes:
  - `.auth/<role>.json` — a Playwright storageState per role, so specs start
    already authenticated (the app authenticates via `localStorage`, which
    these files seed).
  - `.auth/seed.json` — each role's `{ id, token }`, so specs seed prerequisites
    (cases, contributors, team members) **through the API** without re-logging-in.
- Specs pick a role with `test.use({ storageState: authFile('admin') })` and
  seed their own data via `lib/api.ts`, keeping tests independent and parallel-safe.

## Notes & gotchas

- **Login is rate-limited to 5/min per IP** by the backend. The harness logs in
  exactly 4 times in `global-setup`; only `99-login` drives the login UI, and it
  runs last (all other specs use pre-seeded storageState) so its logins don't
  share global-setup's window. `api.login` also retries through a `429` with
  backoff, so back-to-back re-runs recover on their own (global-setup may pause
  ~15s while the window clears).
- **The app ships no `data-testid`s** (the ones in `*.test.tsx` are RTL mocks).
  Selectors here use accessible roles/labels/text plus the few real DOM hooks
  (`#username`, `tr[data-doc-id]`, `#file-upload`). If a selector drifts when the
  UI changes, that's the layer to update.
- **`workers: 1`** on purpose — all specs share one live database. Point each
  worker at an isolated stack before raising it.
- Config lives in `lib/config.ts`, overridable via env (`.env` / shell):
  `E2E_BASE_URL`, `E2E_API_URL`, `E2E_ADMIN_EMAIL`, `E2E_ADMIN_PASSWORD`,
  `E2E_ADMIN_NAME`, `E2E_USER_PASSWORD`.

## Layout

```
e2e/
  playwright.config.ts     # baseURL, globalSetup, single worker, reporters
  global-setup.ts          # seed users + auth state via API
  lib/
    config.ts              # env + canonical test-user roster
    api.ts                 # backend API client (fetch)
    helpers.ts             # seed.json readers, UI login, MUI-select helper
  fixtures/
    sample.pdf             # tiny real PDF for upload specs
  specs/                   # one file per flow (01…13, plus 99-login which runs last)
```
