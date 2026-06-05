# Contributing to BlackBar

Thanks for your interest in contributing. BlackBar is a single-tenant,
self-hosted Freedom of Information case management and document redaction
system, released under the Apache License, Version 2.0.

This guide covers how to get a development environment running, the
conventions the project follows, and what we expect in a pull request.

## Code of Conduct

This project adheres to the [Contributor Covenant](CODE_OF_CONDUCT.md). By
participating, you are expected to uphold it.

## Developer Certificate of Origin (DCO)

BlackBar uses the [Developer Certificate of Origin](https://developercertificate.org/)
rather than a Contributor License Agreement. Every commit must be signed off:

```bash
git commit -s -m "feat(cases): add bulk close action"
```

The `-s` flag appends a `Signed-off-by:` trailer with your name and email,
certifying that you wrote the patch (or otherwise have the right to submit it)
under the project's license. Commits without a sign-off cannot be merged.

## Development setup

### Prerequisites

- Docker and Docker Compose
- `openssl` (used by `setup.sh` to generate secrets)
- Python 3.11+ and Node.js 20+ (only needed for running the test suites or
  the dev servers outside containers)

### Quick start (Docker)

```bash
git clone https://github.com/trustlab-dev/blackbar.git
cd blackbar
cp .env.example .env        # review and edit as needed
bash setup.sh               # generates secrets, starts services, creates the admin user
```

`setup.sh` generates `MONGO_PASSWORD`, `JWT_SECRET`, and
`LLM_API_KEY_ENCRYPTION_KEY` into `.env` if they are not already set, brings up
MongoDB and the backend, creates the admin user, and writes all initial
credentials to a gitignored `INITIAL_CREDS.txt` (mode 600). Copy those into a
password manager and delete the file. The frontend comes up at
`http://localhost:3000`, the backend at `http://localhost:8000`.

### Backend development

The backend is FastAPI + Motor (async MongoDB driver). Install it in editable
mode with the dev extras:

```bash
pip install -e "backend/.[dev]"
```

From `backend/`:

```bash
pytest                      # run the test suite (pytest + testcontainers)
ruff check src tests        # lint
black src tests             # format
mypy src                    # type-check (permissive baseline today)
```

Tests use [testcontainers](https://testcontainers.com/) to spin up a real
MongoDB, so Docker must be running. The coverage gate is **≥ 80%**
(`fail_under = 80` in `backend/pyproject.toml`).

### Frontend development

The frontend is React 18 + TypeScript 5.6, built with Vite and tested with
Vitest + MSW.

```bash
cd frontend
npm install
npm run dev                 # Vite dev server
npm run test                # Vitest (watch mode)
npm run test:run            # Vitest single run
npm run test:coverage       # Vitest with coverage
npm run build               # tsc --noEmit && vite build
npm run lint                # eslint
```

The frontend coverage gate is **≥ 70%**.

## Branch naming

Branches follow a `type/short-description` pattern, matching the commit-type
vocabulary below:

- `feat/` — new functionality
- `fix/` — bug fixes
- `chore/` — tooling, dependencies, repo housekeeping
- `test/` — test-only changes
- `docs/` — documentation-only changes

Example: `feat/case-bulk-export`, `fix/jwt-expiry-tz`.

## Commit messages

BlackBar uses [Conventional Commits](https://www.conventionalcommits.org/):
`type(scope): subject`.

```
feat(cases): add bulk close action
fix(auth): respect JWT_EXPIRATION env var
test(components): 100% on CaseForm
docs: refresh data-model diagram for case_team peers
chore: bump pillow to 11.0
```

Common types: `feat`, `fix`, `chore`, `test`, `docs`, `refactor`. The scope is
optional but encouraged (e.g. `auth`, `cases`, `components`, `packs`). Keep the
subject in the imperative mood and under ~70 characters. Remember the DCO
sign-off (`-s`).

## Pull request checklist

Before opening a PR, confirm:

- [ ] Tests added or updated for the change
- [ ] Backend coverage gate passes (`pytest`, ≥ 80%)
- [ ] Frontend coverage gate passes (`npm run test:coverage`, ≥ 70%)
- [ ] Lint and format pass (`ruff`, `black`, `eslint`)
- [ ] Documentation updated where behaviour or setup changed
- [ ] No `tenant_*` regressions — BlackBar is single-tenant; multi-tenancy was
      removed in the pre-OSS cleanup and must not creep back in
- [ ] Every commit is signed off (`git commit -s`)
- [ ] `CHANGELOG.md` updated under `[Unreleased]` for user-facing changes

## Code review expectations

- PRs are reviewed for correctness, test coverage, and consistency with
  existing patterns. Read the surrounding code before introducing a new
  approach.
- Keep PRs focused. A PR that does one thing well is easier to review and
  safer to merge than a sprawling one.
- Respond to review feedback by pushing follow-up commits; do not force-push
  over a branch under active review unless asked.
- CI must be green before merge.

## Larger work: planning convention

Multi-step or architectural changes should start with a GitHub Discussion or
issue that lays out the goal, the rough shape, and any contract impact. Smaller
work doesn't need this — a focused PR with a clear description is enough.

## Questions

Open a GitHub Discussion or issue. For security-sensitive reports, follow
[SECURITY.md](SECURITY.md) instead of filing a public issue.
