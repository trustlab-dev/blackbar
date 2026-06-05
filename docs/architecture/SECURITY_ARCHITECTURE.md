# Security Architecture

**Status:** Active
**Applies to:** `0.1.x` (post-Phase-1.7 realm cleanup)

BlackBar is a single-tenant, self-hosted FOI redaction system. This
document covers how identity, authentication, authorization, and
related security controls work in the current code. For coordinated
vulnerability disclosure, see [`SECURITY.md`](../../SECURITY.md) at the
repository root.

---

## 1. Identity model

There are two distinct identity stores:

| Store          | Collection       | Purpose                                              |
|----------------|------------------|------------------------------------------------------|
| Internal users | `users`          | FOI staff and admins                                 |
| Public users   | `public_users`   | External FOI requesters and contributors (magic link)|

Internal users authenticate with email + password; public users
authenticate by clicking single-use magic links emailed to them.

---

## 2. Authentication

### Password-based (internal users)

- Passwords are hashed with **bcrypt** (`auth/auth_service.py`,
  `auth/security.py`).
- The login route mints a JWT via `AuthService.issue_token`.
- JWT is signed with `JWT_SECRET` (HS256). Both
  `config.py` and `auth/security.py` enforce a minimum 32-character
  secret in production.

### JWT structure

```python
{
  "sub": "<user-uuid>",           # subject
  "role": "admin",                # single role string
  "realm": "admin" | "org" | "public",
  "exp": 1735200000
}
```

Source: `backend/src/auth/auth_service.py:TokenPayload`. Legacy tokens
with a `roles` array are normalised to a single `role` on validation
for backward compatibility.

A historical `tenant` realm with `tenant_id`, `all_tenants`, and
`is_global_admin` claims no longer exists; BlackBar is single-tenant.

### Magic links (public users)

- A magic link request creates a `magic_link_tokens` document with the
  raw token's bcrypt hash and a short expiry.
- The verification endpoint exchanges a valid token for a JWT in the
  `public` realm.
- Tokens are single-use: once verified, the document's `used` flag
  flips and prevents reuse.

Source: `backend/src/auth/magic_link_routes.py`,
`backend/src/auth/magic_link_service.py`.

### Account activation (WP-001)

New internal users are created with `status="pending_activation"` and
a hashed `activation_token` with an expiry. Recipients receive a
welcome email containing the raw token; the activation endpoint
verifies and lets them set a password, after which status flips to
`active` and the token is cleared.

Source: `backend/src/auth/activation_service.py`,
`backend/src/auth/activation_routes.py`.

### Contributor tokens

Named contributors receive a long-lived (default 14 days) upload
token. The token's hash is stored on the `case_contributors` document;
the raw token is the URL path component. This is JWT-independent —
contributors don't get a JWT until they choose to register as a public
user.

---

## 3. Realms

Three realms are issued post-Phase-1.7:

| Realm    | Who                                    | Allowed surface                                 |
|----------|----------------------------------------|-------------------------------------------------|
| `admin`  | Internal users with role `admin`       | Everything, including `/admin/*`                |
| `org`    | All other internal users               | Authenticated FOI app, scoped by role           |
| `public` | Magic-link authenticated public users  | Public dashboard, own request history           |

Realm is set in the JWT at issuance time based on `user.role`
(`role == "admin"` → `admin`, else `org`). The `public` realm is
issued only by the magic-link verifier.

---

## 4. AuthMiddleware

`backend/src/core/auth_middleware.py` is the single chokepoint for
request authentication. It runs **innermost** in the middleware stack
(after CORS and correlation), validates bearer JWTs, and attaches
`request.state.user_id` and `request.state.roles`.

### Public route allowlist

Routes that are reachable without a JWT:

**Exact-match public routes:**

```
/api/v1/auth/login
/api/v1/auth/me                  (token optional)
/api/v1/auth/activate-owner      (body-token auth)
/api/v1/admin/config/public
/                                 (health)
```

**Prefix-match public routes:**

```
/health
/docs    /openapi.json    /redoc        (FastAPI docs in dev)
/api/v1/auth/public                     (magic link)
/api/v1/cases/public/                   (public request submission)
/api/v1/cases/collect/                  (body-token collection links)
/api/v1/contribute/                     (contributor magic link)
/api/v1/config/                         (status/priority/timeline enums; B19)
```

**Frontend public routes (for SPA path matching):**

```
/request    /track/    /collect/    /contribute/
```

Anything else requires a `Bearer` token. A missing token yields
`401 AUTH_REQUIRED`; a malformed header yields `401 INVALID_AUTH_HEADER`;
an expired or invalid token yields `401 INVALID_TOKEN`.

There is no `TenantMiddleware` and no cross-tenant check — single
tenant, no boundary to enforce.

---

## 5. Authorization

### User roles (4-tier)

Defined in `backend/src/auth/roles.py`:

| Role     | Level | Capability summary                                              |
|----------|------:|-----------------------------------------------------------------|
| `admin`  | 4     | Full system access — users, config, all cases, deletions        |
| `analyst`| 3     | FOI staff — create/manage cases, view all cases, redact         |
| `user`   | 2     | Limited staff — view assigned cases                             |
| `guest`  | 1     | External collaborator — view only invited cases                 |

Hierarchy is implemented as numeric levels;
`has_permission(user_role, required_role)` is a `>=` check.

