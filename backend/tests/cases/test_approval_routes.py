"""Integration tests for `src.cases.approval_routes` endpoints.

Phase 2.2.C (4/5). Target >=80% line coverage on src.cases.approval_routes.

Endpoints under test (all mounted at /api/v1/cases/...):
    POST /{case_id}/approve            (case-team role gate)
    POST /{case_id}/reject-approval    (case-team role gate)
    GET  /{case_id}/approval-status    (team-member or admin/analyst)

**Auth model nuance:** approval_routes uses the *case-team role* from
`get_user_role_on_case` (7-tier: manager/analyst/legal/sme/reviewer/
approver/third_party) — NOT the system user role from the JWT. The
status filter is exact-match against the literal "active" string per
the helper's implementation. So tests seed the case_team array
explicitly with `user_id`/`role`/`status="active"` entries.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorDatabase

from tests.factories import make_case

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_routes_db(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase, app):
    import src.database as db_mod
    import src.dependencies as deps_mod
    from src.cases import approval_routes
    from src.cases import routes as cases_routes

    async def _override_get_db():
        return db

    app.dependency_overrides[approval_routes.get_db] = _override_get_db
    app.dependency_overrides[cases_routes.get_db] = _override_get_db
    monkeypatch.setattr(deps_mod, "users", db.users)
    monkeypatch.setattr(db_mod, "users", db.users)

    yield db

    app.dependency_overrides.pop(approval_routes.get_db, None)
    app.dependency_overrides.pop(cases_routes.get_db, None)


async def _seed_case_with_team_member(
    db: AsyncIOMotorDatabase, user_id: str, case_team_role: str
) -> str:
    """Seed a case with `user_id` on the case_team as `case_team_role`
    (active)."""
    doc = make_case(
        case_team=[
            {
                "user_id": user_id,
                "role": case_team_role,
                "status": "active",
                "added_at": datetime.utcnow().isoformat(),
            }
        ]
    )
    await db.cases.insert_one(doc)
    return doc["id"]


# ---------------------------------------------------------------------------
# POST /{case_id}/approve
# ---------------------------------------------------------------------------


class TestApproveCase:
    async def test_approver_team_member_can_approve(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="user", email="appr@example.com")
        me = await db.users.find_one({"email": "appr@example.com"})
        case_id = await _seed_case_with_team_member(db, me["id"], "approver")

        r = await client.post(
            f"/api/v1/cases/{case_id}/approve",
            json={"notes": "All good"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["approval_status"] == "approved"

        # Verify persisted
        case = await db.cases.find_one({"id": case_id})
        assert case["approval_status"] == "approved"
        assert case["approval_notes"] == "All good"
        assert any(e.get("action") == "case_approved" for e in case.get("audit_log", []))

    async def test_non_team_member_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """A user not on the case team gets 403 — even if their system
        role is admin (the route only checks case-team role)."""
        client: AsyncClient = await authed_client_factory(
            role="admin", email="outsider@example.com"
        )
        # Seed a case with a DIFFERENT user on the team
        case_id = await _seed_case_with_team_member(db, "some-other-user", "approver")

        r = await client.post(f"/api/v1/cases/{case_id}/approve", json={})
        assert r.status_code == 403

    async def test_reviewer_team_member_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """A reviewer is on the team but NOT in
        [approver, manager, analyst] -> 403."""
        client: AsyncClient = await authed_client_factory(role="user", email="rev@example.com")
        me = await db.users.find_one({"email": "rev@example.com"})
        case_id = await _seed_case_with_team_member(db, me["id"], "reviewer")

        r = await client.post(f"/api/v1/cases/{case_id}/approve", json={})
        assert r.status_code == 403

    async def test_approve_missing_case_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post("/api/v1/cases/ghost-case/approve", json={})
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /{case_id}/reject-approval
# ---------------------------------------------------------------------------


class TestRejectApproval:
    async def test_manager_can_reject(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="user", email="mgr@example.com")
        me = await db.users.find_one({"email": "mgr@example.com"})
        case_id = await _seed_case_with_team_member(db, me["id"], "manager")

        r = await client.post(
            f"/api/v1/cases/{case_id}/reject-approval",
            json={"reason": "Bad redactions"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["approval_status"] == "rejected"

        case = await db.cases.find_one({"id": case_id})
        assert case["approval_status"] == "rejected"
        assert case["approval_notes"] == "Bad redactions"

    async def test_reject_requires_reason_field(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """`reason` is a required field on RejectApprovalRequest.

        Phase 4 Batch 4.4 (audit B7) fixed the deprecated
        `HTTP_422_UNPROCESSABLE_ENTITY` constant in
        `src/utils/error_handler.py`; the per-test filterwarnings
        suppressor is no longer required."""
        client: AsyncClient = await authed_client_factory(role="user", email="mgr2@example.com")
        me = await db.users.find_one({"email": "mgr2@example.com"})
        case_id = await _seed_case_with_team_member(db, me["id"], "manager")

        r = await client.post(f"/api/v1/cases/{case_id}/reject-approval", json={})
        assert r.status_code == 422

    async def test_reject_non_team_member_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="user", email="rnotteam@example.com")
        case_id = await _seed_case_with_team_member(db, "other-user", "approver")

        r = await client.post(
            f"/api/v1/cases/{case_id}/reject-approval",
            json={"reason": "x"},
        )
        assert r.status_code == 403

    async def test_reject_missing_case_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/cases/ghost/reject-approval",
            json={"reason": "x"},
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /{case_id}/approval-status
# ---------------------------------------------------------------------------


class TestApprovalStatus:
    async def test_admin_can_view_status_without_team_membership(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Pin: admin/analyst/owner can view approval status even if
        they're NOT on the case team."""
        client: AsyncClient = await authed_client_factory(role="admin")
        # Seed a case where the admin is NOT on the team
        case_id = await _seed_case_with_team_member(db, "other-user", "approver")
        await db.cases.update_one(
            {"id": case_id},
            {"$set": {"approval_status": "approved", "approved_by": "u1"}},
        )

        r = await client.get(f"/api/v1/cases/{case_id}/approval-status")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["case_id"] == case_id
        assert body["approval_status"] == "approved"

    async def test_team_member_can_view_status(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="user", email="legal@example.com")
        me = await db.users.find_one({"email": "legal@example.com"})
        case_id = await _seed_case_with_team_member(db, me["id"], "legal")

        r = await client.get(f"/api/v1/cases/{case_id}/approval-status")
        assert r.status_code == 200, r.text
        assert r.json()["case_id"] == case_id

    async def test_non_admin_non_team_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="user", email="nope@example.com")
        case_id = await _seed_case_with_team_member(db, "other-user", "approver")

        r = await client.get(f"/api/v1/cases/{case_id}/approval-status")
        assert r.status_code == 403

    async def test_approval_status_missing_case_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/cases/no-such-case/approval-status")
        assert r.status_code == 404
