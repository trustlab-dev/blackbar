#!/bin/bash
# BlackBar - Single-tenant setup script
# Usage: bash setup.sh

set -e

echo "============================================"
echo "  BlackBar - FOI Request Management Setup"
echo "============================================"
echo ""

# Check for required tools
command -v docker >/dev/null 2>&1 || { echo "Error: docker is required but not installed."; exit 1; }
command -v openssl >/dev/null 2>&1 || { echo "Error: openssl is required but not installed."; exit 1; }

# Generate a 16-character alphanumeric password using a reduced alphabet
# (no 0/O/1/l/I) so that printed credentials can be copied without ambiguity.
gen_password() {
    LC_ALL=C tr -dc 'A-HJ-NP-Za-hjkmnp-z2-9' </dev/urandom | head -c 16
}

# Create .env if it doesn't exist
touch .env

# Load .env if it exists
if [ -f .env ]; then
    echo "Loading .env file..."
    set -a
    source <(grep -v '^#' .env | grep -v '^\s*$')
    set +a
fi

# --- Generate secrets if not already set ---

# Ensure .env ends with a newline before appending
[ -s .env ] && [ "$(tail -c1 .env)" != "" ] && echo "" >> .env

if [ -z "$MONGO_PASSWORD" ]; then
    MONGO_PASSWORD=$(openssl rand -base64 32 | tr -d '=/+' | head -c 32)
    echo "MONGO_PASSWORD=$MONGO_PASSWORD" >> .env
    echo "Generated MONGO_PASSWORD and saved to .env"
fi

if [ -z "$JWT_SECRET" ]; then
    JWT_SECRET=$(openssl rand -base64 48)
    echo "JWT_SECRET=$JWT_SECRET" >> .env
    echo "Generated JWT_SECRET and saved to .env"
fi

if [ -z "$LLM_API_KEY_ENCRYPTION_KEY" ]; then
    LLM_API_KEY_ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null || openssl rand -base64 32)
    echo "LLM_API_KEY_ENCRYPTION_KEY=$LLM_API_KEY_ENCRYPTION_KEY" >> .env
    echo "Generated LLM_API_KEY_ENCRYPTION_KEY and saved to .env"
fi

# Build MONGODB_URI from credentials
MONGO_USERNAME="${MONGO_USERNAME:-blackbar}"
MONGODB_URI="mongodb://${MONGO_USERNAME}:${MONGO_PASSWORD}@mongodb:27017/blackbar?authSource=admin"

# Write MONGODB_URI to .env if not already there
if ! grep -q "^MONGODB_URI=" .env 2>/dev/null; then
    echo "MONGO_USERNAME=$MONGO_USERNAME" >> .env
    echo "MONGODB_URI=$MONGODB_URI" >> .env
    echo "Generated MONGODB_URI and saved to .env"
fi

# --- Get admin credentials ---

ADMIN_EMAIL="${ADMIN_EMAIL:-}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"
ADMIN_NAME="${ADMIN_NAME:-Admin}"

if [ -z "$ADMIN_EMAIL" ]; then
    read -p "Admin email: " ADMIN_EMAIL
fi

if [ -z "$ADMIN_PASSWORD" ]; then
    read -s -p "Admin password (min 8 chars): " ADMIN_PASSWORD
    echo ""
fi

