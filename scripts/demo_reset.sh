#!/usr/bin/env bash
#
# demo_reset.sh — restore the golden snapshot, wiping all visitor changes.
#
# Idempotent and safe to run on a schedule (see deploy/demo/*.timer). Intended
# for the public demo VM. `mongorestore --drop` drops each collection in the
# archive before restoring it, so anything a visitor created/edited in the
# app's collections is discarded and the curated state is restored exactly.
#
# Usage:
#   scripts/demo_reset.sh [INPUT_ARCHIVE]
#   (default INPUT_ARCHIVE: deploy/demo/golden-snapshot.archive.gz)
#
# Env overrides:
#   COMPOSE   docker compose invocation
#             (default: "docker compose -f docker-compose.yml -f docker-compose.demo.yml")
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

MONGO_USERNAME="${MONGO_USERNAME:-blackbar}"
SNAPSHOT="${1:-deploy/demo/golden-snapshot.archive.gz}"
COMPOSE="${COMPOSE:-docker compose -f docker-compose.yml -f docker-compose.demo.yml}"

if [ -z "${MONGO_PASSWORD:-}" ]; then
  echo "error: MONGO_PASSWORD is not set (export it or put it in .env)" >&2
  exit 1
fi
if [ ! -f "$SNAPSHOT" ]; then
  echo "error: snapshot not found: $SNAPSHOT" >&2
  exit 1
fi

ts() { date -u +%FT%TZ; }

echo "[$(ts)] Restoring demo database from $SNAPSHOT ..."
$COMPOSE exec -T mongodb mongorestore \
  --username "$MONGO_USERNAME" --password "$MONGO_PASSWORD" \
  --authenticationDatabase admin \
  --drop --gzip --archive < "$SNAPSHOT"

# Restart the backend so any in-process caches are cleared.
$COMPOSE restart backend >/dev/null

echo "[$(ts)] Demo reset complete."