### Case-team roles (7-tier, per case)

Defined in `backend/src/cases/permissions.py`. These attach to a user
*on a specific case* via the embedded `case_team` array, and grant a
per-action permission set:

| Role          | Notable permissions                                             |
|---------------|-----------------------------------------------------------------|
| `manager`     | view, edit, redact, manage_team, approve_release, reject_documents |
| `analyst`     | view, edit, redact, manage_team, approve_proposed_redactions    |
| `legal`       | view, comment, propose_redactions, contest_redactions           |
| `sme`         | view, comment, upload                                           |
| `reviewer`    | view, comment, propose, contest, reject_documents               |
| `approver`    | view, comment, propose, approve_release, reject_documents       |
| `third_party` | view, comment, propose_redactions, contest_redactions           |

Helper functions in `cases/permissions.py` (`can_create_redactions`,
`can_approve_release`, etc.) are the canonical check sites.

### Dual taxonomy — namespace collision

`analyst` appears in **both** the 4-tier user role list and the 7-tier
case-team role list. They are independent values that happen to share
a string. A user with system role `user` can hold case role `analyst`
on a single case, and vice versa.

A dedicated reconciliation lives in
[`docs/standards/ROLES.md`](../standards/ROLES.md) (Batch 4.5) — read
that before touching role-related code.

### Authorization patterns

- **Route-level** — `Depends(check_role([...]))` in router signatures.
- **Resource-level** — case routes call `get_user_role_on_case` and
  the helper predicates.
- **Frontend** — `ProtectedRoute` checks realm and role before
  rendering the protected component; it also waits for the auth
  context's `isLoading` to avoid the race-on-mount issue.

---

## 6. Secrets at rest

| Secret                          | Storage                                                    |
|---------------------------------|------------------------------------------------------------|
| User passwords                  | bcrypt hash on `users.password_hash`                       |
| Magic-link tokens               | bcrypt hash on `magic_link_tokens.token_hash`              |
| Activation tokens               | hash on `users.activation_token` (welcome service)         |
| Contributor upload tokens       | hash on `case_contributors.upload_token`                   |
| Release-package access tokens   | hash on `release_packages.access_token`                    |
| LLM provider API keys           | Fernet ciphertext on `llm_configs.api_key_encrypted`       |
| Case-transfer access tokens     | hash on `case_transfers.access_token`                      |

The Fernet key for LLM credentials is supplied via
`LLM_API_KEY_ENCRYPTION_KEY` (`backend/src/llm/encryption.py`). The
JWT signing key is `JWT_SECRET`. Both must be set in production; the
config layer hard-errors if `JWT_SECRET` is unset in
`ENVIRONMENT=production`.

`setup.sh` generates these on first run and writes the initial admin
password to `INITIAL_CREDS.txt`.

---

## 7. Transport and response hardening

A per-request HTTP middleware in `main.py` adds:

| Header                              | Value                                                |
|-------------------------------------|------------------------------------------------------|
| `X-Content-Type-Options`            | `nosniff`                                            |
| `X-Frame-Options`                   | `DENY`                                               |
| `X-XSS-Protection`                  | `1; mode=block`                                      |
| `Strict-Transport-Security`         | `max-age=31536000; includeSubDomains`                |
| `Content-Security-Policy`           | `default-src 'self'`                                 |

CORS is locked to `ALLOWED_ORIGINS` (env-var, comma-separated; defaults
to `localhost:3000` + `localhost:8000` in dev).

Rate limiting is provided by `slowapi` (`Limiter` initialised in
`main.py`) for routes that opt in via decorator.

---

## 8. Audit logging

Case mutations append `AuditLogEntry` records to the embedded
`cases.audit_log` array (model in `cases/models.py`). Each entry
captures `action`, `user_id`, `username`, `timestamp`, and an
action-specific `details` dict. This gives a per-case audit trail
without a separate collection.

Structured request-level logs (correlation ID, user ID where
available, error rates) flow through `core/logging_config.py` and
`core/correlation.py`.

---

## 9. Error response envelope

Authentication failures use the standard error envelope:

```json
{
  "error": {
    "code": "AUTH_REQUIRED" | "INVALID_AUTH_HEADER" | "INVALID_TOKEN",
    "message": "...",
    "correlation_id": "..."
  }
}
```

Authorization failures use the same envelope with `code` values from
the route layer (`FORBIDDEN`, `NOT_TEAM_MEMBER`, etc.).

---

## 10. Operational recommendations

The OSS-prep audit ratified a few non-code controls:

- Operators of pre-OSS BlackBar installs should **rotate the
  `admin@blackbar.app` / `admin123` default** that shipped in the
  now-deleted `create_admin_simple.py`. See `SECURITY.md`.
- Vulnerability disclosure goes through GitHub Private Vulnerability
  Reporting; see `SECURITY.md` for the contact details.
- Production deployments must override the `JWT_SECRET`,
  `LLM_API_KEY_ENCRYPTION_KEY`, `MONGO_PASSWORD`, and any
  observability tokens before exposing the service.

---

## 11. Related documentation

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — system overview
- [`DATA_MODELS.md`](DATA_MODELS.md) — token + user collection
  schemas
- [`../standards/ROLES.md`](../standards/ROLES.md) — dual role
  taxonomy (Batch 4.5)
- [`../../SECURITY.md`](../../SECURITY.md) — vulnerability reporting
