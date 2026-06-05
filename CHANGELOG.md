# Changelog

All notable changes to BlackBar are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Licence: AGPL-3.0-or-later → Apache-2.0.** The repo's LICENSE
  file is now the full Apache 2.0 text; `backend/pyproject.toml`
  SPDX, `frontend/package.json` license field, README badge and
  licence section, CONTRIBUTING, SECURITY, and DOCUMENTATION_INDEX
  all updated. Copyright line updated to "2025-2026 Matt Crossley".

## [0.1.0-rc2] - 2026-05-16

Second release candidate. Substantial AI/redaction work, public-portal
fixes, and a documentation+help refresh on top of `v0.1.0-rc1`.

### Added

- **Public-portal demo mode.** `POST /api/v1/auth/public/demo-login` is
  exposed when `BLACKBAR_DEMO_MODE=true` is set in the backend env;
  returns 404 otherwise. Mints a public-realm JWT for the
  "Jordan Park" demo persona without requiring magic-link email
  delivery. The public login page renders a `Log in as Jordan Park
  (demo)` button when the flag is on. `setup.sh` auto-enables it when
  the operator opts into seeding the TrustLab demo case.
- **TrustLab Inc / CCSA demo FOI case** (`tests/manual-test-files/trustlab-foi/`)
  — one realistic case (proposal letter, CV, evaluation memo, referee notes,
  4-message email thread) for walking through the full redaction workflow
  against meaningful content. `scripts/seed_trustlab_demo.py` loads it via
  the API; `setup.sh` offers it as an optional seed step.
- **BC FIPPA v2 jurisdiction pack** with substantially richer prompt
  structure: STEP 0 record-type framing, explicit allow/deny lists, s.22(3)
  closed-list enumeration, s.13 vs s.22 disambiguation, forbidden-reasoning
  catalogue. Output schema gains `section_subsection`, `reasoning_chain`,
  `severance_note`, `requires_human_review`, `public_interest_override_flag`.
- **Disclosure overrides as first-class entries** in BC FIPPA pack:
  s.25 public-interest override, s.3 scope exclusions.
- **Redaction-box resize and drag-to-move.** Eight handles (corners +
  edges) on the selected box; drag the body to relocate. Movement
  threshold disambiguates a real drag from a click-to-open-menu. Esc
  closes the menu; Esc again deselects.
- **AI suggestion drawer surfaces structured reasoning.** "Why" expander
  shows reasoning chain, harm identified, severance note, exceptions
  considered. Review and s.25? badges on rows the pack flagged.
- **Data-migration script** (`scripts/migrate_dates_to_bson.py`) that
  converts pre-existing ISO-string date fields in `cases` and `documents`
  to BSON Date in-place, and backfills missing `created_at` from the
  doc's `_id` ObjectId timestamp. Idempotent, with `--dry-run` flag.
- **In-app Help guide** rewritten from scratch (10 sections) covering
  the actual user journey: AI suggestions Why expander, badges,
  Generate-vs-Regenerate, LLM Configuration, Public Portal, demo
  mode, troubleshooting for real failure modes.

### Changed

- **AI suggestion prompt: single-shot classification with default-disclose
  anchor.** A true two-pass design (detection + classification LLM calls)
  was implemented and reverted; the doubled latency wasn't worth the
  recall improvement given how often operators iterate on prompts. The
  classification prompt now handles detection inline. Pack version 2.0.5.
- **LLM "regenerate" button now actually regenerates.** Previously it
  refetched cached suggestions; now passes `force_regenerate=true` so the
  backend re-calls the LLM.
- **First enabled LLM config is auto-promoted to default on create.**
  Closes the "config exists but AI says LLM not configured" trap. Error
  copy on the AI side updated accordingly.
- **OCR coordinate lookup tightened.** Both the frontend `findTextInOCR`
  and the backend `find_text_in_ocr_data` now strip edge punctuation,
  prefer single-word exact match, and only fall back to multi-word
  accumulation with strict equality. Fixes ~3× over-wide bboxes on
  phone-number-style suggestions.
