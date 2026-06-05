# Deploying BlackBar as a daily-resetting public demo

This guide deploys BlackBar as a public demo on a single VM that **resets to a
curated state every night** and runs with **no live LLM** — so there are no API
costs and nothing for visitors to abuse.

## How it works

The demo is driven by a **golden snapshot**: a one-time `mongodump` of a
database you've curated (demo cases, documents, and their *pre-generated* AI
redaction suggestions). The whole app state — including the PDF bytes and the
cached `ai_suggestions` — lives in MongoDB, so the snapshot is self-contained.

- **No LLM key on the demo box.** With `BLACKBAR_DEMO_MODE=true`:
  - the backend serves the cached suggestions and **refuses live regeneration**
    (it never calls an LLM, never overwrites the snapshot), and
  - the viewer **hides the "Regenerate" controls**.
  - Visitors can still review → accept/reject → **export** redactions (export
    never touches the LLM).
- **Nightly reset.** A systemd timer restores the golden snapshot, wiping
  anything visitors changed.

Result: the full AI-redaction experience is demoable, deterministically, for
free.

Files referenced below:
- [`docker-compose.demo.yml`](docker-compose.demo.yml) — demo overlay (demo mode on, loopback-only ports, no dev mounts)
- [`scripts/demo_snapshot.sh`](scripts/demo_snapshot.sh) — capture the golden snapshot (run locally)
- [`scripts/demo_reset.sh`](scripts/demo_reset.sh) — restore it (run on the VM, on a schedule)
- [`deploy/demo/blackbar-demo-reset.service`](deploy/demo/blackbar-demo-reset.service) / [`.timer`](deploy/demo/blackbar-demo-reset.timer) — the nightly schedule

---

## Prerequisites

- A VM with **≥ 4 GB RAM** (the backend bundles LibreOffice + Tesseract for OCR;
  2 GB is tight). 2 vCPU is comfortable. Any provider — DigitalOcean, Hetzner,
  etc. Resize up later if you need more headroom.
- **Docker Engine + Docker Compose v2** on the VM.
- A **domain name** pointed (A/AAAA record) at the VM, for TLS.

---

## Part A — Build the golden snapshot (do this locally, once)

This is the only step that needs a real LLM key.

1. Bring up your local stack with an LLM configured, then seed the demo data
   (cases, documents) the way you want it to appear.
2. In the app, open **each** demo document and let its AI suggestions generate
   so they get cached into MongoDB. Curate them (accept/reject) until the demo
   looks the way you want — whatever is cached is exactly what visitors will
   see.
3. Capture the snapshot:
   ```bash
   ./scripts/demo_snapshot.sh
   # writes deploy/demo/golden-snapshot.archive.gz
   ```

> The snapshot is a binary archive. Don't commit it to a public repo if your
> demo data is sensitive — transfer it to the VM out-of-band (scp) instead.
> (BlackBar's bundled demo data is synthetic, so committing it is fine.)

---

## Part B — Provision the VM and first deploy

```bash
# On the VM:
sudo git clone <your-repo-url> /opt/blackbar
cd /opt/blackbar

# Copy the snapshot over from your machine, e.g.:
#   scp deploy/demo/golden-snapshot.archive.gz user@vm:/opt/blackbar/deploy/demo/

cp .env.example .env
```

Edit `.env` and set at minimum:

| Variable | Notes |
|---|---|
| `MONGO_PASSWORD` | strong random string |
| `JWT_SECRET` | random 32+ chars |
| `LLM_API_KEY_ENCRYPTION_KEY` | a valid Fernet key. **Required to boot**, but never used in demo mode (the LLM is never invoked), so it does not need to match the key used when curating. |

You do **not** set any LLM API key. `BLACKBAR_DEMO_MODE` is forced on by the
demo overlay.

Bring it up and load the snapshot:

```bash
docker compose -f docker-compose.yml -f docker-compose.demo.yml up -d --build
./scripts/demo_reset.sh        # restores the golden snapshot
```

The app is now running on the VM's loopback: backend `127.0.0.1:8000`, frontend
`127.0.0.1:3000` (the overlay binds them to localhost so only your reverse proxy
is public).

---

## Part C — Reverse proxy + TLS

Put a proxy in front to terminate HTTPS and route traffic. Route `/api/*` to the
backend (it serves `/api/v1/...`) and everything else to the frontend. A minimal
[Caddy](https://caddyserver.com) config (`/etc/caddy/Caddyfile`) does this with
automatic Let's Encrypt certificates:

```caddyfile
demo.example.com {
    @api path /api/*
    reverse_proxy @api 127.0.0.1:8000
    reverse_proxy 127.0.0.1:3000
}
```

```bash
sudo apt install caddy        # or run caddy in a container
sudo systemctl reload caddy
```

Any proxy works (nginx, Traefik); the routing rule is the same.

> **Vite host check:** the frontend is served by the Vite dev server, which
> **rejects requests whose Host header it doesn't recognise** ("Blocked request.
> This host is not allowed."). The demo overlay handles this by setting
> `ALLOWED_HOSTS=all` (wired into [`frontend/vite.config.ts`](frontend/vite.config.ts)),
> since the dev server is only reachable through your trusted reverse proxy. To
> tighten it, set `DEMO_ALLOWED_HOSTS=demo.example.com` in `.env` and it will
> allow only that host.

**Firewall:** allow only 80/443 (and your SSH port) from the internet — the app
ports are loopback-bound, but lock the box down anyway:
```bash
sudo ufw allow OpenSSH && sudo ufw allow 80,443/tcp && sudo ufw enable
```

---

## Part D — Schedule the nightly reset

```bash
sudo cp deploy/demo/blackbar-demo-reset.service /etc/systemd/system/
sudo cp deploy/demo/blackbar-demo-reset.timer   /etc/systemd/system/
# If you cloned somewhere other than /opt/blackbar, edit WorkingDirectory and
# ExecStart in the .service file to match.
sudo systemctl daemon-reload
sudo systemctl enable --now blackbar-demo-reset.timer

# Verify:
systemctl list-timers blackbar-demo-reset.timer
sudo systemctl start blackbar-demo-reset.service   # run a reset right now to test
journalctl -u blackbar-demo-reset.service --no-pager | tail
```

The default schedule is **09:00 UTC daily** — change `OnCalendar` in the `.timer`
to suit your audience's off-peak hours.

---

## Updating the demo content

When you want to change what the demo shows: re-curate locally, re-run
`./scripts/demo_snapshot.sh`, copy the new `golden-snapshot.archive.gz` to the
VM, and run `./scripts/demo_reset.sh` (or just wait for the nightly timer).

To ship code changes: `git pull` on the VM, then
`docker compose -f docker-compose.yml -f docker-compose.demo.yml up -d --build`.

---

## Scaling & notes

- **Scaling.** Vertical: resize the VM. Horizontal: you can run more `backend`
  replicas behind the proxy, but keep **a single MongoDB** — the nightly
  drop+restore assumes one database. (For multi-node you'd move Mongo to a
  managed instance and point the snapshot/reset scripts at it via `MONGODB_URI`.)
- **Admin login.** The snapshot includes the admin user you created while
  curating; log in with that password. Public visitors use the one-click demo
  persona (enabled by demo mode) and never need credentials.
- **Why not a PaaS?** The reset model is container-native (`mongorestore` into
  the DB container). A VM where you control Docker fits it directly; a managed
  PaaS that can't `exec` into containers needs extra tooling and a managed Mongo.
