"""Integration tests for `src.cases.team_routes` endpoints.

Phase 2.2.C (5/5). Target >=80% line coverage on src.cases.team_routes.

Endpoints under test (all mounted at /api/v1/cases/...):
    GET    /{case_id}/team
    POST   /{case_id}/team/members
    DELETE /{case_id}/team/members/{user_id}
    PUT    /{case_id}/team/members/{user_id}

**Reality pins:**
1. team_routes captures `users = db["users"]` at module load (line 27).
   Tests must monkeypatch `src.cases.team_routes.users` so collection
   reads/writes hit the per-test db.
2. The case-team-role taxonomy (7-tier: manager/analyst/legal/
   subject_matter_expert/reviewer/approver/third_party) is gated per
   system role via `ALLOWED_CASE_ROLES`. The 'sme' shorthand mentioned
   in some docs is actually `subject_matter_expert` in the
   ALLOWED_CASE_ROLES map.
3. The team-membership filter uses an EXACT-match status="active"
   string and case-sensitive user_id match (per Batch 2.2.A findings).
4. The remove/update endpoints use `request.dict(exclude_unset=True)`
   which is the Pydantic-v1-flavored API and emits a deprecation
   warning under Pydantic v2 — not fatal for the route, but loud.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorDatabase

from tests.factories import make_case, make_user

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_routes_db(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase, app):
    import src.database as db_mod
    import src.dependencies as deps_mod
    from src.cases import routes as cases_routes
    from src.cases import team_routes

    async def _override_get_db():
        return db

    app.dependency_overrides[team_routes.get_db] = _override_get_db
    app.dependency_overrides[cases_routes.get_db] = _override_get_db
    monkeypatch.setattr(deps_mod, "users", db.users)
    monkeypatch.setattr(db_mod, "users", db.users)
    # team_routes captures `users = db["users"]` at module load
    monkeypatch.setattr(team_routes, "users", db.users)

    yield db

    app.dependency_overrides.pop(team_routes.get_db, None)
    app.dependency_overrides.pop(cases_routes.get_db, None)


async def _seed_case(db: AsyncIOMotorDatabase, **overrides) -> str:
    doc = make_case(**overrides)
    await db.cases.insert_one(doc)
    return doc["id"]


async def _seed_user(
    db: AsyncIOMotorDatabase,
    role: str = "user",
    name: str = "Some User",
    email: str | None = None,
) -> str:
    doc = make_user(
        role=role,
        name=name,
        email=email or f"user-{uuid.uuid4().hex[:6]}@example.com",
    )
    await db.users.insert_one(doc)
    return doc["id"]


# ---------------------------------------------------------------------------
# GET /{case_id}/team
# ---------------------------------------------------------------------------


class TestGetCaseTeam:
    async def test_admin_can_view_team_without_membership(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        member_uid = await _seed_user(db, role="user", name="Member A")
        case_id = await _seed_case(
            db,
            case_team=[
                {
                    "user_id": member_uid,
                    "role": "analyst",
                    "status": "active",
                }
            ],
        )

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get(f"/api/v1/cases/{case_id}/team")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["case_id"] == case_id
        assert len(body["team_members"]) == 1
        assert body["team_members"][0]["user_name"] == "Member A"

    async def test_non_admin_non_team_member_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(
            db,
            case_team=[
                {
                    "user_id": "someone-else",
                    "role": "analyst",
                    "status": "active",
                }
            ],
        )
        client: AsyncClient = await authed_client_factory(role="user")
        r = await client.get(f"/api/v1/cases/{case_id}/team")
        assert r.status_code == 403

    async def test_team_get_missing_case_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/cases/ghost/team")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /{case_id}/team/members
# ---------------------------------------------------------------------------


class TestAddTeamMember:
    async def test_admin_can_add_analyst(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        target_uid = await _seed_user(db, role="analyst", name="New")
        case_id = await _seed_case(db)

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            f"/api/v1/cases/{case_id}/team/members",
            json={"user_id": target_uid, "role": "analyst"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["member"]["user_id"] == target_uid
        assert body["member"]["role"] == "analyst"
        assert body["member"]["status"] == "active"

        # Verify persistence
        case = await db.cases.find_one({"id": case_id})
        assert len(case["case_team"]) == 1

    async def test_add_member_with_disallowed_case_role_for_system_role(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """A 'user'-system-role user cannot be assigned 'analyst'
        case-team role (only legal/sme/reviewer/approver allowed for
        system 'user'). Pin the ALLOWED_CASE_ROLES validation."""
        target_uid = await _seed_user(db, role="user")
        case_id = await _seed_case(db)

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            f"/api/v1/cases/{case_id}/team/members",
            json={"user_id": target_uid, "role": "analyst"},
        )
        assert r.status_code == 400
        assert "cannot be assigned case team role" in r.json()["error"]["message"]

    async def test_add_member_user_not_found_404(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            f"/api/v1/cases/{case_id}/team/members",
            json={"user_id": "ghost-user-id", "role": "analyst"},
        )
        assert r.status_code == 404
        assert "User not found" in r.json()["error"]["message"]

    async def test_add_member_duplicate_active_member_returns_400(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        target_uid = await _seed_user(db, role="analyst")
        case_id = await _seed_case(
            db,
            case_team=[
                {
                    "user_id": target_uid,
                    "role": "analyst",
                    "status": "active",
                }
            ],
        )

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            f"/api/v1/cases/{case_id}/team/members",
            json={"user_id": target_uid, "role": "analyst"},
        )
        assert r.status_code == 400
        assert "already on the team" in r.json()["error"]["message"]

    async def test_add_member_user_role_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        target_uid = await _seed_user(db, role="analyst")
        case_id = await _seed_case(db)
        client: AsyncClient = await authed_client_factory(role="user")
        r = await client.post(
            f"/api/v1/cases/{case_id}/team/members",
            json={"user_id": target_uid, "role": "analyst"},
        )
        assert r.status_code == 403

    async def test_add_member_missing_case_404(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        target_uid = await _seed_user(db, role="analyst")
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/cases/ghost/team/members",
            json={"user_id": target_uid, "role": "analyst"},
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /{case_id}/team/members/{user_id}
# ---------------------------------------------------------------------------


class TestRemoveTeamMember:
    async def test_admin_can_remove_member(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        target_uid = await _seed_user(db, role="analyst")
        case_id = await _seed_case(
            db,
            case_team=[
                {
                    "user_id": target_uid,
                    "role": "analyst",
                    "status": "active",
                }
            ],
        )

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.delete(f"/api/v1/cases/{case_id}/team/members/{target_uid}")
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True

        # Member status now "removed" (soft delete)
        case = await db.cases.find_one({"id": case_id})
        assert case["case_team"][0]["status"] == "removed"

    async def test_remove_non_member_returns_404(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.delete(f"/api/v1/cases/{case_id}/team/members/ghost-user")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# PUT /{case_id}/team/members/{user_id}
# ---------------------------------------------------------------------------


class TestUpdateTeamMember:
    async def test_admin_can_update_member_role(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        target_uid = await _seed_user(db, role="analyst")
        case_id = await _seed_case(
            db,
            case_team=[
                {
                    "user_id": target_uid,
                    "role": "analyst",
                    "status": "active",
                }
            ],
        )

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.put(
            f"/api/v1/cases/{case_id}/team/members/{target_uid}",
            json={"role": "manager", "notes": "promoted"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True

        case = await db.cases.find_one({"id": case_id})
        assert case["case_team"][0]["role"] == "manager"
        assert case["case_team"][0]["notes"] == "promoted"

    async def test_update_with_no_fields_returns_400(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Pin the 'No fields to update' guard."""
        target_uid = await _seed_user(db, role="analyst")
        case_id = await _seed_case(
            db,
            case_team=[
                {
                    "user_id": target_uid,
                    "role": "analyst",
                    "status": "active",
                }
            ],
        )

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.put(f"/api/v1/cases/{case_id}/team/members/{target_uid}", json={})
        assert r.status_code == 400
        assert "No fields to update" in r.json()["error"]["message"]

    async def test_update_non_member_returns_404(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.put(
            f"/api/v1/cases/{case_id}/team/members/ghost-user",
            json={"role": "analyst"},
        )
        assert r.status_code == 404
