# Security Policy

BlackBar handles Freedom of Information case material, uploaded documents, and
redaction data. We take security reports seriously and appreciate responsible
disclosure.

## Supported versions

BlackBar is pre-1.0. Only the current minor release line receives security
fixes.

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |
| < 0.1   | :x:                |

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Please report privately using one of:

1. **GitHub Private Vulnerability Reporting** — use the "Report a vulnerability"
   button under the repository's *Security* tab. This is the preferred channel.
2. **Email** — `security@blackbar.example`
   <!-- TBD: placeholder address. The real security contact domain is pending
        creation of the `blackbar` GitHub org. Update before public release. -->

Please include:

- A description of the issue and its impact
- Steps to reproduce (proof-of-concept where possible)
- The affected version or commit
- Any suggested remediation

### Embargo and disclosure

- We aim to acknowledge a report within **3 business days**.
- We will work with you to validate the issue, develop a fix, and agree on a
  disclosure timeline.
- Standard embargo target is **90 days** from acknowledgement, or until a fix
  ships — whichever comes first. We will coordinate earlier or later disclosure
  where the situation warrants it.
- We are happy to credit reporters in the release notes unless you prefer to
  remain anonymous.

## CRITICAL: rotate pre-OSS default credentials

Earlier (pre-open-source) builds of BlackBar shipped a setup helper,
`create_admin_simple.py`, that created an administrator account with a
**hard-coded default**:

- Email: `admin@blackbar.app`
- Password: `admin123`

That script has been **deleted** from the repository, but it does not retract
credentials from systems where it was already run.

**If you ever deployed a pre-OSS BlackBar build, you must immediately:**

1. Log in and **rotate the `admin@blackbar.app` password**, or delete that
   account entirely if you have another administrator.
2. **Rotate any demo / seed-data account passwords.** Older builds seeded demo
   accounts (e.g. `analyst123` and similar fixed passwords). Current builds
   randomize all seeded credentials and write them to a gitignored
   `INITIAL_CREDS.txt` — but pre-randomization deployments still carry the old
   predictable passwords.
3. **Rotate `JWT_SECRET`** if there is any chance it was a default or shared
   value; rotating it invalidates all existing tokens and forces re-login.
4. Review the audit log for unexpected administrator activity.

Current `setup.sh` requires an operator-supplied admin password (minimum 8
characters) and generates all other secrets randomly. There is no longer any
default credential in the codebase.

## Security posture

A summary of BlackBar's current security model, for context when assessing
reports:

- **Deployment model** — single-tenant, self-hosted. There is no multi-tenant
  isolation layer; each deployment serves one organisation. Operators are
  responsible for network, TLS, and host hardening.
- **Authentication** — JWT-based, issued and verified with **PyJWT**
  (`PyJWT[crypto]`). Tokens carry a `realm` claim (`public` / `org` / `admin`);
  the `org` realm replaced the former `tenant` realm in the single-tenant
  cleanup.
- **Password storage** — bcrypt hashing via `passlib` / `bcrypt`. Plaintext
  passwords are never stored.
- **Authorization** — a 4-tier system role model (`admin / analyst / user /
  guest`) plus a separate per-case team-role taxonomy. See the architecture
  docs for details.
- **Secrets** — `setup.sh` generates `JWT_SECRET`, `MONGO_PASSWORD`, and
  `LLM_API_KEY_ENCRYPTION_KEY` at install time. LLM provider API keys are
  encrypted at rest with a Fernet key.
- **Telemetry** — no telemetry is sent by default. Sentry and OpenTelemetry
  integrations exist but are opt-in via environment configuration.
- **License** — Apache License, Version 2.0.

## Scope

In scope: the BlackBar backend, frontend, and the deployment scripts in this
repository. Out of scope: vulnerabilities in third-party dependencies (report
those upstream, though we appreciate a heads-up), and issues that require
pre-existing administrative access or a compromised host.
