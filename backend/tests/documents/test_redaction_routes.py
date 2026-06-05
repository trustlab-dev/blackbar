"""Integration tests for `src.documents.redaction_routes` endpoints.

Phase 2.3.B (1/2). Target **100% line + branch coverage** on
`src.documents.redaction_routes` — the manual redaction workflow.
Redactions in released output are the highest data-leak risk surface
(audit Section 5c critical path).

Endpoints under test (all mounted at `/api/v1/documents/...` because
`redaction_router` is `include_router`'d under `documents/routes.py`
which is mounted at `/api/v1/documents`):

    POST   /{document_id}/redactions/propose
    GET    /{document_id}/redactions/proposed
    PUT    /{document_id}/redactions/{redaction_index}/approve
    GET    /{document_id}/redactions
    POST   /{document_id}/redactions
    PUT    /{document_id}/redactions/{redaction_id}        (status query param)
    PUT    /{document_id}/redactions/{redaction_id}/edit
    DELETE /{document_id}/redactions/{redaction_id}

**Auth model nuance:** the propose/approve workflow uses *case-team
role* (7-tier `manager/analyst/legal/...`) via `get_user_role_on_case`
+ `can_propose_redactions`/`can_approve_proposed_redactions`. The CRUD
endpoints use *user role* (4-tier `owner/admin/analyst/user/guest`)
via `check_role` plus an inner case-team-membership check for
non-admin/non-owner users.

**Route registration order is significant** (mirrors B12 lesson from
`cases/queue_routes`): the `/{document_id}/redactions/{redaction_index}/approve`
URL has a numeric index, while the parallel
`/{document_id}/redactions/{redaction_id}` (status-update PUT) takes a
string id. Source registers /approve first which makes it win when the
index is numeric. We test both.

Findings pinned (candidates for audit Section 11):
- The `add_redaction` endpoint (POST /{document_id}/redactions) accepts
  a *raw `dict`* request body with no Pydantic validation. Any shape
  goes in (including empty `{}`). Pinned.
- The `update_redaction_status` endpoint (PUT
  /{document_id}/redactions/{redaction_id}) uses `redactions._id`
  in its mongo filter — but the source's `add_redaction` writes the
  field as `id`, not `_id`. So `update_redaction_status` is functionally
  unreachable for redactions added through the normal flow: it always
  returns 404. Tests pin reality by seeding a redaction with `_id` set.
- The `get_redactions` endpoint auto-assigns UUIDs to redactions
  missing an `id` and writes them back on every read. This persistence
  side-effect on a GET request is unusual but documented.
- Concurrency: two propose requests against the same document race
  on `$push`; mongo's atomic $push means both succeed and the
  redactions array grows by 2. No explicit conflict resolution.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any

import pytest
from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorDatabase

from tests.factories import make_case, make_document

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_routes_db(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase, app):
    """Rebind the redaction routes' `get_db` and the dependencies module's
    captured `users` to the per-test motor database.

    The redaction_routes module defines its own `get_db` helper; the parent
    `documents/routes.py` module also defines one. Override both. Also patch
    `src.dependencies.users` so `get_current_user`'s user lookup uses the
    test db.
    """
    import src.database as db_mod
    import src.dependencies as deps_mod
    from src.documents import redaction_routes
    from src.documents import routes as documents_routes

    async def _override_get_db():
        return db

    app.dependency_overrides[redaction_routes.get_db] = _override_get_db
    app.dependency_overrides[documents_routes.get_db] = _override_get_db
    monkeypatch.setattr(deps_mod, "users", db.users)
    monkeypatch.setattr(db_mod, "users", db.users)

    yield db

    app.dependency_overrides.pop(redaction_routes.get_db, None)
    app.dependency_overrides.pop(documents_routes.get_db, None)


async def _seed_case_with_team_member(
    db: AsyncIOMotorDatabase,
    user_id: str,
    case_team_role: str = "analyst",
    **case_overrides: Any,
) -> str:
    """Seed a case row with `user_id` active on the case_team as
    `case_team_role`. Returns case id."""
    case = make_case(
        case_team=[
            {
                "user_id": user_id,
                "role": case_team_role,
                "status": "active",
                "added_at": datetime.utcnow().isoformat(),
            }
        ],
        **case_overrides,
    )
    await db.cases.insert_one(case)
    return case["id"]


async def _seed_document(db: AsyncIOMotorDatabase, case_id: str, **doc_overrides: Any) -> str:
    """Seed a document row referencing `case_id`. Returns document id."""
    doc = make_document(case_id=case_id, **doc_overrides)
    await db.documents.insert_one(doc)
    return doc["id"]


# ---------------------------------------------------------------------------
# POST /{document_id}/redactions/propose
# ---------------------------------------------------------------------------


class TestProposeRedaction:
    async def test_analyst_team_member_can_propose(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="user", email="prop1@example.com")
        me = await db.users.find_one({"email": "prop1@example.com"})
        case_id = await _seed_case_with_team_member(db, me["id"], case_team_role="analyst")
        doc_id = await _seed_document(db, case_id)

        r = await client.post(
            f"/api/v1/documents/{doc_id}/redactions/propose",
            json={
                "x": 10.5,
                "y": 20.5,
                "width": 100.0,
                "height": 30.0,
                "page": 1,
                "category": "S22",
                "reason": "Personal info",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["redaction"]["type"] == "proposed"
        assert body["redaction"]["proposed_by"] == me["id"]
        assert body["redaction"]["proposed_reason"] == "Personal info"

        # Verify persisted redaction + audit log
        doc = await db.documents.find_one({"id": doc_id})
        assert len(doc["redactions"]) == 1
        case = await db.cases.find_one({"id": case_id})
        assert any(e.get("action") == "redaction_proposed" for e in case.get("audit_log", []))

    async def test_propose_document_not_found(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/documents/ghost/redactions/propose",
            json={
                "x": 0,
                "y": 0,
                "width": 1,
                "height": 1,
                "page": 1,
                "category": "S22",
                "reason": "x",
            },
        )
        assert r.status_code == 404
        assert "Document not found" in r.text

    async def test_propose_case_not_found(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Doc exists but its case_id doesn't resolve."""
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_document(db, case_id="ghost-case")
        r = await client.post(
            f"/api/v1/documents/{doc_id}/redactions/propose",
            json={
                "x": 0,
                "y": 0,
                "width": 1,
                "height": 1,
                "page": 1,
                "category": "S22",
                "reason": "x",
            },
        )
        assert r.status_code == 404
        assert "Case not found" in r.text

    async def test_propose_non_team_member_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """User is NOT on the case team -> get_user_role_on_case returns
        None -> 403."""
        client = await authed_client_factory(role="user", email="ghost@example.com")
        case_id = await _seed_case_with_team_member(
            db, user_id="someone-else", case_team_role="analyst"
        )
        doc_id = await _seed_document(db, case_id)
        r = await client.post(
            f"/api/v1/documents/{doc_id}/redactions/propose",
            json={
                "x": 0,
                "y": 0,
                "width": 1,
                "height": 1,
                "page": 1,
                "category": "S22",
                "reason": "x",
            },
        )
        assert r.status_code == 403
        assert "propose redactions" in r.text

    async def test_propose_sme_role_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """SME case-team role can't propose redactions (only view/comment/
        upload). Pins `can_propose_redactions` False branch."""
        client = await authed_client_factory(role="user", email="sme@example.com")
        me = await db.users.find_one({"email": "sme@example.com"})
        case_id = await _seed_case_with_team_member(db, me["id"], case_team_role="sme")
        doc_id = await _seed_document(db, case_id)
        r = await client.post(
            f"/api/v1/documents/{doc_id}/redactions/propose",
            json={
                "x": 0,
                "y": 0,
                "width": 1,
                "height": 1,
                "page": 1,
                "category": "S22",
                "reason": "x",
            },
        )
        assert r.status_code == 403

    async def test_propose_validation_error_missing_field(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Pydantic rejects body missing required field.

        Phase 4 Batch 4.4 (audit B7) fixed the deprecated
        `HTTP_422_UNPROCESSABLE_ENTITY` constant in
        `src/utils/error_handler.py`; the per-test filterwarnings
        suppressor is no longer required."""
        client = await authed_client_factory(role="admin")
        me = await db.users.find_one({"role": "admin"})
        case_id = await _seed_case_with_team_member(db, me["id"], case_team_role="analyst")
        doc_id = await _seed_document(db, case_id)
        r = await client.post(
            f"/api/v1/documents/{doc_id}/redactions/propose",
            json={"x": 0, "y": 0, "width": 1, "height": 1, "page": 1},
        )
        # 422 from Pydantic
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# GET /{document_id}/redactions/proposed
# ---------------------------------------------------------------------------


class TestGetProposedRedactions:
    async def test_team_member_sees_proposed_only(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="user", email="g1@example.com")
        me = await db.users.find_one({"email": "g1@example.com"})
        case_id = await _seed_case_with_team_member(db, me["id"], "analyst")
        # Mix proposed + professional in one document
        doc_id = await _seed_document(
            db,
            case_id,
            redactions=[
                {"type": "proposed", "page": 1, "id": "r1"},
                {"type": "professional", "page": 2, "id": "r2"},
                {"type": "proposed", "page": 3, "id": "r3"},
            ],
        )
        r = await client.get(f"/api/v1/documents/{doc_id}/redactions/proposed")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] == 2
        assert all(red["type"] == "proposed" for red in body["proposed_redactions"])

    async def test_get_proposed_document_not_found(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/documents/ghost/redactions/proposed")
        assert r.status_code == 404

    async def test_get_proposed_case_not_found(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_document(db, case_id="ghost")
        r = await client.get(f"/api/v1/documents/{doc_id}/redactions/proposed")
        assert r.status_code == 404
        assert "Case not found" in r.text

    async def test_get_proposed_non_team_member_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="user", email="off@example.com")
        case_id = await _seed_case_with_team_member(db, "someone", "analyst")
        doc_id = await _seed_document(db, case_id)
        r = await client.get(f"/api/v1/documents/{doc_id}/redactions/proposed")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# PUT /{document_id}/redactions/{redaction_index}/approve
# ---------------------------------------------------------------------------


class TestApproveOrRejectProposed:
    async def _setup_doc_with_proposed(
        self,
        db: AsyncIOMotorDatabase,
        case_team_role: str = "analyst",
        email: str = "appr@example.com",
        authed_client_factory=None,
    ) -> tuple[AsyncClient, str, str]:
        client = await authed_client_factory(role="user", email=email)
        me = await db.users.find_one({"email": email})
        case_id = await _seed_case_with_team_member(db, me["id"], case_team_role)
        doc_id = await _seed_document(
            db,
            case_id,
            redactions=[
                {
                    "type": "proposed",
                    "status": "proposed",
                    "page": 1,
                    "x": 1,
                    "y": 2,
                    "width": 10,
                    "height": 5,
                    "id": str(uuid.uuid4()),
                }
            ],
        )
        return client, case_id, doc_id

    async def test_analyst_can_approve_proposed(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client, case_id, doc_id = await self._setup_doc_with_proposed(
            db, "analyst", "ap1@example.com", authed_client_factory
        )
        r = await client.put(
            f"/api/v1/documents/{doc_id}/redactions/0/approve",
            json={"action": "approve", "notes": "Looks good"},
        )
        assert r.status_code == 200, r.text
        assert "approved" in r.json()["message"]
        # Pin state-machine transition
        doc = await db.documents.find_one({"id": doc_id})
        assert doc["redactions"][0]["type"] == "professional"
        assert doc["redactions"][0]["status"] == "approved"
        assert doc["redactions"][0]["approval_status"] == "approved"
        case = await db.cases.find_one({"id": case_id})
        assert any(e.get("action") == "redaction_proposal_approved" for e in case["audit_log"])

    async def test_analyst_can_reject_proposed(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client, case_id, doc_id = await self._setup_doc_with_proposed(
            db, "analyst", "rj1@example.com", authed_client_factory
        )
        r = await client.put(
            f"/api/v1/documents/{doc_id}/redactions/0/approve",
            json={"action": "reject", "notes": "Not needed"},
        )
        assert r.status_code == 200
        assert "rejected" in r.json()["message"]
        doc = await db.documents.find_one({"id": doc_id})
        # Reject keeps type=proposed but flips status
        assert doc["redactions"][0]["status"] == "rejected"
        assert doc["redactions"][0]["approval_status"] == "rejected"
        case = await db.cases.find_one({"id": case_id})
        # Phase 4 Batch 4.4 (audit B26): the typo
        # "redaction_proposal_rejectd" is fixed. The audit log entry now
        # uses the correctly-spelled "redaction_proposal_rejected".
        assert any(e.get("action") == "redaction_proposal_rejected" for e in case["audit_log"])

    async def test_approve_invalid_action(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client, _, doc_id = await self._setup_doc_with_proposed(
            db, "analyst", "iv@example.com", authed_client_factory
        )
        r = await client.put(
            f"/api/v1/documents/{doc_id}/redactions/0/approve",
            json={"action": "maybe"},
        )
        assert r.status_code == 400
        assert "approve" in r.text and "reject" in r.text

    async def test_approve_document_not_found(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.put(
            "/api/v1/documents/ghost/redactions/0/approve",
            json={"action": "approve"},
        )
        assert r.status_code == 404
        assert "Document not found" in r.text

    async def test_approve_case_not_found(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_document(
            db,
            case_id="ghost",
            redactions=[{"type": "proposed", "status": "proposed", "page": 1, "id": "x"}],
        )
        r = await client.put(
            f"/api/v1/documents/{doc_id}/redactions/0/approve",
            json={"action": "approve"},
        )
        assert r.status_code == 404
        assert "Case not found" in r.text

    async def test_approve_non_approver_role_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Legal case-team role can propose but NOT approve. Pins
        `can_approve_proposed_redactions` False branch."""
        client, _, doc_id = await self._setup_doc_with_proposed(
            db, "legal", "lg@example.com", authed_client_factory
        )
        r = await client.put(
            f"/api/v1/documents/{doc_id}/redactions/0/approve",
            json={"action": "approve"},
        )
        assert r.status_code == 403
        assert "approve/reject" in r.text

    async def test_approve_non_team_member_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """User not on case_team -> get_user_role_on_case returns None ->
        403 (first half of the `or` short-circuit)."""
        client = await authed_client_factory(role="user", email="x@example.com")
        case_id = await _seed_case_with_team_member(db, "other", "analyst")
        doc_id = await _seed_document(
            db,
            case_id,
            redactions=[{"type": "proposed", "status": "proposed", "page": 1, "id": "x"}],
        )
        r = await client.put(
            f"/api/v1/documents/{doc_id}/redactions/0/approve",
            json={"action": "approve"},
        )
        assert r.status_code == 403

    async def test_approve_index_out_of_range(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client, _, doc_id = await self._setup_doc_with_proposed(
            db, "analyst", "or@example.com", authed_client_factory
        )
        r = await client.put(
            f"/api/v1/documents/{doc_id}/redactions/99/approve",
            json={"action": "approve"},
        )
        assert r.status_code == 404
        assert "Redaction not found" in r.text

    async def test_approve_target_is_not_proposed(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """The redaction at index 0 is `type=professional`, not proposed."""
        client = await authed_client_factory(role="user", email="np@example.com")
        me = await db.users.find_one({"email": "np@example.com"})
        case_id = await _seed_case_with_team_member(db, me["id"], "analyst")
        doc_id = await _seed_document(
            db,
            case_id,
            redactions=[{"type": "professional", "page": 1, "id": "x", "status": "approved"}],
        )
        r = await client.put(
            f"/api/v1/documents/{doc_id}/redactions/0/approve",
            json={"action": "approve"},
        )
        assert r.status_code == 400
        assert "not a proposed redaction" in r.text


# ---------------------------------------------------------------------------
# GET /{document_id}/redactions
# ---------------------------------------------------------------------------


class TestGetRedactions:
    async def test_admin_get_redactions_assigns_uuids(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Reading redactions without `id` triggers UUID backfill that
        persists to mongo."""
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case_with_team_member(db, "x", "analyst")
        doc_id = await _seed_document(
            db,
            case_id,
            redactions=[
                {"type": "professional", "page": 1, "x": 1, "y": 2, "width": 3, "height": 4},
                {
                    "type": "professional",
                    "page": 2,
                    "x": 5,
                    "y": 6,
                    "width": 7,
                    "height": 8,
                    "id": "preexisting",
                },
            ],
        )
        r = await client.get(f"/api/v1/documents/{doc_id}/redactions")
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body) == 2
        # First gained a UUID
        assert "id" in body[0]
        assert body[1]["id"] == "preexisting"
        # Verify persistence happened
        doc = await db.documents.find_one({"id": doc_id})
        assert all("id" in r for r in doc["redactions"])

    async def test_get_redactions_document_not_found(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/documents/ghost/redactions")
        assert r.status_code == 404

    async def test_get_redactions_role_decorator_forbids_unknown_role(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """The endpoint's `check_role` allowlist excludes any role outside
        owner/admin/analyst/user/guest. We synthesize one by directly
        patching the JWT user's role to a value `check_role` rejects."""
        client = await authed_client_factory(role="user", email="role@example.com")
        # Mutate the user's role to an unrecognized value, then issue a new token
        await db.users.update_one(
            {"email": "role@example.com"},
            {"$set": {"role": "weird"}},
        )
        # The existing client's JWT still carries role="user"; create-and-mutate
        # path puts "weird" in the DB but the JWT/payload-derived role is "user"
        # which IS in the allowlist. So the role-decorator check passes. To
        # actually exercise the decorator's 403, mint a fresh token with the
        # weird role baked in:
        # We do this by manipulating dependencies.get_current_user to return
        # weird via a JWT that carries that role.
        from src.auth.auth_service import AuthService
        from src.users.models import User as UserModel
        from src.users.repository import UsersRepository

        repo = UsersRepository(db)
        user_doc = await db.users.find_one({"email": "role@example.com"})
        user_obj = UserModel(**user_doc)
        auth_svc = AuthService(repo)
        token = await auth_svc.issue_token(user_obj)
        case_id = await _seed_case_with_team_member(db, user_doc["id"], "analyst")
        doc_id = await _seed_document(db, case_id)
        from httpx import ASGITransport, AsyncClient

        from src.main import app as fastapi_app

        weird_client = AsyncClient(
            transport=ASGITransport(app=fastapi_app),
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            r = await weird_client.get(f"/api/v1/documents/{doc_id}/redactions")
        finally:
            await weird_client.aclose()
        assert r.status_code == 403

    async def test_get_redactions_guest_with_share_can_access(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Guest user listed in `shared_with` passes `check_document_access`."""
        client = await authed_client_factory(role="guest", email="gst@example.com")
        me = await db.users.find_one({"email": "gst@example.com"})
        case_id = await _seed_case_with_team_member(db, "other", "analyst")
        doc_id = await _seed_document(
            db,
            case_id,
            shared_with=[{"user_id": me["id"]}],
            redactions=[{"type": "professional", "page": 1, "id": "r1"}],
        )
        r = await client.get(f"/api/v1/documents/{doc_id}/redactions")
        assert r.status_code == 200

    async def test_get_redactions_guest_without_share_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Guest user not in `shared_with` is denied access."""
        client = await authed_client_factory(role="guest", email="gst2@example.com")
        case_id = await _seed_case_with_team_member(db, "other", "analyst")
        doc_id = await _seed_document(db, case_id, shared_with=[])
        r = await client.get(f"/api/v1/documents/{doc_id}/redactions")
        assert r.status_code == 403

    async def test_get_redactions_user_on_team_can_access(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Plain user on case team passes the membership branch."""
        client = await authed_client_factory(role="user", email="on@example.com")
        me = await db.users.find_one({"email": "on@example.com"})
        case_id = await _seed_case_with_team_member(db, me["id"], "analyst")
        doc_id = await _seed_document(db, case_id)
        r = await client.get(f"/api/v1/documents/{doc_id}/redactions")
        assert r.status_code == 200

    async def test_get_redactions_user_off_team_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Plain user NOT on case team -> `check_document_access` False."""
        client = await authed_client_factory(role="user", email="off2@example.com")
        case_id = await _seed_case_with_team_member(db, "x", "analyst")
        doc_id = await _seed_document(db, case_id)
        r = await client.get(f"/api/v1/documents/{doc_id}/redactions")
        assert r.status_code == 403

    async def test_get_redactions_no_case_present(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Document with case_id pointing to nothing. For a user (not
        owner/admin/guest), `check_document_access` returns False because
        the `case` arg is None and the "Others" branch falls through."""
        client = await authed_client_factory(role="user", email="nc@example.com")
        doc_id = await _seed_document(db, case_id="ghost-case")
        r = await client.get(f"/api/v1/documents/{doc_id}/redactions")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# POST /{document_id}/redactions  (add_redaction)
# ---------------------------------------------------------------------------


class TestAddRedaction:
    async def test_admin_can_add_redaction(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case_with_team_member(db, "x", "analyst")
        doc_id = await _seed_document(db, case_id)
        r = await client.post(
            f"/api/v1/documents/{doc_id}/redactions",
            json={
                "x": 10,
                "y": 20,
                "width": 30,
                "height": 40,
                "page": 1,
                "category": "S22",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "id" in body
        # Persisted
        doc = await db.documents.find_one({"id": doc_id})
        assert len(doc["redactions"]) == 1
        red = doc["redactions"][0]
        assert red["created_by_role"] == "admin"
        assert red["status"] == "pending"
        # Case audit log gained an entry
        case = await db.cases.find_one({"id": case_id})
        assert any(e.get("action") == "redaction_created" for e in case["audit_log"])

    async def test_add_redaction_preserves_provided_id(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """If the body includes `id`, the endpoint keeps it (pin: no
        UUID regeneration when present)."""
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case_with_team_member(db, "x", "analyst")
        doc_id = await _seed_document(db, case_id)
        my_id = "my-custom-id-123"
        r = await client.post(
            f"/api/v1/documents/{doc_id}/redactions",
            json={"id": my_id, "page": 1, "x": 1, "y": 1, "width": 1, "height": 1},
        )
        assert r.status_code == 200
        assert r.json()["id"] == my_id

    async def test_add_redaction_user_on_team_can_add(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="user", email="add@example.com")
        me = await db.users.find_one({"email": "add@example.com"})
        case_id = await _seed_case_with_team_member(db, me["id"], "analyst")
        doc_id = await _seed_document(db, case_id)
        r = await client.post(
            f"/api/v1/documents/{doc_id}/redactions",
            json={"page": 1, "x": 1, "y": 1, "width": 1, "height": 1},
        )
        assert r.status_code == 200

    async def test_add_redaction_user_off_team_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="user", email="off3@example.com")
        case_id = await _seed_case_with_team_member(db, "other", "analyst")
        doc_id = await _seed_document(db, case_id)
        r = await client.post(
            f"/api/v1/documents/{doc_id}/redactions",
            json={"page": 1, "x": 1, "y": 1, "width": 1, "height": 1},
        )
        assert r.status_code == 403

    async def test_add_redaction_guest_role_forbidden_by_decorator(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """`check_role(["owner","admin","analyst","user"])` excludes guest."""
        client = await authed_client_factory(role="guest")
        case_id = await _seed_case_with_team_member(db, "x", "analyst")
        doc_id = await _seed_document(db, case_id)
        r = await client.post(
            f"/api/v1/documents/{doc_id}/redactions",
            json={"page": 1, "x": 1, "y": 1, "width": 1, "height": 1},
        )
        assert r.status_code == 403

    async def test_add_redaction_document_not_found(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/documents/ghost/redactions",
            json={"page": 1, "x": 1, "y": 1, "width": 1, "height": 1},
        )
        assert r.status_code == 404
        assert "Document not found" in r.text

    async def test_add_redaction_no_case_skips_audit(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Doc.case_id resolves to nothing — admin bypass means no team
        check, and the `if case` audit branch is skipped."""
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_document(db, case_id="ghost-case")
        r = await client.post(
            f"/api/v1/documents/{doc_id}/redactions",
            json={"page": 1, "x": 1, "y": 1, "width": 1, "height": 1},
        )
        assert r.status_code == 200
        body = r.json()
        assert "id" in body

    async def test_add_redaction_then_doc_disappears_returns_404(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        app,
        patch_routes_db,
    ) -> None:
        """The `result.modified_count == 0` branch fires when the $push
        update affects no documents. Hard to hit naturally — race
        condition. We override get_db with a wrapper that returns a db
        whose `documents.update_one` always reports modified_count=0
        while passing the initial `find_one` through to the real db."""
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case_with_team_member(db, "x", "analyst")
        doc_id = await _seed_document(db, case_id)

        class _Result:
            modified_count = 0

        class _FakeDocuments:
            def __init__(self, real):
                self._real = real

            async def find_one(self, *a, **kw):
                return await self._real.find_one(*a, **kw)

            async def update_one(self, *a, **kw):
                return _Result()

        class _FakeDb:
            def __init__(self, real):
                self.documents = _FakeDocuments(real.documents)
                self.cases = real.cases
                self.users = real.users

        from src.documents import redaction_routes

        async def _override_get_db():
            return _FakeDb(db)

        app.dependency_overrides[redaction_routes.get_db] = _override_get_db
        try:
            r = await client.post(
                f"/api/v1/documents/{doc_id}/redactions",
                json={"page": 1, "x": 1, "y": 1, "width": 1, "height": 1},
            )
        finally:
            app.dependency_overrides.pop(redaction_routes.get_db, None)
        assert r.status_code == 404
        assert "Document not found" in r.text


# ---------------------------------------------------------------------------
# PUT /{document_id}/redactions/{redaction_id}  (status update via query param)
# ---------------------------------------------------------------------------


class TestUpdateRedactionStatus:
    async def test_update_status_to_accepted(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Phase 4 Batch 4.4 (audit B27): the handler now filters by
        `redactions.id` (matching what `add_redaction` writes); seed
        accordingly."""
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case_with_team_member(db, "x", "analyst")
        rid = "red-123"
        doc_id = await _seed_document(
            db,
            case_id,
            redactions=[{"id": rid, "page": 1, "status": "pending"}],
        )
        r = await client.put(
            f"/api/v1/documents/{doc_id}/redactions/{rid}?status=accepted",
        )
        assert r.status_code == 200, r.text
        assert "accepted" in r.json()["message"]
        doc = await db.documents.find_one({"id": doc_id})
        # Status persisted
        assert doc["redactions"][0]["status"] == "accepted"

    async def test_update_status_to_rejected(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case_with_team_member(db, "x", "analyst")
        rid = "red-456"
        doc_id = await _seed_document(
            db,
            case_id,
            redactions=[{"id": rid, "page": 1, "status": "pending"}],
        )
        r = await client.put(f"/api/v1/documents/{doc_id}/redactions/{rid}?status=rejected")
        assert r.status_code == 200
        doc = await db.documents.find_one({"id": doc_id})
        assert doc["redactions"][0]["status"] == "rejected"

    async def test_update_status_invalid_value(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case_with_team_member(db, "x", "analyst")
        doc_id = await _seed_document(db, case_id)
        r = await client.put(f"/api/v1/documents/{doc_id}/redactions/anything?status=maybe")
        assert r.status_code == 400
        assert "Invalid status" in r.text

    async def test_update_status_non_admin_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """check_role(['owner','admin']) — analyst rejected here."""
        client = await authed_client_factory(role="analyst")
        case_id = await _seed_case_with_team_member(db, "x", "analyst")
        doc_id = await _seed_document(db, case_id)
        r = await client.put(f"/api/v1/documents/{doc_id}/redactions/anything?status=accepted")
        assert r.status_code == 403

    async def test_update_status_redaction_not_found(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Filter doesn't match -> modified_count==0 -> 404."""
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case_with_team_member(db, "x", "analyst")
        doc_id = await _seed_document(db, case_id, redactions=[])
        r = await client.put(f"/api/v1/documents/{doc_id}/redactions/ghost?status=accepted")
        assert r.status_code == 404
        assert "not found" in r.text

    async def test_add_then_update_status_end_to_end(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Phase 4 Batch 4.4 (audit B27): regression test asserting the
        full add_redaction -> update_redaction_status flow works through
        the public URL. Previously the update filter looked for
        `redactions._id` while `add_redaction` wrote `redactions.id`,
        so this round-trip always returned 404."""
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case_with_team_member(db, "x", "analyst")
        doc_id = await _seed_document(db, case_id, redactions=[])

        # 1. POST a new redaction via the standard handler
        post_r = await client.post(
            f"/api/v1/documents/{doc_id}/redactions",
            json={"page": 1, "category": "personal"},
        )
        assert post_r.status_code == 200, post_r.text
        new_id = post_r.json()["id"]

        # 2. PUT to update its status — must find the redaction via id
        put_r = await client.put(f"/api/v1/documents/{doc_id}/redactions/{new_id}?status=accepted")
        assert put_r.status_code == 200, put_r.text

        doc = await db.documents.find_one({"id": doc_id})
        assert doc["redactions"][0]["id"] == new_id
        assert doc["redactions"][0]["status"] == "accepted"


# ---------------------------------------------------------------------------
# PUT /{document_id}/redactions/{redaction_id}/edit
# ---------------------------------------------------------------------------


class TestUpdateRedaction:
    async def test_edit_all_mutable_fields(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Pin every mutable-field branch (reason, notes, x, y, width,
        height) in one shot."""
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case_with_team_member(db, "x", "analyst")
        rid = "red-edit-1"
        doc_id = await _seed_document(
            db,
            case_id,
            redactions=[
                {
                    "id": rid,
                    "page": 2,
                    "x": 1.0,
                    "y": 2.0,
                    "width": 10.0,
                    "height": 20.0,
                    "category": "S22",
                    "reason": "old",
                    "notes": "n",
                }
            ],
        )
        r = await client.put(
            f"/api/v1/documents/{doc_id}/redactions/{rid}/edit",
            json={
                "reason": "updated reason",
                "notes": "updated notes",
                "x": "11.5",  # string -> float coerced by `float()`
                "y": 22.5,
                "width": 33,
                "height": 44.4,
            },
        )
        assert r.status_code == 200, r.text
        doc = await db.documents.find_one({"id": doc_id})
        red = doc["redactions"][0]
        assert red["reason"] == "updated reason"
        assert red["notes"] == "updated notes"
        assert red["x"] == 11.5
        assert red["y"] == 22.5
        assert red["width"] == 33.0
        assert red["height"] == 44.4
        case = await db.cases.find_one({"id": case_id})
        assert any(e.get("action") == "redaction_edited" for e in case["audit_log"])

    async def test_edit_partial_fields_only(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Only update `reason`; other fields preserved. Pins selective
        update branches."""
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case_with_team_member(db, "x", "analyst")
        rid = "red-edit-2"
        doc_id = await _seed_document(
            db,
            case_id,
            redactions=[
                {
                    "id": rid,
                    "page": 1,
                    "x": 1,
                    "y": 2,
                    "width": 3,
                    "height": 4,
                    "reason": "old",
                }
            ],
        )
        r = await client.put(
            f"/api/v1/documents/{doc_id}/redactions/{rid}/edit",
            json={"reason": "new"},
        )
        assert r.status_code == 200
        doc = await db.documents.find_one({"id": doc_id})
        red = doc["redactions"][0]
        assert red["reason"] == "new"
        assert red["x"] == 1
        assert red["y"] == 2

    async def test_edit_document_not_found(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.put("/api/v1/documents/ghost/redactions/x/edit", json={"reason": "z"})
        assert r.status_code == 404

    async def test_edit_redaction_not_found(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case_with_team_member(db, "x", "analyst")
        doc_id = await _seed_document(db, case_id, redactions=[])
        r = await client.put(
            f"/api/v1/documents/{doc_id}/redactions/ghost/edit",
            json={"reason": "x"},
        )
        assert r.status_code == 404
        assert "Redaction not found" in r.text

    async def test_edit_only_notes_skips_reason_branch(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Cover branch 357->359: `if 'reason' in updates` False (skip)
        while a later `if` is True. Updates body only contains `notes`."""
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case_with_team_member(db, "x", "analyst")
        rid = "red-notes-only"
        doc_id = await _seed_document(
            db,
            case_id,
            redactions=[{"id": rid, "page": 1, "reason": "keep me"}],
        )
        r = await client.put(
            f"/api/v1/documents/{doc_id}/redactions/{rid}/edit",
            json={"notes": "just notes"},
        )
        assert r.status_code == 200
        doc = await db.documents.find_one({"id": doc_id})
        red = doc["redactions"][0]
        assert red["notes"] == "just notes"
        assert red["reason"] == "keep me"

    async def test_edit_second_redaction_matches_first_does_not(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Cover branch 355->354 (loop iteration continues): first
        redaction doesn't match the target id, second does."""
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case_with_team_member(db, "x", "analyst")
        target_id = "second-one"
        doc_id = await _seed_document(
            db,
            case_id,
            redactions=[
                {"id": "first-one", "page": 1, "reason": "untouched"},
                {"id": target_id, "page": 2, "reason": "stale"},
            ],
        )
        r = await client.put(
            f"/api/v1/documents/{doc_id}/redactions/{target_id}/edit",
            json={"reason": "fresh"},
        )
        assert r.status_code == 200
        doc = await db.documents.find_one({"id": doc_id})
        assert doc["redactions"][0]["reason"] == "untouched"
        assert doc["redactions"][1]["reason"] == "fresh"

    async def test_edit_no_case_branch(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Doc without a case_id: audit log block is skipped (`if case`
        False branch)."""
        client = await authed_client_factory(role="admin")
        rid = "red-no-case"
        # Pass case_id=None
        doc = make_document(
            redactions=[
                {"id": rid, "page": 1, "x": 0, "y": 0, "width": 1, "height": 1, "reason": "old"}
            ]
        )
        doc["case_id"] = None
        await db.documents.insert_one(doc)
        r = await client.put(
            f"/api/v1/documents/{doc['id']}/redactions/{rid}/edit",
            json={"reason": "new"},
        )
        assert r.status_code == 200

    async def test_edit_guest_role_forbidden_by_decorator(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """`check_role` excludes guest."""
        client = await authed_client_factory(role="guest")
        case_id = await _seed_case_with_team_member(db, "x", "analyst")
        doc_id = await _seed_document(db, case_id)
        r = await client.put(
            f"/api/v1/documents/{doc_id}/redactions/x/edit",
            json={"reason": "z"},
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /{document_id}/redactions/{redaction_id}
# ---------------------------------------------------------------------------


class TestDeleteRedaction:
    async def test_admin_can_delete_redaction(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case_with_team_member(db, "x", "analyst")
        rid = "red-del-1"
        doc_id = await _seed_document(
            db,
            case_id,
            redactions=[
                {"id": rid, "page": 1, "category": "S22"},
                {"id": "keep", "page": 2, "category": "S22"},
            ],
        )
        r = await client.delete(f"/api/v1/documents/{doc_id}/redactions/{rid}")
        assert r.status_code == 200, r.text
        doc = await db.documents.find_one({"id": doc_id})
        assert [r["id"] for r in doc["redactions"]] == ["keep"]
        case = await db.cases.find_one({"id": case_id})
        assert any(e.get("action") == "redaction_deleted" for e in case["audit_log"])

    async def test_delete_user_on_team_can_delete(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="user", email="del@example.com")
        me = await db.users.find_one({"email": "del@example.com"})
        case_id = await _seed_case_with_team_member(db, me["id"], "analyst")
        rid = "r-x"
        doc_id = await _seed_document(db, case_id, redactions=[{"id": rid, "page": 1}])
        r = await client.delete(f"/api/v1/documents/{doc_id}/redactions/{rid}")
        assert r.status_code == 200

    async def test_delete_user_off_team_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="user", email="off4@example.com")
        case_id = await _seed_case_with_team_member(db, "other", "analyst")
        doc_id = await _seed_document(db, case_id, redactions=[{"id": "x", "page": 1}])
        r = await client.delete(f"/api/v1/documents/{doc_id}/redactions/x")
        assert r.status_code == 403

    async def test_delete_guest_role_forbidden_by_decorator(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="guest")
        case_id = await _seed_case_with_team_member(db, "x", "analyst")
        doc_id = await _seed_document(db, case_id)
        r = await client.delete(f"/api/v1/documents/{doc_id}/redactions/x")
        assert r.status_code == 403

    async def test_delete_document_not_found(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.delete("/api/v1/documents/ghost/redactions/x")
        assert r.status_code == 404

    async def test_delete_redaction_not_found(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case_with_team_member(db, "x", "analyst")
        doc_id = await _seed_document(db, case_id, redactions=[])
        r = await client.delete(f"/api/v1/documents/{doc_id}/redactions/ghost")
        assert r.status_code == 404
        assert "Redaction not found" in r.text

    async def test_delete_no_case_skips_audit(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Doc whose case_id is None -> audit log block is skipped."""
        client = await authed_client_factory(role="admin")
        rid = "r-no-case"
        doc = make_document(redactions=[{"id": rid, "page": 1}])
        doc["case_id"] = None
        await db.documents.insert_one(doc)
        r = await client.delete(f"/api/v1/documents/{doc['id']}/redactions/{rid}")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Direct unit tests (cover module-level helpers not reachable via deps-override)
# ---------------------------------------------------------------------------


async def test_get_db_helper_returns_shared_database(mongo_uri: str) -> None:
    """The module-level `get_db` helper is normally bypassed by
    `app.dependency_overrides` in route tests. Cover it directly so the
    line stays measured. It just delegates to
    `get_database_from_request` which returns the shared blackbar db."""
    from unittest.mock import MagicMock

    from src.documents.redaction_routes import get_db

    fake_request = MagicMock()
    result = await get_db(fake_request)
    # AsyncIOMotorDatabase instance, name "blackbar"
    assert result.name == "blackbar"


def test_check_document_access_owner_always_allowed() -> None:
    """Owner role bypasses all checks."""
    from src.documents.redaction_routes import check_document_access

    assert check_document_access({}, {"id": "u", "role": "owner"}) is True
    assert check_document_access({}, {"id": "u", "role": "admin"}) is True


def test_check_document_access_others_no_case_denies() -> None:
    """A user with no case context and no admin/guest role is denied
    via the fall-through `return False`."""
    from src.documents.redaction_routes import check_document_access

    assert check_document_access({}, {"id": "u", "role": "analyst"}, case=None) is False


# ---------------------------------------------------------------------------
# Coordinate roundtrip + multi-page + concurrency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "x,y,width,height,page",
    [
        (0.0, 0.0, 1.0, 1.0, 1),
        (123.45, 678.9, 50.5, 25.25, 7),
        (1000.0, 2000.0, 100.0, 50.0, 99),  # large coords
    ],
)
async def test_coordinate_roundtrip_fidelity(
    db: AsyncIOMotorDatabase,
    authed_client_factory,
    patch_routes_db,
    x: float,
    y: float,
    width: float,
    height: float,
    page: int,
) -> None:
    """Coordinate roundtrip: propose with PDF coords -> persist ->
    GET back via /redactions and verify exact float fidelity."""
    client = await authed_client_factory(role="user", email=f"coord-{page}@example.com")
    me = await db.users.find_one({"email": f"coord-{page}@example.com"})
    case_id = await _seed_case_with_team_member(db, me["id"], "analyst")
    doc_id = await _seed_document(db, case_id)
    r = await client.post(
        f"/api/v1/documents/{doc_id}/redactions/propose",
        json={
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "page": page,
            "category": "S22",
            "reason": "test",
        },
    )
    assert r.status_code == 200, r.text
    # Now GET back and inspect the persisted coords
    r2 = await client.get(f"/api/v1/documents/{doc_id}/redactions")
    assert r2.status_code == 200
    persisted = r2.json()[0]
    assert persisted["x"] == x
    assert persisted["y"] == y
    assert persisted["width"] == width
    assert persisted["height"] == height
    assert persisted["page"] == page


async def test_multi_page_redactions_persist_independently(
    db: AsyncIOMotorDatabase,
    authed_client_factory,
    patch_routes_db,
) -> None:
    """Propose redactions on three different pages; verify each is stored
    with its own page number and visible via GET."""
    client = await authed_client_factory(role="user", email="mp@example.com")
    me = await db.users.find_one({"email": "mp@example.com"})
    case_id = await _seed_case_with_team_member(db, me["id"], "analyst")
    doc_id = await _seed_document(db, case_id)
    for page in (1, 5, 10):
        r = await client.post(
            f"/api/v1/documents/{doc_id}/redactions/propose",
            json={
                "x": 0,
                "y": 0,
                "width": 10,
                "height": 10,
                "page": page,
                "category": "S22",
                "reason": f"page-{page}",
            },
        )
        assert r.status_code == 200, r.text
    r = await client.get(f"/api/v1/documents/{doc_id}/redactions/proposed")
    body = r.json()
    pages = sorted(red["page"] for red in body["proposed_redactions"])
    assert pages == [1, 5, 10]


async def test_concurrent_propose_both_succeed(
    db: AsyncIOMotorDatabase,
    authed_client_factory,
    patch_routes_db,
) -> None:
    """Two users propose on the same doc simultaneously. Pin observed
    behavior: mongo's atomic $push means both succeed, array length 2.
    There's no application-level conflict resolution."""
    client_a = await authed_client_factory(role="user", email="ca@example.com")
    client_b = await authed_client_factory(role="user", email="cb@example.com")
    me_a = await db.users.find_one({"email": "ca@example.com"})
    me_b = await db.users.find_one({"email": "cb@example.com"})
    # Both users on the case_team
    case = make_case(
        case_team=[
            {"user_id": me_a["id"], "role": "analyst", "status": "active"},
            {"user_id": me_b["id"], "role": "analyst", "status": "active"},
        ]
    )
    await db.cases.insert_one(case)
    case_id = case["id"]
    doc_id = await _seed_document(db, case_id)

    async def _propose(c: AsyncClient, who: str):
        return await c.post(
            f"/api/v1/documents/{doc_id}/redactions/propose",
            json={
                "x": 0,
                "y": 0,
                "width": 10,
                "height": 10,
                "page": 1,
                "category": "S22",
                "reason": who,
            },
        )

    ra, rb = await asyncio.gather(_propose(client_a, "A"), _propose(client_b, "B"))
    assert ra.status_code == 200
    assert rb.status_code == 200
    doc = await db.documents.find_one({"id": doc_id})
    assert len(doc["redactions"]) == 2
    reasons = {r["proposed_reason"] for r in doc["redactions"]}
    assert reasons == {"A", "B"}


async def test_approval_state_machine_propose_then_approve(
    db: AsyncIOMotorDatabase,
    authed_client_factory,
    patch_routes_db,
) -> None:
    """End-to-end state machine: propose -> approve -> redaction at
    index 0 transitions type=proposed -> professional, status proposed
    -> approved, approval_status pending -> approved."""
    client = await authed_client_factory(role="user", email="sm@example.com")
    me = await db.users.find_one({"email": "sm@example.com"})
    case_id = await _seed_case_with_team_member(db, me["id"], "analyst")
    doc_id = await _seed_document(db, case_id)

    # Propose
    r1 = await client.post(
        f"/api/v1/documents/{doc_id}/redactions/propose",
        json={
            "x": 1,
            "y": 2,
            "width": 3,
            "height": 4,
            "page": 1,
            "category": "S22",
            "reason": "private",
        },
    )
    assert r1.status_code == 200
    doc = await db.documents.find_one({"id": doc_id})
    assert doc["redactions"][0]["type"] == "proposed"
    assert doc["redactions"][0]["approval_status"] == "pending"

    # Approve (same user, who has analyst case role -> can approve)
    r2 = await client.put(
        f"/api/v1/documents/{doc_id}/redactions/0/approve",
        json={"action": "approve", "notes": "ok"},
    )
    assert r2.status_code == 200
    doc = await db.documents.find_one({"id": doc_id})
    assert doc["redactions"][0]["type"] == "professional"
    assert doc["redactions"][0]["status"] == "approved"
    assert doc["redactions"][0]["approval_status"] == "approved"
    assert doc["redactions"][0]["reviewed_by"] == me["id"]
