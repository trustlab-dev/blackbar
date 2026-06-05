#!/usr/bin/env python3
"""
Seed demo data for BlackBar
Creates sample users, cases, and teams for evaluation/testing.
Safe to run multiple times — skips if demo data already exists.

Demo-user passwords are read from environment variables that setup.sh
generates randomly per install. To run this script standalone, export
the SETUP_DEMO_*_PASSWORD env vars before invoking it:

    SETUP_DEMO_ANALYST_PASSWORD=... \\
    SETUP_DEMO_REVIEWER_PASSWORD=... \\
    SETUP_DEMO_STAFF_PASSWORD=... \\
    docker compose exec backend python scripts/seed_demo_data.py

The script will fail loudly if any of these are unset, so no plaintext
demo defaults ship in this file.
"""
import asyncio
import os
import uuid
import random
import string
from datetime import datetime, timedelta

# Setup path
import sys
sys.path.insert(0, "/app")

from src.database import db
from src.users.repository import UsersRepository
from src.users.models import UserCreate, UserStatus
from src.auth.auth_service import AuthService


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(
            f"ERROR: required env var {name} is not set. "
            "seed_demo_data.py expects setup.sh to generate demo "
            "passwords and pass them through; see the module docstring "
            "for standalone usage."
        )
    return value


# ---------------------------------------------------------------------------
# Demo Users
# ---------------------------------------------------------------------------
DEMO_USERS = [
    {
        "email": "analyst@example.com",
        "name": "Jane Analyst",
        "role": "analyst",
        "password": _require_env("SETUP_DEMO_ANALYST_PASSWORD"),
    },
    {
        "email": "reviewer@example.com",
        "name": "Bob Reviewer",
        "role": "analyst",
        "password": _require_env("SETUP_DEMO_REVIEWER_PASSWORD"),
    },
    {
        "email": "staff@example.com",
        "name": "Carol Staff",
        "role": "user",
        "password": _require_env("SETUP_DEMO_STAFF_PASSWORD"),
    },
]

# ---------------------------------------------------------------------------
# Demo Cases
# ---------------------------------------------------------------------------
DEMO_CASES = [
    {
        "title": "Request for Environmental Impact Reports",
        "description": "Requesting copies of all environmental impact assessments conducted for the proposed waterfront development project between January 2024 and December 2025.",
        "requester": {
            "name": "Sarah Mitchell",
            "email": "sarah.mitchell@greenwatch.org",
            "organization": "GreenWatch Environmental Advocacy",
        },
        "status": "in_progress",
        "priority": "high",
        "workflow_stage": "collection",
        "tags": ["environment", "development"],
    },
    {
        "title": "Annual Budget Expenditure Details",
        "description": "Request for detailed breakdown of departmental expenditures for fiscal year 2025, including consultant fees and travel expenses.",
        "requester": {
            "name": "Michael Chen",
            "email": "mchen@dailynews.com",
            "organization": "Daily News Investigative Team",
        },
        "status": "new",
        "priority": "medium",
        "workflow_stage": "intake",
        "tags": ["budget", "finance"],
    },
    {
        "title": "Police Use-of-Force Statistics 2024-2025",
        "description": "Requesting all use-of-force incident reports, statistics, and internal review outcomes for the period January 2024 through December 2025.",
        "requester": {
            "name": "Dr. Angela Torres",
            "email": "atorres@university.edu",
            "organization": "University Research Institute",
        },
        "status": "in_progress",
        "priority": "high",
        "workflow_stage": "review",
        "tags": ["police", "statistics", "public-safety"],
    },
    {
        "title": "IT Infrastructure Vendor Contracts",
        "description": "Request for copies of all current IT infrastructure and cloud services contracts, including pricing schedules and service level agreements.",
        "requester": {
            "name": "James Patel",
            "email": "jpatel@techaudit.com",
            "organization": "TechAudit Consulting",
        },
        "status": "in_progress",
        "priority": "medium",
        "workflow_stage": "redaction",
        "tags": ["IT", "contracts", "procurement"],
    },
    {
        "title": "Public Transit Ridership Data",
        "description": "Requesting monthly ridership data, route performance metrics, and service reliability reports for all public transit routes from 2023-2025.",
        "requester": {
            "name": "Lisa Wong",
            "email": "lwong@commuters.org",
            "phone": "555-0142",
            "organization": "Commuters Alliance",
        },
        "status": "completed",
        "priority": "low",
        "workflow_stage": "release",
        "tags": ["transit", "data"],
    },
    {
        "title": "Building Permit Applications - Downtown Core",
        "description": "Request for all building permit applications submitted for properties in the downtown core area during 2025.",
        "requester": {
            "name": "Robert Kim",
            "email": "rkim@archfirm.com",
            "organization": "Kim & Associates Architecture",
        },
        "status": "on_hold",
        "priority": "low",
        "workflow_stage": "pending_fee_payment",
        "clock_status": "paused",
        "clock_pause_reason": "fee_pending",
        "tags": ["building", "permits", "development"],
    },
]


def generate_tracking_number(year: int, sequence: int) -> str:
    """Generate a tracking number in the format FOI-YYYY-NNN-XXX"""
    random_code = "".join(random.choices(string.ascii_uppercase, k=3))
    return f"FOI-{year}-{sequence:03d}-{random_code}"