- **All `db.cases` + `db.documents` date writers normalised on BSON
  Date** (raw `datetime.utcnow()`). The previous mix of `.isoformat()`
  serialisation and raw datetimes made Mongo date queries unreliable
  and surfaced as `'str' object has no attribute 'isoformat'` errors
  on the read side. The defensive `_iso()` helper on public_routes
  reads stays, covering any pre-migration data still on disk.

### Fixed

- **Public dashboard 500 on case-detail.** `/cases/public/my-requests`
  was returning `str(case["_id"])` (the Mongo ObjectId) as the case
  `id`; the detail endpoint then looked up by ObjectId AND tripped on
  `.isoformat()` on string date fields. Both endpoints now use the
  app-level UUID consistently and tolerate either date shape.
- **"Submitted: December 31, 1969" on the public dashboard.** The
  authenticated case-create route wasn't setting `created_at`. New
  cases write it; existing cases backfill from their `_id` ObjectId.
- **BC FIPPA fee schedule** (BC Reg 155/2012 Schedule 1, verified at
  bclaws.gov.bc.ca): search/preparation rates are per quarter-hour, not
  per half-hour. Pack was off by 2× on every fee estimate. Colour copy,
  scanned electronic rates, and commercial-applicant note added.
- **BC FIPPA s.10 extension grounds**: replaced loose paraphrase with the
  statutory list (s.10(1)(a)–(d)). Misattributed "s.23 third-party
  notification" extension bullet removed; s.10(1.1) Commissioner
  extension noted.
- **Frontend axios client** stopped setting `Content-Type: application/json`
  as a global default, which had been disabling multipart `FormData`
  uploads (file uploads were rejected with `422 / file missing`).
- **Documentation tree reset** — deleted ~26k lines of internal-process
  artefacts (RFCs, phase plans, design specs, superseded operations docs,
  empty role-naming stubs). Surviving docs updated to match current
  code state, including a full rewrite of `docs/api/AI_PROMPT_SYSTEM.md`
  and `docs/guides/SUGGESTION_OVERLAY_GUIDE.md`.

### Removed

- `docs/_RFCs/`, `docs/superpowers/`, `docs/operations/`,
  `docs/features/`, `docs/SECURITY_AUDIT.md`, `docs/ROADMAP.md`,
  `docs/KNOWN_ISSUES.md`, and the `docs/standards/ROLE_NAMING.md`/
  `ROLE_SCHEMA.md` stubs.
- Dead `fabric` / `@types/fabric` / `konva` / `react-konva` deps from
  `frontend/package.json` and `package-lock.json`. Not imported
  anywhere in source.

## [0.1.0] - Unreleased

Initial open-source release. The release tag (`v0.1.0`) lands at the end of
the OSS-preparation arc; this entry summarizes the changes made across that
work so contributors landing in the repo for the first time can see the shape
of what they're inheriting.

### Added

- **Test infrastructure and coverage.** Comprehensive automated test suite:
  ~2,141 backend tests (pytest + testcontainers MongoDB) and ~943 frontend
  tests (Vitest + Testing Library + MSW). Backend coverage gate `≥ 80%`;
  frontend gate `≥ 70%`. All security-critical paths verified at 100% line
  + branch coverage (auth services, RBAC permissions, release-package
  generation, OCR/conversion pipeline, manual redaction routes, JWT
  middleware, LLM key encryption, final-PDF redaction).
- **`pyproject.toml`** consolidating project metadata, pytest config,
  coverage thresholds, and `ruff` / `black` / `mypy` settings.
- **Vite + Vitest + MSW** frontend build and test stack (replaces the
  archived `react-scripts` / CRA-bundled Jest).
- **`pytest-timeout`** integration on the backend suite for hang protection.
- **`INITIAL_CREDS.txt` flow** in `setup.sh`: demo accounts now get
  randomly-generated passwords on first run, written to a gitignored file
  with rotation guidance.
