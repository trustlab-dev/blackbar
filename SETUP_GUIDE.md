# BlackBar Setup Guide

BlackBar is a self-hosted, single-tenant Freedom of Information (FOI) case management system. It runs as three Docker Compose services: a frontend (port 3000), a backend API (port 8000), and MongoDB (bound to `127.0.0.1:27017`).

All commands in this guide use the modern Compose v2 (`docker compose`, no hyphen). The legacy `docker-compose` form may still work if you have it installed, but is not the supported invocation.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [What the Setup Script Does](#what-the-setup-script-does)
3. [Initial Credentials](#initial-credentials)
4. [Access Points](#access-points)
5. [Environment Configuration](#environment-configuration)
6. [User Roles](#user-roles)
7. [Creating Additional Users](#creating-additional-users)
8. [LLM Configuration](#llm-configuration)
9. [Docker Commands](#docker-commands)
10. [Database Management](#database-management)
11. [Troubleshooting](#troubleshooting)
12. [Production Deployment](#production-deployment)
13. [Security Best Practices](#security-best-practices)

---

## Quick Start

### Prerequisites

- Docker Engine with Compose v2 (`docker compose version` must work)
- `openssl` (used by `setup.sh` to generate secrets)
- Python 3 (optional but preferred — used by `setup.sh` to generate the LLM-key encryption key via `cryptography.fernet`; the script falls back to `openssl` if Python is unavailable)

### Run the setup script

From the repository root:

```bash
bash setup.sh
```

The script prompts for an admin email and password interactively. You can also pre-set them in the environment to run non-interactively:

```bash
ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD='changeme-strong-pw' SEED_DEMO=N bash setup.sh
```

Once setup completes, open `http://localhost:3000` and log in with the admin credentials.

---

## What the Setup Script Does

The setup script performs the following steps in order:

1. **Verifies tooling** — checks for `docker` and `openssl`.
2. **Generates secrets** — if `.env` does not already define them, generates `MONGO_PASSWORD` (32 chars), `JWT_SECRET` (48-byte base64), and `LLM_API_KEY_ENCRYPTION_KEY` (a Fernet key, or 32-byte base64 fallback). Each value is appended to `.env`.
3. **Builds `MONGODB_URI`** — composes the URI from `MONGO_USERNAME` (default `blackbar`) and `MONGO_PASSWORD` and writes it to `.env`.
4. **Collects admin credentials** — prompts interactively for `ADMIN_EMAIL` and `ADMIN_PASSWORD` (or reads them from the environment). The password must be at least 8 characters.
5. **Starts MongoDB and the backend** — `docker compose up -d mongodb backend` plus a short wait for both to be reachable.
6. **Creates database indexes, the admin user, default system configuration, and seeds default templates** — executed inside the backend container.
7. **Optionally seeds demo data** — if you opt in at the prompt (or set `SEED_DEMO=y`), creates three demo users (`analyst@example.com`, `reviewer@example.com`, `staff@example.com`), a sample team, and a set of sample cases. Demo passwords are randomly generated (16 chars, no ambiguous characters).
8. **Writes `INITIAL_CREDS.txt`** — contains the admin password and any demo-user passwords, with file mode `600`. Listed in `.gitignore`.
9. **Starts the frontend** — `docker compose up -d frontend`.

After the script finishes, all three services are running and the application is ready for use.

---

## Initial Credentials

On first run, BlackBar creates:

- The **admin** user, with the email and password you supplied.
- If you opt in to demo data, three **demo users** (`analyst@example.com`, `reviewer@example.com`, `staff@example.com`), each with a randomly generated 16-character password.

All initial credentials are written to `INITIAL_CREDS.txt` in the project root with file mode `600`. **This file is listed in `.gitignore` and must never be committed.**

After setup completes:

1. Open `INITIAL_CREDS.txt` and copy the credentials into your password manager.
2. Delete the file:

   ```bash
   rm INITIAL_CREDS.txt
   ```

3. **Before exposing BlackBar to production traffic, rotate all initial passwords.** Log in as the admin and change the admin password from the user-settings screen; delete or rotate the demo users from the Admin Console if you no longer need them.

If you re-run `setup.sh`, a fresh `INITIAL_CREDS.txt` is generated. Demo users that already exist will not have their passwords reset by the seed script, so the values in the new file may not match the live accounts — treat the file as authoritative only for the run that produced it.

---

## Access Points

| Service | URL | Description |
|---------|-----|-------------|
| Frontend | http://localhost:3000 | Main application interface |
| API | http://localhost:8000 | Backend REST API |
| API Documentation | http://localhost:8000/docs | Interactive Swagger/OpenAPI documentation |

---

## Environment Configuration

All configuration is managed through a `.env` file in the project root. `setup.sh` writes most variables for you, but you can pre-populate or edit `.env` yourself. There is no `.env.example` — the setup script is the source of truth for what gets written.

```bash
# MongoDB credentials (generated by setup.sh if absent)
MONGO_USERNAME=blackbar
MONGO_PASSWORD=<32-char generated value>
MONGODB_URI=mongodb://blackbar:<MONGO_PASSWORD>@mongodb:27017/blackbar?authSource=admin

# JWT signing secret (48-byte base64, generated by setup.sh if absent)
JWT_SECRET=<generated value>

# Encryption key for storing LLM API keys at rest (Fernet key, generated by setup.sh if absent)
LLM_API_KEY_ENCRYPTION_KEY=<generated value>

# Admin account credentials (only used by setup.sh on first run; not required at runtime)
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=<your value>
ADMIN_NAME=Admin

# Organisation name displayed throughout the application (used by setup.sh on first run)
ORG_NAME=Freedom of Information Office

# Optional: skip the demo-data prompt
SEED_DEMO=N
```

### Production-only variables

`docker-compose.prod.yml` parameterises the on-host bind-mount path for persistent volumes:

```bash
# Base directory for production data volumes (mongodb_data, grafana_data)
# Defaults to ./data if unset.
BLACKBAR_DATA_DIR=/var/lib/blackbar
```

The compose file resolves `${BLACKBAR_DATA_DIR:-./data}/mongodb` and `${BLACKBAR_DATA_DIR:-./data}/grafana` as the bind-mount sources. Make sure the directory exists and is writable by the container's UID before bringing the production stack up.

### Generating Secure Keys manually

`setup.sh` does this for you, but if you need to rotate keys:

```bash
# Generate a JWT secret
openssl rand -base64 48

# Generate an LLM API key encryption key (Fernet)
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

After rotating `JWT_SECRET`, all previously issued tokens are invalidated; every active user will need to log in again.

---

## User Roles

BlackBar uses two distinct role taxonomies:

### System roles (4-tier)

Stored on `user.role` and defined in `backend/src/auth/roles.py`. Listed from most to least privileged:

| Role | Level | Description |
|------|-------|-------------|
| **admin** | 4 | Full system access — manage users, teams, and all cases |
| **analyst** | 3 | FOI staff — create and manage cases, view all cases |
| **user** | 2 | Limited staff — view only assigned cases (legal, privacy, reviewers) |
| **guest** | 1 | External collaborators — view only invited cases (third parties) |

### Case-team roles (7-tier)

Per-case assignments stored on `case.team[*].role`, defined in `backend/src/cases/permissions.py`: `manager`, `analyst`, `legal`, `sme`, `reviewer`, `approver`, `third_party`. These grant per-case permissions independent of the system role.

> The system "analyst" and the case-team "analyst" share a name but are separate concepts. A user with system role `user` can still be added to a case team as `manager` and gain manager-level permissions on that case. The canonical write-up of both taxonomies lives in `docs/standards/ROLES.md` (forthcoming — Phase 4 Batch 4.5).

---

## Creating Additional Users

After initial setup, additional user accounts are created through the application:

1. Log in with an account that has the **admin** system role.
2. Navigate to the **Admin Console** from the main navigation.
3. Use the user management interface to create new accounts and assign system roles.

Case-team membership and case-team roles are managed from within each case, not from the Admin Console.

---

## LLM Configuration

BlackBar supports integration with large language models to assist with FOI case processing. Configuration is done entirely through the application interface.

1. Log in with an **admin** account.
2. Navigate to **Admin Console**.
3. Select the **LLM Configuration** tab.
4. Choose a provider and enter your API key.

Supported LLM providers:

- **OpenAI** (GPT models)
- **Anthropic** (Claude models)
- **Google** (Gemini models)
- **Cohere** (Command models)

API keys are encrypted at rest using the `LLM_API_KEY_ENCRYPTION_KEY` value from your `.env` file. Ensure this key is set before configuring LLM providers.

---

## Docker Commands

See [`DOCKER_COMMANDS.md`](DOCKER_COMMANDS.md) for the full cheatsheet. Quick reference:

```bash
docker compose up -d                    # start all services
docker compose down                     # stop all services
docker compose restart                  # restart all services
docker compose restart backend          # restart one service
docker compose logs -f                  # tail all logs
docker compose logs -f backend          # tail one service
docker compose build backend            # rebuild after backend code/dep changes
docker compose up -d --build            # rebuild and start everything
docker compose exec mongodb mongosh blackbar  # MongoDB shell
```

---

## Database Management

### View users

```bash
docker compose exec mongodb mongosh blackbar --eval 'db.users.find().pretty()'
```

(MongoDB is started with `--auth`. Use the credentials from `.env` — `MONGO_USERNAME` / `MONGO_PASSWORD` — when connecting from outside the Compose network.)

### Backup the database

```bash
docker compose exec mongodb mongodump --db blackbar --out /data/backup
```

Copy the backup to your host machine:

```bash
docker cp "$(docker compose ps -q mongodb):/data/backup" ./backup
```

### Restore the database

```bash
docker compose exec mongodb mongorestore --db blackbar /data/backup/blackbar
```

---

## Troubleshooting

### Services will not start (port conflicts)

**Cause:** another process is bound to one of the required ports.

**Fix:**

```bash
# Linux / macOS
sudo lsof -i :3000
sudo lsof -i :8000
sudo lsof -i :27017
```

```powershell
# Windows (PowerShell)
Get-NetTCPConnection -LocalPort 3000
Get-NetTCPConnection -LocalPort 8000
Get-NetTCPConnection -LocalPort 27017
```

Stop the offending process or change the host-side port mapping in `docker-compose.yml`. If you just want a clean slate:

```bash
docker compose down
bash setup.sh
```

### "Cannot connect to the Docker daemon"

- **Linux:** ensure the `docker` daemon is running (`sudo systemctl start docker`) and your user is in the `docker` group (re-log after `usermod -aG docker $USER`).
- **macOS:** start Docker Desktop and wait for the whale icon to stop animating.
- **Windows / WSL2:** Docker Desktop must be running with WSL integration enabled for your distro. Inside WSL, run the BlackBar commands from a path under your Linux home (`~/`), not under `/mnt/c/...` — bind-mount performance is dramatically worse on the Windows filesystem.

### Cannot connect to the application

**Cause:** services may still be starting.

**Fix:**

```bash
docker compose ps
docker compose logs -f
```

Wait for all services to report as healthy before attempting to connect.

### "Invalid token" or authentication errors

**Cause:** the JWT token has expired or `JWT_SECRET` was changed after the token was issued.

**Fix:** log out and log back in. If `JWT_SECRET` was rotated, every active session is invalidated and all users must log in again.

### "Permission denied" errors

**Cause:** the logged-in user does not have the required system role or case-team role for the requested action.

**Fix:** verify the user's system role in the Admin Console, and their case-team role on the affected case. Update either as needed.

### Frontend not loading or showing a blank page

**Cause:** frontend build errors or stale build cache.

**Fix:**

```bash
docker compose build --no-cache frontend
docker compose up -d frontend
docker compose logs -f frontend
```

### MongoDB connection failures

**Cause:** the MongoDB container is not running or has not finished initialising.

**Fix:**

```bash
docker compose ps mongodb
docker compose logs mongodb
docker compose up -d mongodb
```

### File-permission issues on bind-mounted volumes (production)

If you have set `BLACKBAR_DATA_DIR` to a host directory that the container UID cannot write to, MongoDB and Grafana will fail to start. Ensure the directory is owned by an appropriate user (`chown -R 999:999 $BLACKBAR_DATA_DIR/mongodb` for the official `mongo:5` image) or set permissive modes.

---

## Production Deployment

Before deploying BlackBar to a production environment, complete the following checklist:

- [ ] Generate and set a strong `JWT_SECRET` (at least 48 bytes, base64-encoded) — `setup.sh` does this automatically.
- [ ] Set a strong admin password and rotate it on first login.
- [ ] Rotate all initial credentials from `INITIAL_CREDS.txt`, then delete the file from disk.
- [ ] If demo data was seeded, either delete the demo users (`analyst@example.com`, `reviewer@example.com`, `staff@example.com`) or rotate their passwords from the Admin Console.
- [ ] Generate and set `LLM_API_KEY_ENCRYPTION_KEY` if using LLM features (auto-generated by `setup.sh`).
- [ ] Set `BLACKBAR_DATA_DIR` to a stable on-host path with appropriate ownership, then bring up the production stack:
  ```bash
  docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
  ```
- [ ] Configure HTTPS using a reverse proxy (Nginx, Caddy, or Traefik) with a valid TLS certificate.
- [ ] Restrict `ALLOWED_ORIGINS` to your production domain(s).
- [ ] Set up automated database backups on a regular schedule.
- [ ] Store backups in a separate location from the application server.
- [ ] Test the database restore procedure.
- [ ] Configure a firewall to restrict access to ports 8000 and 27017 — only the frontend port (3000) or your reverse-proxy port should be publicly accessible. (MongoDB is already bound to `127.0.0.1` in `docker-compose.yml`; verify this is preserved in production.)
- [ ] Set up log monitoring and alerting. The Docker logs from `backend`, `frontend`, and `mongodb` are the primary signal; ship them to whatever observability stack you already operate.

---

## Security Best Practices

### Secrets Management

- Never commit `.env` to version control. It is listed in `.gitignore`.
- Use strong, randomly generated values for `JWT_SECRET` and `LLM_API_KEY_ENCRYPTION_KEY`. `setup.sh` does this for you.
- Rotate secrets periodically. When rotating `JWT_SECRET`, be aware that all active sessions will be invalidated.
- Delete `INITIAL_CREDS.txt` immediately after copying its contents to your password manager.

### Network Security

- Do not expose MongoDB (port 27017) or the backend API (port 8000) directly to the public internet. Place a reverse proxy in front of the frontend and restrict direct access to internal services.
- Use HTTPS for all production traffic. Obtain certificates through Let's Encrypt or your certificate authority of choice.
- Set `ALLOWED_ORIGINS` to the exact production domain(s). Do not use wildcard origins in production.

### Access Control

- Follow the principle of least privilege when assigning system roles. Most operational users should be **analyst** or **user**, not **admin**.
- Limit the number of **admin** accounts to the minimum necessary.
- Case-team membership grants per-case permissions independent of system role — review case teams regularly and remove members who no longer need access.
- Review user accounts and roles periodically. Deactivate accounts that are no longer needed.

### Database Security

- Run automated daily backups and store them off-site or in a separate storage system.
- Test your restore procedure periodically.
- MongoDB is started with `--auth`; the username/password pair lives in `.env`. Restrict MongoDB network access to the backend service only.

### Monitoring and Auditing

- Monitor application logs for failed login attempts, unusual access patterns, and error spikes.
- Forward Docker Compose logs to a centralised logging system in production.
- Keep all dependencies up to date. Check for security advisories in both the backend (Python) and frontend (Node.js) trees.

### Dependency Updates

```bash
# Check for outdated backend dependencies
docker compose exec backend pip list --outdated

# Check for outdated frontend dependencies
docker compose exec frontend npm outdated
```

Address critical and high-severity vulnerabilities promptly. See `SECURITY.md` for the vulnerability disclosure process.
