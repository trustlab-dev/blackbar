"""Integration tests for `src.cases.routes` (core cases CRUD endpoints).

Phase 2.2.D (2/3). Target >=80% line coverage on src.cases.routes.

Endpoints under test (mounted at /api/v1/cases/...):
    POST   /                            -- create_case
    GET    /                            -- list_cases
    GET    /{case_id}                   -- get_case
    PUT    /{case_id}                   -- update_case
    POST   /{case_id}/documents         -- add_documents_to_case
    DELETE /{case_id}/documents         -- remove_documents_from_case
    GET    /{case_id}/documents         -- get_case_documents
    PUT    /{case_id}/assign            -- assign_case
    DELETE /{case_id}                   -- delete_case
    PUT    /{case_id}/status            -- update_case_status
    PUT    /{case_id}/priority          -- update_case_priority
    POST   /{case_id}/comments          -- add_comment
    GET    /{case_id}/comments          -- get_comments
    POST   /{case_id}/generate-letter   -- 501 stub

Reality pins surfaced while writing these tests:
- Route decorators reference `"owner"` user role but is vestigial; the
  4-tier model is `admin/analyst/user/guest`. Membership-set comparison
  silently passes the unknown entry.
- Case-team-role taxonomy is a separate 7-tier system from user roles.
- `create_case` calls `get_system_config()` which reads
  `db.system_config` captured at module import time. We monkeypatch
  `src.admin.config_routes.config_collection` to point at the test
  db so default-config inserts don't hit a closed global client.
- `update_case` permission check uses user_role in
  ["owner","admin","manager"] — "manager" is a case-team role bleed-
  through into a system-role check. Pinned as a source surprise.
- `assign_case` does not return 404 for missing cases — instead it
  silently 404s via the find_one returning None then crashes on
  `case.get(...)`. Pin reality: missing case yields 404 from the
  explicit existence check.
"""

from __future__ import annotations

import uuid
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
    """Rebind every db-resolution path used by cases/routes.py:
    - `app.dependency_overrides` for cases.routes.get_db (Depends path
      used by create/get/update/assign/comments/documents endpoints).
    - `cases.routes.get_database_from_request` — list_cases calls
      `db = await get_db(request)` DIRECTLY (no Depends), which itself
      calls `get_database_from_request`. We monkeypatch that symbol
      on cases.routes module so the imported binding sees the test db.
    - `src.dependencies.users` — get_current_user reads users via the
      captured-at-import global.
    - `src.database.users` — the lazy import path in some sub-routes.
    - `src.admin.config_routes.config_collection` — create_case calls
      `get_system_config()` which uses this module-captured collection.
    """
    import src.admin.config_routes as cfg_mod
    import src.database as db_mod
    import src.dependencies as deps_mod
    from src.cases import routes as cases_routes

    async def _override_get_db_from_request(request=None):
        return db

    async def _override_get_db():
        return db

    app.dependency_overrides[cases_routes.get_db] = _override_get_db
    monkeypatch.setattr(cases_routes, "get_database_from_request", _override_get_db_from_request)
    monkeypatch.setattr(deps_mod, "users", db.users)
    monkeypatch.setattr(db_mod, "users", db.users)
    monkeypatch.setattr(cfg_mod, "config_collection", db.system_config)

    yield db

    app.dependency_overrides.pop(cases_routes.get_db, None)


async def _seed_case(db: AsyncIOMotorDatabase, **overrides) -> str:
    doc = make_case(**overrides)
    await db.cases.insert_one(doc)
    return doc["id"]


# ---------------------------------------------------------------------------
# POST / — create_case
# ---------------------------------------------------------------------------


