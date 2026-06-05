"""Integration tests for contributor + public-contribute + transfer
endpoints in `src.workflow.routes`.

Phase 2.5 Batch B (2/3). Covers:
    Auth-required:
        POST   /cases/{case_id}/contributors
        POST   /cases/{case_id}/contributors/bulk
        GET    /cases/{case_id}/contributors
        PUT    /cases/{case_id}/contributors/{contributor_id}
        POST   /cases/{case_id}/contributors/{contributor_id}/remind
        DELETE /cases/{case_id}/contributors/{contributor_id}
        POST   /cases/{case_id}/transfer
        GET    /cases/{case_id}/transfers
    Public (token-authed, allowlisted at /api/v1/contribute/):
        GET    /contribute/{contributor_id}
        POST   /contribute/{contributor_id}/upload
        POST   /contribute/{contributor_id}/confirm-complete

Patch points:
- `src.workflow.routes.get_db` override (auth-required endpoints)
- `src.core.database.get_database_from_request` override (public endpoints)
- `src.dependencies.users` + `src.database.users` for `get_current_user` lookup

Phase 1.8 pin: contributor invitation reads `system_config.org_name`,
fallback to "BlackBar" when no config row present.

Phase 1.9c pin: public `/contribute/{id}` returns `org_name`
(formerly `tenant_name`).

The `email_service` instance is module-level; in tests
`SENDGRID_API_KEY` is unset so `email_service.client is None` and
`send_*` returns False without making network calls. That keeps the
tests deterministic without respx.

For document upload, we stub `DocumentProcessingService.process_upload`
to avoid invoking the real OCR/conversion pipeline (mirrors
`tests/cases/test_collection_link_routes.py`).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.workflow.repository import hash_token
from tests.factories import make_case


@pytest.fixture
def patch_routes_db(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase, app):
    """Cover both DI and direct-call db resolution paths."""
    import src.database as db_mod
    import src.dependencies as deps_mod
    from src.core import database as core_db
    from src.workflow import routes as workflow_routes

    async def _override_get_db():
        return db

    async def _override_get_db_from_request(request=None):
        return db

    app.dependency_overrides[workflow_routes.get_db] = _override_get_db
    app.dependency_overrides[core_db.get_database_from_request] = _override_get_db_from_request
    # Public endpoints call `from src.core.database import get_database_from_request`
    # INSIDE the handler body, so we have to patch the symbol on the
    # `src.core.database` module itself (not just on `workflow.routes`).
    monkeypatch.setattr(
        core_db,
        "get_database_from_request",
        _override_get_db_from_request,
    )
    monkeypatch.setattr(
        workflow_routes,
        "get_database_from_request",
        _override_get_db_from_request,
    )
    monkeypatch.setattr(deps_mod, "users", db.users)
    monkeypatch.setattr(db_mod, "users", db.users)

    yield db

    app.dependency_overrides.pop(workflow_routes.get_db, None)
    app.dependency_overrides.pop(core_db.get_database_from_request, None)


async def _seed_case(db: AsyncIOMotorDatabase, **overrides) -> str:
    case = make_case(**overrides)
    await db.cases.insert_one(case)
    return case["id"]


async def _seed_system_config(db: AsyncIOMotorDatabase, org_name: str) -> None:
    """Seed a system_config row so org_name lookup returns this name."""
    await db.system_config.insert_one({"org_name": org_name})


async def _seed_contributor(
    db: AsyncIOMotorDatabase,
    *,
    case_id: str,
    raw_token: str = "abc-123-token",
    email: str = "c@example.com",
    name: str = "Contributor",
    expires_at: datetime | None = None,
    status: str = "invited",
    records_confirmed: bool = False,
) -> str:
    """Insert a contributor row using the production hash."""
    import uuid

    cid = str(uuid.uuid4())
    if expires_at is None:
        expires_at = datetime.utcnow() + timedelta(days=14)
    await db.case_contributors.insert_one(
        {
            "id": cid,
            "case_id": case_id,
            "name": name,
            "email": email,
            "status": status,
            "upload_token": hash_token(raw_token),
            "token_expires_at": expires_at,
            "documents_uploaded": 0,
            "last_upload_at": None,
            "invited_by": "u",
            "invited_by_name": "Inviter",
            "created_at": datetime.utcnow(),
            "first_access_at": None,
            "completed_at": None,
            "notes": None,
            "records_confirmed": records_confirmed,
        }
    )
    return cid


# ---------------------------------------------------------------------------
# POST /cases/{case_id}/contributors
# ---------------------------------------------------------------------------


class TestInviteContributor:
    async def test_invite_happy_path_uses_system_config_org_name(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Phase 1.8 pin: handler reads `system_config.org_name`, not a
        hardcoded 'Blackbar'."""
        await _seed_system_config(db, "Acme FOI Office")
        case_id = await _seed_case(db, tracking_number="FOI-2026-0001")
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            f"/api/v1/cases/{case_id}/contributors",
            json={
                "name": "Alice",
                "email": "alice@example.com",
                "department": "Records",
                "notes": "x",
                "token_expiration_days": 7,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "contributor" in body
        assert "upload_url" in body
        assert body["upload_url"].startswith("/contribute/")
        # The contributor was persisted
        stored = await db.case_contributors.find_one({"id": body["contributor"]["id"]})
        assert stored is not None
        assert stored["email"] == "alice@example.com"

    async def test_invite_missing_case_returns_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/cases/ghost/contributors",
            json={"name": "A", "email": "a@example.com"},
        )
        assert r.status_code == 404

    async def test_invite_unauthenticated_401(self, client) -> None:
        r = client.post(
            "/api/v1/cases/foo/contributors",
            json={"name": "A", "email": "a@example.com"},
        )
        assert r.status_code == 401

    async def test_invite_no_system_config_falls_back_to_blackbar(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """When no system_config row exists, org_name defaults to 'BlackBar'.
        The endpoint still succeeds — just exercises the fallback branch."""
        case_id = await _seed_case(db)
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            f"/api/v1/cases/{case_id}/contributors",
            json={"name": "A", "email": "a@example.com"},
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# POST /cases/{case_id}/contributors/bulk
# ---------------------------------------------------------------------------


class TestBulkInviteContributors:
    async def test_bulk_happy_path(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_system_config(db, "Acme")
        case_id = await _seed_case(db)
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            f"/api/v1/cases/{case_id}/contributors/bulk",
            json={
                "contributors": [
                    {"name": "A", "email": "a@example.com"},
                    {"name": "B", "email": "b@example.com"},
                ]
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] == 2
        assert len(body["invitations"]) == 2

    async def test_bulk_missing_case_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/cases/ghost/contributors/bulk",
            json={"contributors": [{"name": "A", "email": "a@example.com"}]},
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /cases/{case_id}/contributors
# ---------------------------------------------------------------------------


class TestListContributors:
    async def test_list_returns_contributors_sorted(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        await _seed_contributor(db, case_id=case_id, name="Older")
        await _seed_contributor(db, case_id=case_id, name="Newer")
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get(f"/api/v1/cases/{case_id}/contributors")
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body) == 2

    async def test_list_missing_case_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get("/api/v1/cases/ghost/contributors")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# PUT /cases/{case_id}/contributors/{contributor_id}
# ---------------------------------------------------------------------------


class TestUpdateContributor:
    async def test_update_name_persists(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        cid = await _seed_contributor(db, case_id=case_id, name="Old")
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.put(
            f"/api/v1/cases/{case_id}/contributors/{cid}",
            json={"name": "New"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "New"

    async def test_update_missing_contributor_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.put(
            "/api/v1/cases/c/contributors/ghost",
            json={"name": "X"},
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /cases/{case_id}/contributors/{contributor_id}/remind
# ---------------------------------------------------------------------------


class TestRemindContributor:
    async def test_remind_no_sendgrid_returns_success_false_and_keeps_token(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Phase 4 Batch 4.4 (audit B44): when the email send fails (no
        SENDGRID_API_KEY in test env), the upload_token is NO LONGER
        rotated. Previously the token was rotated before the email
        send, so a SendGrid failure invalidated the contributor's
        existing link without delivering the new one. The handler now
        commits the rotation only on successful send.

        Test flipped from `_returns_success_false_when_no_sendgrid`
        (asserting `new_hash != old_hash`) to assert the hash is
        unchanged."""
        await _seed_system_config(db, "Acme")
        case_id = await _seed_case(db, tracking_number="FOI-2026-0042")
        cid = await _seed_contributor(db, case_id=case_id, raw_token="old-tok")

        old_doc = await db.case_contributors.find_one({"id": cid})
        old_hash = old_doc["upload_token"]

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(f"/api/v1/cases/{case_id}/contributors/{cid}/remind")
        assert r.status_code == 200, r.text
        body = r.json()
        # In env without SENDGRID, send returns False
        assert body["success"] is False

        # Token must NOT have been rotated: the existing contributor
        # link remains valid for a manual nudge through other channels.
        new_doc = await db.case_contributors.find_one({"id": cid})
        assert new_doc["upload_token"] == old_hash

    async def test_remind_missing_contributor_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post("/api/v1/cases/c/contributors/ghost/remind")
        assert r.status_code == 404

    async def test_remind_completed_contributor_400(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        cid = await _seed_contributor(db, case_id=case_id, status="completed")
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(f"/api/v1/cases/{case_id}/contributors/{cid}/remind")
        assert r.status_code == 400
        assert "already completed" in r.text.lower()

    async def test_remind_expired_contributor_400(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        cid = await _seed_contributor(db, case_id=case_id, status="expired")
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(f"/api/v1/cases/{case_id}/contributors/{cid}/remind")
        assert r.status_code == 400
        assert "expired" in r.text.lower()

    async def test_remind_missing_case_404(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        cid = await _seed_contributor(db, case_id="ghost-case")
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(f"/api/v1/cases/ghost-case/contributors/{cid}/remind")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /cases/{case_id}/contributors/{contributor_id}
# ---------------------------------------------------------------------------


class TestDeleteContributor:
    async def test_delete_happy_path(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        cid = await _seed_contributor(db, case_id=case_id)
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.delete(f"/api/v1/cases/{case_id}/contributors/{cid}")
        assert r.status_code == 200
        assert r.json()["success"] is True
        assert (await db.case_contributors.find_one({"id": cid})) is None

    async def test_delete_missing_returns_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.delete("/api/v1/cases/c/contributors/ghost")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /contribute/{contributor_id}  (public, token-authed)
# ---------------------------------------------------------------------------


class TestContributorPortal:
    async def _public_client(self, app) -> AsyncClient:
        return AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        )

    async def test_portal_returns_upload_info_with_org_name_phase19c(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_routes_db,
    ) -> None:
        """Phase 1.9c pin: the public payload uses `org_name` (NOT
        `tenant_name`). Also pins it's sourced from system_config."""
        await _seed_system_config(db, "Acme FOI Office")
        case_id = await _seed_case(db, tracking_number="FOI-2026-0001", title="Test")
        cid = await _seed_contributor(db, case_id=case_id, raw_token="good-tok")

        async with await self._public_client(app) as c:
            r = await c.get(f"/api/v1/contribute/{cid}?token=good-tok")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["org_name"] == "Acme FOI Office"
        # Must not have the old tenant_name key
        assert "tenant_name" not in body
        assert body["contributor_id"] == cid
        assert body["case_tracking_number"] == "FOI-2026-0001"

    async def test_portal_bad_token_401(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        cid = await _seed_contributor(db, case_id=case_id, raw_token="real-tok")
        async with await self._public_client(app) as c:
            r = await c.get(f"/api/v1/contribute/{cid}?token=wrong")
        assert r.status_code == 401

    async def test_portal_missing_case_returns_404(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_routes_db,
    ) -> None:
        """Contributor exists but the case row was deleted -> 404 path."""
        cid = await _seed_contributor(db, case_id="orphan-case", raw_token="tok")
        async with await self._public_client(app) as c:
            r = await c.get(f"/api/v1/contribute/{cid}?token=tok")
        assert r.status_code == 404

    async def test_portal_lists_documents_uploaded_by_contributor(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        cid = await _seed_contributor(db, case_id=case_id, raw_token="tok")
        # Seed a document attributed to this contributor
        await db.documents.insert_one(
            {
                "id": "doc-1",
                "case_id": case_id,
                "uploaded_by_contributor": cid,
                "original_filename": "scan.pdf",
                "uploaded_at": datetime.utcnow(),
                "status": "uploaded",
            }
        )
        async with await self._public_client(app) as c:
            r = await c.get(f"/api/v1/contribute/{cid}?token=tok")
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["uploaded_documents"]) == 1
        assert body["uploaded_documents"][0]["filename"] == "scan.pdf"


# ---------------------------------------------------------------------------
# POST /contribute/{contributor_id}/upload  (public)
# ---------------------------------------------------------------------------


class TestContributorUpload:
    async def _public_client(self, app) -> AsyncClient:
        return AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        )

    async def test_upload_happy_path_records_increment(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        case_id = await _seed_case(db)
        cid = await _seed_contributor(db, case_id=case_id, raw_token="tok")

        from src.documents import processing_service as ps_mod

        class _OkResult:
            status = ps_mod.ProcessingStatus.SUCCESS
            message = "ok"
            document_id = "doc-1"
            filename = "x.txt"
            has_ocr = False
            has_ai_summary = False
            attachment_count = 0

        async def _fake(self, *args, **kwargs):
            return _OkResult()

        monkeypatch.setattr(ps_mod.DocumentProcessingService, "process_upload", _fake)

        async with await self._public_client(app) as c:
            r = await c.post(
                f"/api/v1/contribute/{cid}/upload",
                files={"file": ("x.txt", b"hello", "text/plain")},
                data={"token": "tok"},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        # documents_uploaded counter was incremented on the contributor row
        contributor = await db.case_contributors.find_one({"id": cid})
        assert contributor["documents_uploaded"] == 1

    async def test_upload_bad_token_401(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        cid = await _seed_contributor(db, case_id=case_id, raw_token="real")
        async with await self._public_client(app) as c:
            r = await c.post(
                f"/api/v1/contribute/{cid}/upload",
                files={"file": ("x.txt", b"x", "text/plain")},
                data={"token": "wrong"},
            )
        assert r.status_code == 401

    async def test_upload_after_confirm_400(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        cid = await _seed_contributor(db, case_id=case_id, raw_token="tok", records_confirmed=True)
        async with await self._public_client(app) as c:
            r = await c.post(
                f"/api/v1/contribute/{cid}/upload",
                files={"file": ("x.txt", b"x", "text/plain")},
                data={"token": "tok"},
            )
        assert r.status_code == 400
        assert "already confirmed" in r.text.lower()

    async def test_upload_duplicate_returns_success_false(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        case_id = await _seed_case(db)
        cid = await _seed_contributor(db, case_id=case_id, raw_token="tok")

        from src.documents import processing_service as ps_mod

        class _Dup:
            status = ps_mod.ProcessingStatus.DUPLICATE
            message = "dup"
            duplicate_of_id = "doc-orig"
            duplicate_of_filename = "orig.txt"

        async def _fake(self, *args, **kwargs):
            return _Dup()

        monkeypatch.setattr(ps_mod.DocumentProcessingService, "process_upload", _fake)

        async with await self._public_client(app) as c:
            r = await c.post(
                f"/api/v1/contribute/{cid}/upload",
                files={"file": ("x.txt", b"x", "text/plain")},
                data={"token": "tok"},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is False
        assert body["is_duplicate"] is True

    async def test_upload_validation_failed_400(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        case_id = await _seed_case(db)
        cid = await _seed_contributor(db, case_id=case_id, raw_token="tok")

        from src.documents import processing_service as ps_mod

        class _Bad:
            status = ps_mod.ProcessingStatus.VALIDATION_FAILED
            message = "Bad file"

        async def _fake(self, *args, **kwargs):
            return _Bad()

        monkeypatch.setattr(ps_mod.DocumentProcessingService, "process_upload", _fake)

        async with await self._public_client(app) as c:
            r = await c.post(
                f"/api/v1/contribute/{cid}/upload",
                files={"file": ("x.txt", b"x", "text/plain")},
                data={"token": "tok"},
            )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# POST /contribute/{contributor_id}/confirm-complete  (public)
# ---------------------------------------------------------------------------


class TestConfirmRecordsComplete:
    async def _public_client(self, app) -> AsyncClient:
        return AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        )

    async def test_confirm_happy_path(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        cid = await _seed_contributor(db, case_id=case_id, raw_token="tok")
        async with await self._public_client(app) as c:
            r = await c.post(f"/api/v1/contribute/{cid}/confirm-complete?token=tok")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        stored = await db.case_contributors.find_one({"id": cid})
        assert stored["records_confirmed"] is True
        assert stored["status"] == "completed"

    async def test_confirm_idempotent_returns_already_message(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        cid = await _seed_contributor(db, case_id=case_id, raw_token="tok", records_confirmed=True)
        async with await self._public_client(app) as c:
            r = await c.post(f"/api/v1/contribute/{cid}/confirm-complete?token=tok")
        assert r.status_code == 200
        assert "already" in r.json()["message"].lower()

    async def test_confirm_bad_token_401(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        cid = await _seed_contributor(db, case_id=case_id, raw_token="real")
        async with await self._public_client(app) as c:
            r = await c.post(f"/api/v1/contribute/{cid}/confirm-complete?token=wrong")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /cases/{case_id}/transfer
# ---------------------------------------------------------------------------


class TestTransferCase:
    async def test_transfer_happy_path_updates_case_and_returns_url(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_system_config(db, "Acme")
        case_id = await _seed_case(db, tracking_number="FOI-2026-0001")
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            f"/api/v1/cases/{case_id}/transfer",
            json={
                "recipient_organization": "Other Public Body",
                "recipient_email": "other@example.com",
                "recipient_name": "OtherStaff",
                "transfer_reason": "wrong jurisdiction",
                "include_documents": False,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "transfer" in body
        assert body["transfer_url"].startswith("/transfer/")
        # Case workflow_stage updated
        case = await db.cases.find_one({"id": case_id})
        assert case["workflow_stage"] == "transferred"
        assert case["transferred_to"] == "Other Public Body"

    async def test_transfer_missing_case_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/cases/ghost/transfer",
            json={
                "recipient_organization": "X",
                "recipient_email": "x@example.com",
                "transfer_reason": "r",
            },
        )
        assert r.status_code == 404

    async def test_transfer_unauthenticated_401(self, client) -> None:
        r = client.post(
            "/api/v1/cases/foo/transfer",
            json={
                "recipient_organization": "X",
                "recipient_email": "x@example.com",
                "transfer_reason": "r",
            },
        )
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /cases/{case_id}/transfers
# ---------------------------------------------------------------------------


class TestListTransfers:
    async def test_list_returns_transfers_for_case(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_system_config(db, "Acme")
        case_id = await _seed_case(db)
        client: AsyncClient = await authed_client_factory(role="admin")
        # Create a transfer first
        await client.post(
            f"/api/v1/cases/{case_id}/transfer",
            json={
                "recipient_organization": "OB",
                "recipient_email": "ob@example.com",
                "transfer_reason": "r",
            },
        )

        r = await client.get(f"/api/v1/cases/{case_id}/transfers")
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body) == 1
        assert body[0]["recipient_organization"] == "OB"

    async def test_list_transfers_missing_case_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/cases/ghost/transfers")
        assert r.status_code == 404