async def seed_demo_users(users_repo: UsersRepository) -> dict:
    """Create demo users. Returns dict of email -> user_id."""
    user_map = {}
    for u in DEMO_USERS:
        existing = await users_repo.get_by_email(u["email"])
        if existing:
            print(f"  User {u['email']} already exists, skipping.")
            user_map[u["email"]] = existing.id
            continue

        password_hash = AuthService.hash_password(u["password"])
        user_data = UserCreate(
            email=u["email"],
            name=u["name"],
            password="placeholder",
            status=UserStatus.ACTIVE,
        )
        user = await users_repo.create(user_data, password_hash)
        await db.users.update_one(
            {"id": user.id},
            {"$set": {"role": u["role"]}},
        )
        user_map[u["email"]] = user.id
        print(f"  Created user: {u['name']} ({u['email']}) — role: {u['role']}")

    return user_map


async def seed_demo_cases(user_map: dict, admin_user_id: str) -> list:
    """Create demo cases. Returns list of created case IDs."""
    # Check if demo cases already exist
    existing = await db.cases.count_documents({"tags": "demo-data"})
    if existing > 0:
        print(f"  {existing} demo cases already exist, skipping.")
        return []

    analyst_ids = [
        uid for email, uid in user_map.items()
        if email in ("analyst@example.com", "reviewer@example.com")
    ]

    now = datetime.utcnow()
    case_ids = []

    for i, c in enumerate(DEMO_CASES, start=1):
        case_id = str(uuid.uuid4())
        tracking = generate_tracking_number(now.year, i)

        # Spread received dates over the past 60 days
        days_ago = random.randint(5, 60)
        received = now - timedelta(days=days_ago)
        due = received + timedelta(days=30)

        # Assign analysts round-robin
        assignee_id = analyst_ids[i % len(analyst_ids)] if analyst_ids else admin_user_id

        case_doc = {
            "id": case_id,
            "tracking_number": tracking,
            "title": c["title"],
            "description": c["description"],
            "status": c["status"],
            "priority": c["priority"],
            "requester": c["requester"],
            "assigned_user_ids": [assignee_id],
            "assignee": assignee_id,
            "privacy_officer_id": admin_user_id,
            "workflow_stage": c.get("workflow_stage", "intake"),
            "clock_status": c.get("clock_status", "running"),
            "clock_pause_reason": c.get("clock_pause_reason"),
            "total_paused_days": 0,
            "tags": c.get("tags", []) + ["demo-data"],
            "metadata": {},
            "due_date": due,
            "received_date": received,
            "created_at": received,
            "updated_at": now,
            "created_by": admin_user_id,
            "comments": [],
            "audit_log": [
                {
                    "action": "case_created",
                    "user_id": admin_user_id,
                    "username": "Admin",
                    "timestamp": received,
                    "details": {"source": "demo_seed"},
                }
            ],
            "document_ids": [],
            "case_team": [],
            "all_records_uploaded": False,
        }
        await db.cases.insert_one(case_doc)
        case_ids.append(case_id)
        print(f"  Created case: {tracking} — {c['title'][:50]}...")

    return case_ids


async def seed_demo_team(user_map: dict, admin_user_id: str):
    """Create a demo team."""
    existing = await db.teams.find_one({"name": "FOI Analysts"})
    if existing:
        print("  Team 'FOI Analysts' already exists, skipping.")
        return

    member_ids = [uid for uid in user_map.values()]
    if admin_user_id not in member_ids:
        member_ids.append(admin_user_id)

    team_doc = {
        "id": str(uuid.uuid4()),
        "name": "FOI Analysts",
        "description": "Primary team handling FOI request analysis and review",
        "manager_id": admin_user_id,
        "member_ids": member_ids,
        "auto_assign": True,
        "round_robin": True,
        "active_cases": 0,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "created_by": admin_user_id,
    }
    await db.teams.insert_one(team_doc)
    print(f"  Created team: FOI Analysts ({len(member_ids)} members)")


async def main():
    print("=" * 50)
    print("  Seeding demo data...")
    print("=" * 50)

    users_repo = UsersRepository(db)

    # Find admin user to use as creator
    admin = await db.users.find_one({"role": "admin"})
    if not admin:
        admin = await db.users.find_one({"role": "owner"})
    if not admin:
        print("ERROR: No admin user found. Run setup.sh first.")
        return

    admin_user_id = admin["id"]
    print(f"\nUsing admin: {admin.get('name', admin.get('email'))} ({admin_user_id})")

    # Seed users
    print("\n--- Users ---")
    user_map = await seed_demo_users(users_repo)

    # Seed cases
    print("\n--- Cases ---")
    await seed_demo_cases(user_map, admin_user_id)

    # Seed team
    print("\n--- Teams ---")
    await seed_demo_team(user_map, admin_user_id)

    print("\n" + "=" * 50)
    print("  Demo data seeding complete!")
    print("")
    print("  Demo users created (passwords are written to INITIAL_CREDS.txt):")
    for u in DEMO_USERS:
        print(f"    {u['email']} ({u['role']})")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