- **CONTRIBUTING.md**, **SECURITY.md**, **CODE_OF_CONDUCT.md**,
  **CHANGELOG.md** (this file), and a refreshed README + SETUP_GUIDE.
- **Documentation:** dual-role-taxonomy reference (`docs/standards/ROLES.md`),
  rewritten architecture docs (5 of 6), and a Mermaid system-overview
  diagram replacing the previous excalidraw file.

### Changed

- **Single-tenant architecture.** Multi-tenancy was removed wholesale. All
  `tenant_*` symbols, database namespacing, subdomain-based routing, and
  related conditionals were deleted. BlackBar is now a single-tenant,
  self-hosted application.
- **Mega-router decomposition.** `cases/routes.py` (1995 LoC) was split
  into `routes` / `queue_routes` / `collection_link_routes` /
  `release_routes` / existing sub-routers; `documents/routes.py` (2017 LoC)
  was split into `routes` / `redaction_routes` (manual) /
  `redaction_suggestion_routes` (AI) / `attachment_routes` /
  `document_status_routes` / `search_routes` / existing sub-routers.
  Mounted via FastAPI `include_router`; URL space unchanged.
- **Frontend axios client consolidation.** Three parallel HTTP clients
  (`api.ts`, `api/index.ts`, `api/client.ts`) collapsed into a single
  `api/client.ts`.
- **Shared viewer coordinate math** extracted into
  `components/viewer/coordinates.ts` (pure functions, fully unit-tested).
- **JWT library swap.** `python-jose` (CVE history) replaced with
  `PyJWT[crypto]`.
- **DOCX→PDF conversion** now goes through LibreOffice only; `docx2pdf`
  dependency dropped.
- **TypeScript upgraded** 4.9.5 → 5.6.x.
- **`pii_detection.py` / Presidio** integration is deactivated by default.
  README's "Presidio-based PII detection" feature claim has been adjusted
  accordingly; instructions for opting in live in the documentation.

### Breaking

- **JWT `realm` claim renamed** from `tenant` to `org`. All existing tokens
  are invalidated on upgrade; users must re-authenticate. Single-tenant
  deployments absorb a brief re-login on first deploy.
- **API response field renames:**
  - `tenant_role` → `role` in `/api/v1/auth/users/search`
  - `ContributorUploadInfo.tenant_name` → `org_name` in
    `/api/v1/workflow/contribute/{contributor_id}`
- **Frontend environment-variable renames** (Vite convention):
  - `REACT_APP_API_URL` → `VITE_API_URL`
  - `REACT_APP_SENTRY_DSN` → `VITE_SENTRY_DSN`
  - `REACT_APP_ENVIRONMENT` → `VITE_ENVIRONMENT`
  - `REACT_APP_VERSION` → `VITE_VERSION`
  Update `.env`, container env, or deployment templates. Old `REACT_APP_*`
  names are not read.
- **Frontend npm scripts** changed from CRA's `start` / `test` to
  Vite's `dev` / `test` / `test:run` / `test:coverage` / `preview`.
- **Removed endpoints** (previously dead / unreachable):
  - `cases/routes.py` `/generate-letter` collapsed to a clean `501` stub.