class TestCreateCase:
    async def test_admin_can_create_case(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/cases/",
            json={"title": "New case", "description": "Hello"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["title"] == "New case"
        assert body["status"] == "new"
        assert body["tracking_number"].startswith("FOI-")
        assert len(body["case_team"]) == 1
        assert body["case_team"][0]["role"] == "analyst"

        stored = await db.cases.find_one({"id": body["id"]})
        assert stored is not None

    async def test_create_case_assigns_default_priority_when_omitted(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/cases/",
            json={"title": "Priority default", "description": "x"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["priority"] in {"normal", "medium"}

    async def test_user_role_forbidden_from_creating_case(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="user")
        r = await client.post(
            "/api/v1/cases/",
            json={"title": "Nope", "description": "x"},
        )
        assert r.status_code == 403

    async def test_create_case_unauthenticated_returns_401(
        self,
        client,
    ) -> None:
        r = client.post("/api/v1/cases/", json={"title": "x"})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET / — list_cases
# ---------------------------------------------------------------------------


class TestListCases:
    async def test_admin_sees_all_cases(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_case(db, title="A")
        await _seed_case(db, title="B")

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/cases/")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 2
        assert len(body["cases"]) == 2

    async def test_user_only_sees_own_team_cases(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="user", email="me@example.com")
        me = await db.users.find_one({"email": "me@example.com"})
        my_id = me["id"]

        await _seed_case(
            db,
            title="Mine",
            case_team=[
                {
                    "user_id": my_id,
                    "role": "analyst",
                    "department": None,
                    "permissions": [],
                    "added_at": datetime.utcnow().isoformat(),
                    "added_by": my_id,
                    "status": "active",
                    "notes": "",
                }
            ],
        )
        await _seed_case(db, title="Theirs")

        r = await client.get("/api/v1/cases/")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["cases"][0]["title"] == "Mine"

    async def test_list_cases_filter_by_status(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_case(db, status="new")
        await _seed_case(db, status="closed")

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/cases/?status=new")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["cases"][0]["status"] == "new"


# ---------------------------------------------------------------------------
# GET /{case_id} — get_case
# ---------------------------------------------------------------------------


class TestGetCase:
    async def test_admin_can_get_case(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db, title="The Case")
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get(f"/api/v1/cases/{case_id}")
        assert r.status_code == 200
        assert r.json()["title"] == "The Case"

    async def test_get_case_missing_returns_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/cases/ghost-case-id")
        assert r.status_code == 404

    async def test_user_cannot_view_case_they_arent_on(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db, title="Closed off")
        client: AsyncClient = await authed_client_factory(role="user", email="outsider@example.com")
        r = await client.get(f"/api/v1/cases/{case_id}")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# PUT /{case_id} — update_case
# ---------------------------------------------------------------------------


class TestUpdateCase:
    async def test_admin_can_update_case_title(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db, title="Old")
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.put(
            f"/api/v1/cases/{case_id}",
            json={"title": "New"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["title"] == "New"

    async def test_update_missing_case_returns_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.put(
            "/api/v1/cases/no-such-id",
            json={"title": "x"},
        )
        assert r.status_code == 404

    async def test_update_case_user_role_forbidden_when_not_on_team(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        client: AsyncClient = await authed_client_factory(role="user")
        r = await client.put(
            f"/api/v1/cases/{case_id}",
            json={"title": "Nope"},
        )
        # user role is not in update_case dependencies decorator's role
        # list (owner/admin/analyst), so check_role rejects first with 403
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# POST /{case_id}/documents — add_documents_to_case
# ---------------------------------------------------------------------------


class TestAddDocuments:
    async def test_admin_can_add_documents(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        doc_id = str(uuid.uuid4())
        await db.documents.insert_one({"id": doc_id, "filename": "f.pdf"})

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            f"/api/v1/cases/{case_id}/documents",
            json=[doc_id],
        )
        assert r.status_code == 200, r.text

        case = await db.cases.find_one({"id": case_id})
        assert doc_id in case["document_ids"]

    async def test_add_documents_unknown_doc_returns_404(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            f"/api/v1/cases/{case_id}/documents",
            json=["ghost-doc-id"],
        )
        assert r.status_code == 404

    async def test_add_documents_missing_case_returns_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/cases/ghost/documents",
            json=["x"],
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /{case_id}/documents — remove_documents_from_case
# ---------------------------------------------------------------------------


class TestRemoveDocuments:
    async def test_admin_can_remove_documents(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        doc_id = str(uuid.uuid4())
        case_id = await _seed_case(db, document_ids=[doc_id])

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.request(
            "DELETE",
            f"/api/v1/cases/{case_id}/documents",
            json=[doc_id],
        )
        assert r.status_code == 200

        case = await db.cases.find_one({"id": case_id})
        assert doc_id not in case["document_ids"]

    async def test_remove_documents_missing_case_returns_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.request("DELETE", "/api/v1/cases/ghost/documents", json=["x"])
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /{case_id}/documents — get_case_documents
# ---------------------------------------------------------------------------


class TestGetCaseDocuments:
    async def test_admin_can_get_case_documents(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        doc_id = str(uuid.uuid4())
        case_id = await _seed_case(db, document_ids=[doc_id])
        await db.documents.insert_one(
            {
                "id": doc_id,
                "filename": "test.pdf",
                "mime_type": "application/pdf",
            }
        )

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get(f"/api/v1/cases/{case_id}/documents")
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["documents"]) == 1
        assert body["documents"][0]["filename"] == "test.pdf"

    async def test_get_case_documents_empty_list(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get(f"/api/v1/cases/{case_id}/documents")
        assert r.status_code == 200
        assert r.json()["documents"] == []

    async def test_get_case_documents_missing_case_returns_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/cases/ghost/documents")
        assert r.status_code == 404

    async def test_get_case_documents_collapses_email_threads(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Pin the email-thread collapsing branch:
        two emails in the same thread (same normalized subject/from/to)
        return only the latest (by upload_date)."""
        d1 = str(uuid.uuid4())
        d2 = str(uuid.uuid4())
        case_id = await _seed_case(db, document_ids=[d1, d2])
        await db.documents.insert_one(
            {
                "id": d1,
                "filename": "early.eml",
                "mime_type": "message/rfc822",
                "thread_metadata": {
                    "normalized_subject": "Hello",
                    "from": "a@example.com",
                    "to": "b@example.com",
                },
                "upload_date": datetime(2024, 1, 1),
            }
        )
        await db.documents.insert_one(
            {
                "id": d2,
                "filename": "latest.eml",
                "mime_type": "message/rfc822",
                "thread_metadata": {
                    "normalized_subject": "Hello",
                    "from": "a@example.com",
                    "to": "b@example.com",
                },
                "upload_date": datetime(2024, 6, 1),
            }
        )

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get(f"/api/v1/cases/{case_id}/documents")
        assert r.status_code == 200
        body = r.json()
        # Thread collapsing keeps only the latest email
        assert len(body["documents"]) == 1
        assert body["documents"][0]["filename"] == "latest.eml"


# ---------------------------------------------------------------------------
# PUT /{case_id}/assign — assign_case
# ---------------------------------------------------------------------------


class TestAssignCase:
    async def test_admin_can_assign_case(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.put(
            f"/api/v1/cases/{case_id}/assign",
            json={"assignee": "user-99", "team": "team-a"},
        )
        assert r.status_code == 200, r.text

        case = await db.cases.find_one({"id": case_id})
        assert case["assignee"] == "user-99"
        assert case["team"] == "team-a"
        assert "user-99" in case.get("assigned_user_ids", [])

    async def test_assign_missing_case_returns_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.put(
            "/api/v1/cases/ghost/assign",
            json={"assignee": "u1"},
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /{case_id} — delete_case
# ---------------------------------------------------------------------------


class TestDeleteCase:
    async def test_admin_can_delete_case(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.delete(f"/api/v1/cases/{case_id}")
        assert r.status_code == 200, r.text
        assert r.json()["case_id"] == case_id

        case = await db.cases.find_one({"id": case_id})
        assert case is None

    async def test_delete_case_also_deletes_documents(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        doc_id = str(uuid.uuid4())
        await db.documents.insert_one({"id": doc_id, "filename": "f.pdf"})
        case_id = await _seed_case(db, document_ids=[doc_id])

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.delete(f"/api/v1/cases/{case_id}")
        assert r.status_code == 200
        assert r.json()["deleted_documents"] == 1

        doc = await db.documents.find_one({"id": doc_id})
        assert doc is None

    async def test_delete_missing_case_returns_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.delete("/api/v1/cases/no-such-case")
        assert r.status_code == 404

    async def test_analyst_forbidden_from_deleting_case(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.delete(f"/api/v1/cases/{case_id}")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# PUT /{case_id}/status — update_case_status
# ---------------------------------------------------------------------------


class TestUpdateStatus:
    async def test_admin_can_change_status(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db, status="new")
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.put(
            f"/api/v1/cases/{case_id}/status",
            json="in_progress",
        )
        assert r.status_code == 200, r.text
        case = await db.cases.find_one({"id": case_id})
        assert case["status"] == "in_progress"
        # Audit entry was pushed
        assert any(e["action"] == "status_changed" for e in case["audit_log"])

    async def test_update_status_missing_case_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.put("/api/v1/cases/no-such/status", json="closed")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# PUT /{case_id}/priority — update_case_priority
# ---------------------------------------------------------------------------


class TestUpdatePriority:
    async def test_admin_can_change_priority(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db, priority="medium")
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.put(f"/api/v1/cases/{case_id}/priority", json="high")
        assert r.status_code == 200
        case = await db.cases.find_one({"id": case_id})
        assert case["priority"] == "high"

    async def test_analyst_forbidden_from_priority_change(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Priority change is `owner/admin` only — analyst rejected."""
        case_id = await _seed_case(db)
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.put(f"/api/v1/cases/{case_id}/priority", json="high")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# POST /{case_id}/comments — add_comment
# ---------------------------------------------------------------------------


class TestAddComment:
    async def test_admin_can_add_internal_comment(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            f"/api/v1/cases/{case_id}/comments",
            json={"text": "Internal note", "type": "internal"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["comment"]["text"] == "Internal note"

        case = await db.cases.find_one({"id": case_id})
        assert len(case["comments"]) == 1

    async def test_add_comment_missing_case_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/cases/no-such/comments",
            json={"text": "x", "type": "internal"},
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /{case_id}/comments — get_comments
# ---------------------------------------------------------------------------


class TestGetComments:
    async def test_admin_can_get_comments(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(
            db,
            comments=[
                {
                    "id": "c1",
                    "author_id": "u1",
                    "author_name": "A",
                    "text": "Hi",
                    "type": "public",
                    "created_at": datetime.utcnow(),
                },
                {
                    "id": "c2",
                    "author_id": "u1",
                    "author_name": "A",
                    "text": "Secret",
                    "type": "internal",
                    "created_at": datetime.utcnow(),
                },
            ],
        )

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get(f"/api/v1/cases/{case_id}/comments")
        assert r.status_code == 200
        body = r.json()
        assert len(body["comments"]) == 2

    async def test_get_comments_excludes_internal_when_flag_false(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(
            db,
            comments=[
                {
                    "id": "c1",
                    "author_id": "u1",
                    "author_name": "A",
                    "text": "Hi",
                    "type": "public",
                    "created_at": datetime.utcnow(),
                },
                {
                    "id": "c2",
                    "author_id": "u1",
                    "author_name": "A",
                    "text": "Secret",
                    "type": "internal",
                    "created_at": datetime.utcnow(),
                },
            ],
        )

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get(f"/api/v1/cases/{case_id}/comments?include_internal=false")
        assert r.status_code == 200
        body = r.json()
        assert len(body["comments"]) == 1
        assert body["comments"][0]["type"] == "public"

    async def test_get_comments_missing_case_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/cases/no-such/comments")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /{case_id}/generate-letter — 501 stub
# ---------------------------------------------------------------------------


class TestGenerateLetterStub:
    async def test_generate_letter_returns_501_not_implemented(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(f"/api/v1/cases/{case_id}/generate-letter")
        assert r.status_code == 501