if [ ${#ADMIN_PASSWORD} -lt 8 ]; then
    echo "Error: Password must be at least 8 characters."
    exit 1
fi

ORG_NAME="${ORG_NAME:-Freedom of Information Office}"

echo ""
echo "Configuration:"
echo "  Admin email: $ADMIN_EMAIL"
echo "  Admin name:  $ADMIN_NAME"
echo "  Org name:    $ORG_NAME"
echo ""

# Start MongoDB and backend (secrets are now in .env, docker compose reads them)
echo "Starting services..."
docker compose up -d mongodb backend
echo "Waiting for MongoDB to be ready..."
sleep 5
echo "Waiting for backend to be ready..."
sleep 5

# Create admin user
echo "Creating admin user..."
docker compose exec \
    -e SETUP_ADMIN_EMAIL="$ADMIN_EMAIL" \
    -e SETUP_ADMIN_PASSWORD="$ADMIN_PASSWORD" \
    -e SETUP_ADMIN_NAME="$ADMIN_NAME" \
    -e SETUP_ORG_NAME="$ORG_NAME" \
    backend python -c '
import asyncio, os
from src.database import db
from src.users.repository import UsersRepository
from src.users.models import UserCreate, UserStatus
from src.auth.auth_service import AuthService
from src.core.database import create_indexes
from src.utils.seed_templates import seed_default_templates
from datetime import datetime

async def setup():
    admin_email = os.environ["SETUP_ADMIN_EMAIL"]
    admin_password = os.environ["SETUP_ADMIN_PASSWORD"]
    admin_name = os.environ.get("SETUP_ADMIN_NAME", "Admin")
    org_name = os.environ.get("SETUP_ORG_NAME", "Freedom of Information Office")

    await create_indexes(db)
    print("Database indexes created.")

    users_repo = UsersRepository(db)
    existing = await users_repo.get_by_email(admin_email)
    if existing:
        print(f"Admin user {existing.email} already exists.")
    else:
        password_hash = AuthService.hash_password(admin_password)
        user_data = UserCreate(
            email=admin_email,
            name=admin_name,
            password="placeholder",
            status=UserStatus.ACTIVE
        )
        user = await users_repo.create(user_data, password_hash)
        await db.users.update_one(
            {"id": user.id},
            {"$set": {"role": "admin"}}
        )
        print(f"Admin user created: {user.email}")

    config = await db.system_config.find_one({})
    if not config:
        await db.system_config.insert_one({
            "org_name": org_name,
            "primary_color": "#0366d6",
            "enable_public_requests": True,
            "enable_request_tracking": True,
            "enable_public_upload": True,
            "default_due_days": 30,
            "created_at": datetime.utcnow()
        })
        print("Default system configuration created.")

    await seed_default_templates(db.templates)
    print("Default templates seeded.")

asyncio.run(setup())
'

# Seed demo data (optional)
SEED_DEMO="${SEED_DEMO:-}"
if [ -z "$SEED_DEMO" ]; then
    read -p "Seed demo data (sample users, cases, team)? [y/N]: " SEED_DEMO
fi

DEMO_ANALYST_PASSWORD=""
DEMO_REVIEWER_PASSWORD=""
DEMO_STAFF_PASSWORD=""

if [[ "$SEED_DEMO" =~ ^[Yy]$ ]]; then
    echo "Seeding demo data..."
    DEMO_ANALYST_PASSWORD="$(gen_password)"
    DEMO_REVIEWER_PASSWORD="$(gen_password)"
    DEMO_STAFF_PASSWORD="$(gen_password)"
    docker compose exec \
        -e SETUP_DEMO_ANALYST_PASSWORD="$DEMO_ANALYST_PASSWORD" \
        -e SETUP_DEMO_REVIEWER_PASSWORD="$DEMO_REVIEWER_PASSWORD" \
        -e SETUP_DEMO_STAFF_PASSWORD="$DEMO_STAFF_PASSWORD" \
        backend python scripts/seed_demo_data.py
fi

# Seed TrustLab Inc / CCSA demo FOI case (optional)
# A complete realistic FOI case: proposal records, internal evaluation memo,
# referee notes, and a 4-message email thread. Useful for walking through
# the full case-management + redaction tooling against meaningful content.
SEED_TRUSTLAB="${SEED_TRUSTLAB:-}"
if [ -z "$SEED_TRUSTLAB" ]; then
    read -p "Seed TrustLab demo FOI case (1 case, 8 documents)? [y/N]: " SEED_TRUSTLAB
fi

if [[ "$SEED_TRUSTLAB" =~ ^[Yy]$ ]]; then
    FIXTURE_DIR="tests/manual-test-files/trustlab-foi/generated"
    if [ ! -d "$FIXTURE_DIR" ] || [ -z "$(ls -A "$FIXTURE_DIR" 2>/dev/null)" ]; then
        echo "Generating TrustLab fixtures..."
        docker compose exec -T backend pip install -q python-docx >/dev/null 2>&1 || true
        # The fixtures live outside the backend bind-mount, so generate on
        # the host instead. python-docx is widely available.
        if python3 -c "import docx" >/dev/null 2>&1; then
            python3 tests/manual-test-files/trustlab-foi/generate.py
        else
            echo "  python-docx not found on host; install with:"
            echo "    pip install python-docx"
            echo "  then re-run setup.sh, or skip the demo case."
            SEED_TRUSTLAB="n"
        fi
    fi

    if [[ "$SEED_TRUSTLAB" =~ ^[Yy]$ ]]; then
        echo "Seeding TrustLab demo case via API..."
        if python3 -c "import httpx" >/dev/null 2>&1; then
            python3 scripts/seed_trustlab_demo.py \
                --admin-email "$ADMIN_EMAIL" \
                --admin-password "$ADMIN_PASSWORD"
        else
            echo "  httpx not found on host. Install with: pip install httpx"
            echo "  Then run: python3 scripts/seed_trustlab_demo.py \\"
            echo "    --admin-email $ADMIN_EMAIL --admin-password <password>"
        fi

        # When the demo case is seeded, also enable demo-login mode so
        # the operator can click "Log in as Jordan Park (demo)" on the
        # public login page without going through magic-link emails.
        # Stored in .env so it survives container restarts.
        if ! grep -q "^BLACKBAR_DEMO_MODE=" .env 2>/dev/null; then
            echo "BLACKBAR_DEMO_MODE=true" >> .env
            echo "Enabled BLACKBAR_DEMO_MODE=true in .env (public login page will show a demo-login button)"
        elif ! grep -q "^BLACKBAR_DEMO_MODE=true" .env 2>/dev/null; then
            # Flag exists but is set to something other than true. Leave
            # the operator's setting alone — they may have deliberately
            # disabled it.
            echo "Note: BLACKBAR_DEMO_MODE is set to a non-true value in .env."
            echo "  To enable the demo-login button on the public login page,"
            echo "  set BLACKBAR_DEMO_MODE=true in .env and restart the backend."
        fi
        # Restart backend so it picks up the new env var.
        docker compose up -d backend
    fi
fi

# Write all initial credentials to a gitignored file for the operator.
CREDS_FILE="INITIAL_CREDS.txt"
{
    echo "# BlackBar - Initial Credentials"
    echo "# Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "#"
    echo "# DELETE THIS FILE AFTER COPYING THE CREDENTIALS TO YOUR PASSWORD MANAGER."
    echo "# This file is gitignored, but should not remain on disk in production."
    echo "# ROTATE ALL PASSWORDS BELOW BEFORE EXPOSING BLACKBAR TO PRODUCTION TRAFFIC."
    echo ""
    echo "admin:"
    echo "  email:    ${ADMIN_EMAIL}"
    echo "  password: ${ADMIN_PASSWORD}"
    if [[ "$SEED_DEMO" =~ ^[Yy]$ ]]; then
        echo ""
        echo "demo_analyst:"
        echo "  email:    analyst@example.com"
        echo "  password: ${DEMO_ANALYST_PASSWORD}"
        echo ""
        echo "demo_reviewer:"
        echo "  email:    reviewer@example.com"
        echo "  password: ${DEMO_REVIEWER_PASSWORD}"
        echo ""
        echo "demo_staff:"
        echo "  email:    staff@example.com"
        echo "  password: ${DEMO_STAFF_PASSWORD}"
    fi
} > "$CREDS_FILE"
chmod 600 "$CREDS_FILE"

# Start frontend
echo "Starting frontend..."
docker compose up -d frontend

echo ""
echo "============================================"
echo "  Setup complete!"
echo ""
echo "  Frontend: http://localhost:3000"
echo "  Backend:  http://localhost:8000"
echo "  Login:    $ADMIN_EMAIL"
echo ""
echo "  Initial credentials written to: $CREDS_FILE (mode 600)"
echo "  - Copy them to your password manager, then delete the file."
echo "  - Rotate all initial passwords before production use."
echo "============================================"
