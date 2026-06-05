#!/usr/bin/env bash
#
# demo_snapshot.sh — capture the curated demo database as the "golden snapshot".
#
# Run this LOCALLY (or wherever you curated the demo) AFTER you have:
#   1. seeded the demo cases/documents, and
#   2. opened each demo document so its AI suggestions were generated and
#      cached into MongoDB (this step needs a real LLM key configured).
#
# The resulting archive is a self-contained copy of the whole `blackbar`
# database — documents, their PDF bytes, and the cached `ai_suggestions`.
# Transfer it to the demo VM; scripts/demo_reset.sh restores it nightly so the
# public demo never needs an LLM key.
#
# Usage:
#   scripts/demo_snapshot.sh [OUTPUT_ARCHIVE]
#   (default OUTPUT_ARCHIVE: deploy/demo/golden-snapshot.archive.gz)
#
# Env overrides:
#   COMPOSE   docker compose invocation (default: "docker compose")
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Load MONGO_USERNAME / MONGO_PASSWORD from .env if present.
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

MONGO_USERNAME="${MONGO_USERNAME:-blackbar}"
DB_NAME="${MONGODB_DB_NAME:-blackbar}"
SNAPSHOT="${1:-deploy/demo/golden-snapshot.archive.gz}"
COMPOSE="${COMPOSE:-docker compose}"

if [ -z "${MONGO_PASSWORD:-}" ]; then
  echo "error: MONGO_PASSWORD is not set (export it or put it in .env)" >&2
  exit 1
fi

mkdir -p "$(dirname "$SNAPSHOT")"

echo "Dumping database '$DB_NAME' -> $SNAPSHOT ..."
$COMPOSE exec -T mongodb mongodump \
  --username "$MONGO_USERNAME" --password "$MONGO_PASSWORD" \
  --authenticationDatabase admin \
  --db "$DB_NAME" --archive --gzip > "$SNAPSHOT"

echo "Wrote $(du -h "$SNAPSHOT" | cut -f1) -> $SNAPSHOT"
echo "Next: copy this archive to the demo VM and run scripts/demo_reset.sh,"
echo "then install the nightly timer (see DEPLOY-DEMO.md)."
