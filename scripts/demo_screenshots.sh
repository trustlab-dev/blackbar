#!/usr/bin/env bash
#
# demo_screenshots.sh — capture the BlackBar demo screenshot set.
#
# Drives a headless Chromium (via the official Playwright Docker image, so no
# host Node/browser is needed) against a RUNNING demo stack, and writes PNGs to
# docs/screenshots/. The browser logs in, navigates the core flows, and shoots
# each screen at 1440x900 (2x for crispness). See scripts/demo_screenshots.cjs
# for the per-screen logic.
#
# Prereqs:
#   - the demo stack is up:
#       docker compose -f docker-compose.yml -f docker-compose.demo.yml up -d
#   - it's seeded with at least one case that has a processed document
#     (see DEPLOY-DEMO.md / the seed_* scripts).
#
# Usage:
#   ADMIN_PASSWORD=secret ./scripts/demo_screenshots.sh
#   ONLY=11,12 ADMIN_PASSWORD=secret ./scripts/demo_screenshots.sh   # subset
#
# Env (ADMIN_PASSWORD required; everything else has a sensible default):
#   ADMIN_EMAIL     admin login            (default: admin@blackbar.demo)
#   ADMIN_PASSWORD  admin password         (REQUIRED)
#   OUT_DIR         output directory       (default: docs/screenshots)
#   BASE_URL        app URL the browser hits (default: http://localhost:3000)
#   NETWORK         docker network         (default: host)
#                   For an in-network run set NETWORK=<project>_blackbar-network
#                   and BASE_URL=http://frontend:3000.
#   CASE_ID/DOC_ID  override auto-discovery
#   ONLY            comma list of shot prefixes to capture (e.g. 11,12)
#   PW_IMAGE        Playwright image tag
#   COMPOSE         compose invocation used for auto-discovery
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

ADMIN_EMAIL=${ADMIN_EMAIL:-admin@blackbar.demo}
OUT_DIR=${OUT_DIR:-docs/screenshots}
BASE_URL=${BASE_URL:-http://localhost:3000}
NETWORK=${NETWORK:-host}
PW_IMAGE=${PW_IMAGE:-mcr.microsoft.com/playwright:v1.49.0-jammy}
COMPOSE=${COMPOSE:-docker compose -f docker-compose.yml -f docker-compose.demo.yml}
ONLY=${ONLY:-}

if [ -z "${ADMIN_PASSWORD:-}" ]; then
  echo "error: set ADMIN_PASSWORD to the demo admin's password" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
OUT_ABS=$(cd "$OUT_DIR" && pwd)

# Auto-discover a case + a processed PDF document unless overridden.
if [ -z "${CASE_ID:-}" ] || [ -z "${DOC_ID:-}" ]; then
  read -r CASE_ID DOC_ID < <($COMPOSE exec -T backend python - <<'PY' || true
import asyncio
from src.database import db
async def main():
    q = {"mime_type": "application/pdf", "content_file_id": {"$exists": True}}
    doc = (await db.documents.find_one({**q, "filename": {"$regex": "proposal"}})
           or await db.documents.find_one(q))
    if doc:
        print(doc["case_id"], doc["id"])
asyncio.run(main())
PY
)
fi

if [ -z "${CASE_ID:-}" ] || [ -z "${DOC_ID:-}" ]; then
  echo "error: no case with a processed document found — seed the demo first" >&2
  exit 1
fi

echo "Capturing screenshots -> $OUT_DIR   (case=$CASE_ID doc=$DOC_ID)"

docker run --rm \
  --network "$NETWORK" \
  -v "$PWD/scripts:/scripts:ro" \
  -v "$OUT_ABS:/out" \
  -e BASE_URL="$BASE_URL" \
  -e CASE_ID="$CASE_ID" \
  -e DOC_ID="$DOC_ID" \
  -e ADMIN_EMAIL="$ADMIN_EMAIL" \
  -e ADMIN_PASSWORD="$ADMIN_PASSWORD" \
  -e ONLY="$ONLY" \
  "$PW_IMAGE" \
  sh -c 'cd /tmp \
    && npm init -y >/dev/null 2>&1 \
    && npm i --no-audit --no-fund playwright-core@1.49.0 >/tmp/npm.log 2>&1 \
    && NODE_PATH=/tmp/node_modules node /scripts/demo_screenshots.cjs'

echo "Done. PNGs in $OUT_DIR/"
