"""Integration tests for `src.cases.collection_link_routes` endpoints.

Phase 2.2.C (2/5). Target >=80% line coverage on
src.cases.collection_link_routes.

Endpoints under test (all mounted at /api/v1/cases/...):
    POST   /{case_id}/collection-links             (role-gated)
    GET    /{case_id}/collection-links             (role-gated)
    DELETE /{case_id}/collection-links/{link_id}   (role-gated)
    GET    /collect/{token}                        (intended public)
    POST   /collect/{token}/upload                 (intended public)

**Reality pin** — auth surface of /collect/* endpoints:
The AuthMiddleware (`src/core/auth_middleware.py`) bypasses auth on
paths starting with the public-prefix list, which includes
`/api/v1/cases/public/` and `/collect/` (FE), but NOT
`/api/v1/cases/collect/`. So while the route handlers themselves
declare no auth dependency (token is the auth), the middleware still
requires an Authorization header on the actual API URL. The
result is: these endpoints are unreachable WITHOUT a JWT, even though
the handlers were designed to work tokenlessly. Pinned for audit
Section 11.

Test infrastructure:
- Use the same `patch_routes_db` pattern as test_queue_routes: override
  both `cases.routes.get_db` and `collection_link_routes.get_db`,
  monkeypatch `src.dependencies.users` and `src.database.users`.
"""

from __future__ import annotations

from datetime import datetime

import httpx
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
    from src.cases import collection_link_routes
    from src.cases import routes as cases_routes

    async def _override_get_db(_req=None):
        return db

    # Capture the ORIGINAL function references before monkey-patching,
    # so the FastAPI dependency_overrides key matches the function the
    # route's `Depends(get_db)` was bound to at import time.
    orig_link_get_db = collection_link_routes.get_db
    orig_cases_get_db = cases_routes.get_db

    # FastAPI dependency overrides for the role-gated endpoints (Depends path).
    app.dependency_overrides[orig_link_get_db] = _override_get_db
    app.dependency_overrides[orig_cases_get_db] = _override_get_db
    # The /collect/{token} and /collect/{token}/upload handlers call
    # `get_db(http_request)` DIRECTLY (not via Depends), so we also
    # monkey-patch the module-level reference.
    monkeypatch.setattr(collection_link_routes, "get_db", _override_get_db)
    monkeypatch.setattr(deps_mod, "users", db.users)
    monkeypatch.setattr(db_mod, "users", db.users)

    yield db

    app.dependency_overrides.pop(orig_link_get_db, None)
    app.dependency_overrides.pop(orig_cases_get_db, None)


async def _seed_case(db: AsyncIOMotorDatabase, **overrides) -> str:
    doc = make_case(**overrides)
    await db.cases.insert_one(doc)
    return doc["id"]


# ---------------------------------------------------------------------------
# POST /{case_id}/collection-links
# ---------------------------------------------------------------------------