- **Removed files in the public distribution:** `samples/` (Rotary Youth
  Exchange and similar personal documents from a maintainer's machine),
  `create_admin_simple.py` (a setup helper that shipped a plaintext default
  admin credential), `tests/` personal `.eml` fixtures, and the
  `migrate_to_single_tenant.py` one-shot migration script. **Operators of
  any pre-OSS BlackBar deployment must rotate the
  `admin@blackbar.app` / `admin123` default; see SECURITY.md.**

### Fixed

- **Release-package data leak (CRITICAL).** `release_package_service.py`
  previously swallowed `apply_redactions_to_pdf` exceptions and fell back
  to the unredacted original document, finishing the package as DRAFT.
  Operators could release unredacted content unknowingly. Redaction
  failures now mark the package `failed` and stop the pipeline.
- **JWT expiration on non-UTC hosts.** `create_access_token` used
  `datetime.utcnow().timestamp()`, which on non-UTC hosts inflated the
  `exp` claim by the local TZ offset. Tokens lasted longer than intended.
  Replaced with `time.time()`.
- **Validation handler crash.** `validation_exception_handler` raised a
  `TypeError` when Pydantic V2 `RequestValidationError.errors()` carried
  a non-serializable `ValueError` in `ctx.error` from custom validators —
  routes with failing custom validators returned `500` instead of `422`.
  Errors are now sanitized via `jsonable_encoder` with an `Exception`
  fallback.
- **Broken activation flow.** `POST /api/v1/auth/activate-owner` was
  mounted behind the JWT middleware, but invitation recipients have no
  JWT yet by design. Every legitimate activation HTTP request was
  rejected with `401` before the handler ran. The path is now in the
  public allowlist; the handler authenticates via the activation token
  in the request body.
- **Broken contributor-upload flow.** Same class as the activation bug:
  `/api/v1/cases/collect/{token}` upload URLs require no JWT (the token
  in the path is the auth), but the middleware demanded one. The
  `/api/v1/cases/collect/` prefix is now in the public allowlist.
- **Hardcoded organization name.** `workflow/routes.py` previously
  hardcoded `tenant_name = 'Blackbar'` in five places, so contributor
  invitation and case-transfer emails always said "Blackbar" regardless
  of the configured `system_config.org_name`. Now reads from config.
- **Collection-link Z-suffix datetime crash.** `is_link_valid` parsed
  ISO timestamps with a `Z` suffix as tz-aware but compared against
  naive `datetime.utcnow()`, raising `TypeError` on JSON-deserialized
  inputs. Both sides are now tz-aware.
- **Dead production endpoints.** Several routes were unreachable due to
  registration-order shadowing by catch-all `/{id}` paths:
  - `GET /api/v1/cases/search` and `/deadline-dashboard` (queue routes)
  - `GET /api/v1/cases/public/health`
  Sub-routers are now included before catch-all paths so the more
  specific routes win FastAPI's first-match resolution.
- **Misleading `/api/v1/config/*` claim.** The status / priority / timeline
  endpoints documented themselves as public but the middleware required
  a JWT. They are now actually public (the data is zero-PII reference
  enums).
- **Frontend FormData uploads.** `CaseDocuments` and
  `PackManagement/PackUploader` manually set `Content-Type:
  multipart/form-data` on a `FormData` body, omitting the multipart
  boundary axios would otherwise auto-generate. The malformed request
  caused axios's promise to never resolve, hanging the upload UI.
  Headers removed so axios derives the correct `Content-Type` itself.
- **Missing `web-vitals` dependency.** `utils/telemetry.ts` imported
  `web-vitals`, but the package was never listed in `package.json` and
  never installed. `tsc --skipLibCheck` masked the issue; the
  production frontend build (`npm run build`) failed to resolve the
  module. Added `web-vitals` to dependencies.
- **Full backend test-suite hang.** Per-test motor `AsyncIOMotorClient`
  instances accumulated unclosed connections at the
  `AsyncIOMotorClient.__del__` boundary because the asyncio event
  loop had already closed when GC fired. Daemon threads piled up and
  eventually saturated the pool. Fixed by forcing `gc.collect()` in
  the `db` fixture's teardown while the loop is still alive.

### Security

- Default admin and demo credentials are no longer hard-coded. The
  former `create_admin_simple.py` helper, which created
  `admin@blackbar.app` / `admin123` in plaintext, has been deleted.
  See **SECURITY.md** for credential-rotation guidance for operators
  of any pre-OSS deployment.

[Unreleased]: https://github.com/blackbar/blackbar/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/blackbar/blackbar/releases/tag/v0.1.0