class TestCreateCollectionLink:
    async def test_admin_can_create_collection_link(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            f"/api/v1/cases/{case_id}/collection-links",
            json={
                "case_id": case_id,
                "max_uploads": 5,
                "notes": "test",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["case_id"] == case_id
        assert body["max_uploads"] == 5
        assert body["upload_count"] == 0
        assert body["is_active"] is True
        assert body["url"].startswith("/collect/")
        assert "token" in body

        # Verify persisted on the case
        case = await db.cases.find_one({"id": case_id})
        assert len(case["collection_links"]) == 1
        assert case["collection_links"][0]["token"] == body["token"]

    async def test_create_collection_link_missing_case_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/cases/ghost-case-id/collection-links",
            json={"case_id": "ghost-case-id"},
        )
        assert r.status_code == 404

    async def test_user_role_cannot_create_collection_link(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        client: AsyncClient = await authed_client_factory(role="user")
        r = await client.post(
            f"/api/v1/cases/{case_id}/collection-links",
            json={"case_id": case_id},
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# GET /{case_id}/collection-links
# ---------------------------------------------------------------------------


class TestGetCollectionLinks:
    async def test_admin_can_list_collection_links(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        # Seed a case with one existing link
        case_id = await _seed_case(
            db,
            collection_links=[
                {
                    "id": "lnk-1",
                    "case_id": "",  # placeholder
                    "token": "tok-abc",
                    "is_active": True,
                    "max_uploads": None,
                    "upload_count": 0,
                    "created_at": datetime.utcnow(),
                }
            ],
        )
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get(f"/api/v1/cases/{case_id}/collection-links")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "links" in body
        assert len(body["links"]) == 1
        assert body["links"][0]["url"].endswith("/tok-abc")

    async def test_get_links_missing_case_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get("/api/v1/cases/ghost/collection-links")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /{case_id}/collection-links/{link_id}
# ---------------------------------------------------------------------------


class TestDeactivateCollectionLink:
    async def test_admin_can_deactivate(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(
            db,
            collection_links=[{"id": "doomed", "token": "x", "is_active": True}],
        )
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.delete(f"/api/v1/cases/{case_id}/collection-links/doomed")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True

        # Verify it's marked inactive
        case = await db.cases.find_one({"id": case_id})
        assert case["collection_links"][0]["is_active"] is False

    async def test_deactivate_missing_link_returns_404(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.delete(f"/api/v1/cases/{case_id}/collection-links/never-existed")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /collect/{token}
# ---------------------------------------------------------------------------


class TestGetCollectionInfoPublic:
    """The route handler accepts no auth dependency — token IS the auth.
    `/api/v1/cases/collect/` is in the AuthMiddleware public-prefix
    allowlist (added 2026-05-12 to fix audit finding B14), so requests
    reach the handler without a JWT and the handler validates the
    token from the URL path."""

    async def test_get_collection_info_unauthenticated_invalid_token_404(
        self,
        app,
        patch_routes_db,
    ) -> None:
        """Public route — no JWT required; invalid token returns 404 from
        the handler, not 401 from the middleware.

        Phase 2.10 fix (B53 family): use httpx.AsyncClient + ASGITransport
        instead of the sync `client` fixture so the test's motor `db`
        fixture and the request share the same event loop. The sync
        TestClient spawns its own loop, which closes before the `db`
        fixture's teardown can call `drop_database`, causing
        "Event loop is closed" errors at teardown.
        """
        from httpx import ASGITransport

        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as c:
            r = await c.get("/api/v1/cases/collect/sometoken")
        assert r.status_code == 404

    async def test_get_collection_info_invalid_token_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="user")
        r = await client.get("/api/v1/cases/collect/no-such-token")
        assert r.status_code == 404

    async def test_get_collection_info_happy_path(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_case(
            db,
            title="Public Case",
            collection_links=[
                {
                    "id": "lk",
                    "token": "good-token",
                    "is_active": True,
                    "upload_count": 0,
                    "max_uploads": 3,
                    "expires_at": None,
                }
            ],
        )
        client: AsyncClient = await authed_client_factory(role="user")
        r = await client.get("/api/v1/cases/collect/good-token")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["case_title"] == "Public Case"
        assert body["max_uploads"] == 3

    async def test_get_collection_info_deactivated_link_returns_403(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Pin the is_link_valid() inactive branch."""
        await _seed_case(
            db,
            collection_links=[
                {
                    "id": "lk",
                    "token": "inactive-token",
                    "is_active": False,
                    "upload_count": 0,
                }
            ],
        )
        client: AsyncClient = await authed_client_factory(role="user")
        r = await client.get("/api/v1/cases/collect/inactive-token")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# POST /collect/{token}/upload
# ---------------------------------------------------------------------------


class TestUploadCollectionPublic:
    """Public upload route — token IS the auth. `/api/v1/cases/collect/`
    in middleware public-prefix allowlist (B14 fix)."""

    async def test_upload_unauthenticated_invalid_token_404(
        self,
        app,
        patch_routes_db,
    ) -> None:
        """Phase 2.10 fix (B53 family): see sibling test note. Uses
        `httpx.AsyncClient` + `ASGITransport` to share the event loop with
        the `db` fixture."""
        from httpx import ASGITransport

        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as c:
            r = await c.post(
                "/api/v1/cases/collect/sometoken/upload",
                files={"file": ("x.txt", b"hello", "text/plain")},
                data={
                    "submitter_name": "X",
                    "submitter_email": "x@example.com",
                },
            )
        assert r.status_code == 404

    async def test_upload_invalid_token_returns_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="user")
        r = await client.post(
            "/api/v1/cases/collect/bad-token/upload",
            files={"file": ("x.txt", b"x", "text/plain")},
            data={
                "submitter_name": "X",
                "submitter_email": "x@example.com",
            },
        )
        assert r.status_code == 404

    async def test_upload_inactive_link_returns_403(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_case(
            db,
            collection_links=[
                {
                    "id": "lk",
                    "token": "off-token",
                    "is_active": False,
                    "upload_count": 0,
                }
            ],
        )
        client: AsyncClient = await authed_client_factory(role="user")
        r = await client.post(
            "/api/v1/cases/collect/off-token/upload",
            files={"file": ("a.txt", b"x", "text/plain")},
            data={
                "submitter_name": "X",
                "submitter_email": "x@example.com",
            },
        )
        assert r.status_code == 403

    async def test_upload_happy_path_increments_count_and_logs_audit(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Exercise the upload handler body — mocks
        DocumentProcessingService to avoid invoking the real OCR /
        attachment pipeline. Pins:
        - Upload count is `$inc`-ed by 1 on the relevant link.
        - An audit_log entry with action="document_uploaded_via_collection_link"
          is appended.
        """
        case_id = await _seed_case(
            db,
            collection_links=[
                {
                    "id": "lk1",
                    "token": "good-up-tok",
                    "is_active": True,
                    "upload_count": 0,
                    "max_uploads": None,
                }
            ],
        )

        # Stub DocumentProcessingService.process_upload
        from src.documents import processing_service as ps_mod

        class _FakeResult:
            status = ps_mod.ProcessingStatus.SUCCESS
            message = "ok"
            document_id = "doc-123"
            filename = "uploaded.txt"
            has_ocr = False
            has_ai_summary = False
            attachment_count = 0
            conversion_status = "n/a"
            duplicate_of_id = None
            duplicate_of_filename = None

        async def _fake_process_upload(self, *args, **kwargs):
            return _FakeResult()

        monkeypatch.setattr(
            ps_mod.DocumentProcessingService,
            "process_upload",
            _fake_process_upload,
        )

        client: AsyncClient = await authed_client_factory(role="user")
        r = await client.post(
            "/api/v1/cases/collect/good-up-tok/upload",
            files={"file": ("uploaded.txt", b"hello world", "text/plain")},
            data={
                "submitter_name": "Alice",
                "submitter_email": "alice@example.com",
                "notes": "look",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["document_id"] == "doc-123"

        # Verify upload_count was incremented and audit log added
        case = await db.cases.find_one({"id": case_id})
        assert case["collection_links"][0]["upload_count"] == 1
        assert any(
            e.get("action") == "document_uploaded_via_collection_link"
            for e in case.get("audit_log", [])
        )

    async def test_upload_duplicate_returns_success_false(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Pin the duplicate-status branch (lines 208-215)."""
        await _seed_case(
            db,
            collection_links=[
                {
                    "id": "lkd",
                    "token": "dup-tok",
                    "is_active": True,
                    "upload_count": 0,
                }
            ],
        )

        from src.documents import processing_service as ps_mod

        class _DupResult:
            status = ps_mod.ProcessingStatus.DUPLICATE
            message = "Already uploaded"
            duplicate_of_id = "doc-orig"
            duplicate_of_filename = "orig.txt"

        async def _fake(self, *args, **kwargs):
            return _DupResult()

        monkeypatch.setattr(ps_mod.DocumentProcessingService, "process_upload", _fake)

        client: AsyncClient = await authed_client_factory(role="user")
        r = await client.post(
            "/api/v1/cases/collect/dup-tok/upload",
            files={"file": ("dup.txt", b"x", "text/plain")},
            data={
                "submitter_name": "X",
                "submitter_email": "x@example.com",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is False
        assert body["is_duplicate"] is True

    async def test_upload_validation_failed_returns_400(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Pin the validation/error result branch -> 400."""
        await _seed_case(
            db,
            collection_links=[
                {
                    "id": "lkv",
                    "token": "vf-tok",
                    "is_active": True,
                    "upload_count": 0,
                }
            ],
        )

        from src.documents import processing_service as ps_mod

        class _FailResult:
            status = ps_mod.ProcessingStatus.VALIDATION_FAILED
            message = "Bad file"

        async def _fake(self, *args, **kwargs):
            return _FailResult()

        monkeypatch.setattr(ps_mod.DocumentProcessingService, "process_upload", _fake)

        client: AsyncClient = await authed_client_factory(role="user")
        r = await client.post(
            "/api/v1/cases/collect/vf-tok/upload",
            files={"file": ("bad.txt", b"x", "text/plain")},
            data={
                "submitter_name": "X",
                "submitter_email": "x@example.com",
            },
        )
        assert r.status_code == 400
