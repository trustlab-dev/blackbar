"""Integration tests for `src.cases.public_routes` endpoints.

Phase 2.2.D (1/3). Absorbs the pre-Phase-1.5 tests/test_public_routes.py
and fixes the 9 failures caused by Phase 1 tenant cleanup drift:
- Original tests used `TestClient` + `mock.patch('src.auth.dependencies
  .get_current_user_public', ...)` which never intercepted because
  the route module captured the dependency at import time and the
  AuthMiddleware now sits in front of every protected endpoint.
- Original tests passed `Authorization: Bearer mock-jwt-token` which
  fails JWT validation in `get_current_user_public`.
- Original tests mocked `get_database` which is no longer the
  injection point — routes now use `Depends(get_database_from_request)`.

Target: >=80% line coverage on src.cases.public_routes.

Endpoints under test (mounted at /api/v1/cases/public/...):
    POST   /submit                  -- anonymous public submission
    GET    /track/{tracking_number} -- anonymous public tracking
    GET    /my-requests             -- public user JWT required
    GET    /{request_id}            -- public user JWT required
    GET    /stats/summary           -- public user JWT required
    GET    /health                  -- anonymous health check
    GET    /release/{access_token}  -- public token-based download

Reality pins surfaced while writing these tests:
- `get_request_details` uses Mongo `_id` as `ObjectId(request_id)` for
  lookup (despite app-level `id` UUID being the canonical key elsewhere).
  Tests must seed cases with a real ObjectId `_id` to hit the success
  branch.
- The submit endpoint creates 0 or more system_config / email side-effects.
  We mock the email service to keep tests fast and avoid external IO.
- `release/{access_token}` calls `get_shared_database()` directly
  (NOT injected) — to hit it the test patches
  `src.cases.public_routes.get_shared_database` to return the test db.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import jwt as pyjwt
import pytest
from bson import ObjectId
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.config import ALGORITHM, JWT_SECRET
from tests.factories import make_case

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_public_routes_db(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase, app):
    """Override every db-resolution path used by public_routes:

    - FastAPI `Depends(get_db)`: covers /my-requests, /{id}, /stats/summary
      (via app.dependency_overrides on public_routes.get_db AND
      core.database.get_database_from_request — the latter because
      `/my-requests` uses `Depends(get_database_from_request)` directly).
    - Direct `await get_db(http_request)` inside /submit and /track:
      not part of FastAPI DI — monkeypatch the underlying
      `get_database_from_request` symbol on public_routes' module so
      the imported name is rebound to our test-db returner.
    - `get_shared_database()` (called directly inside /release/{token}):
      monkeypatched on the public_routes module symbol.
    """
    from src.cases import public_routes
    from src.core import database as core_db

    async def _override_get_db_from_request(request=None):
        return db

    async def _override_get_db():
        return db

    # FastAPI DI path
    app.dependency_overrides[public_routes.get_db] = _override_get_db
    app.dependency_overrides[core_db.get_database_from_request] = _override_get_db_from_request

    # Direct-call paths used inside /submit and /track
    monkeypatch.setattr(public_routes, "get_database_from_request", _override_get_db_from_request)
    monkeypatch.setattr(public_routes, "get_shared_database", lambda: db)

    yield db

    app.dependency_overrides.pop(public_routes.get_db, None)
    app.dependency_overrides.pop(core_db.get_database_from_request, None)


def _issue_public_jwt(user_id: str, email: str) -> str:
    """Mint a JWT matching what magic_link_service.issue_token produces.

    `get_current_user_public` requires sub + email + user_type == "public".
    """
    exp = datetime.utcnow() + timedelta(hours=1)
    payload = {
        "sub": user_id,
        "email": email,
        "user_type": "public",
        "realm": "public",
        "exp": exp,
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)


async def _public_client(app, user_id: str, email: str) -> AsyncClient:
    """AsyncClient pre-authenticated with a public-user JWT."""
    token = _issue_public_jwt(user_id, email)
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {token}"},
    )


# ---------------------------------------------------------------------------
# GET /health (no auth)
# ---------------------------------------------------------------------------


class TestHealthCheck:
    """`GET /api/v1/cases/public/health` reachability (B18 fix, 2026-05-12).

    Before the B18 fix, this URL was shadowed by `GET /{request_id}`
    declared earlier in `cases/public_routes.py`. FastAPI matches paths
    in registration order; the catch-all caught the single-segment
    `/health` and required a JWT. Fix: declared `/health` BEFORE
    `/{request_id}` so the static path matches first.
    """

    async def test_health_is_reachable_without_auth(self, app) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.get("/api/v1/cases/public/health")
        assert r.status_code == 200, r.text
        assert r.json() == {"status": "healthy", "service": "public_foi_requests"}


# ---------------------------------------------------------------------------
# POST /submit (anonymous)
# ---------------------------------------------------------------------------


class TestSubmitPublicRequest:
    async def test_submit_creates_case_with_tracking_number(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_public_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Stub out email side-effect — submit_public_request swallows
        # exceptions from the welcome-email path, but stubbing keeps it
        # fast and silent.
        from src.utils import welcome_email_service as wmod

        class _Stub:
            def __init__(self, *a, **kw):
                pass

            def send_public_request_confirmation(self, **kw):
                return True

        monkeypatch.setattr(wmod, "WelcomeEmailService", _Stub)

        payload = {
            "title": "Budget records request",
            "description": "Please provide Q1 budget docs.",
            "category": "Financial",
            "requester": {
                "name": "Jane Citizen",
                "email": "jane@example.com",
                "phone": "555-1234",
                "organization": "Civic Org",
            },
        }

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.post("/api/v1/cases/public/submit", json=payload)

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["tracking_number"].startswith(f"FOI-{datetime.utcnow().year}-")
        assert "case_id" in body
        assert "due_date" in body

        stored = await db.cases.find_one({"tracking_number": body["tracking_number"]})
        assert stored is not None
        assert stored["title"] == "Budget records request"
        assert stored["status"] == "new"
        assert stored["audit_log"][0]["action"] == "case_created"

    async def test_submit_missing_required_fields_returns_422(
        self,
        app,
        patch_public_routes_db,
    ) -> None:
        """Phase 4 Batch 4.4 (audit B7) fixed the deprecated
        `HTTP_422_UNPROCESSABLE_ENTITY` constant in
        `src/utils/error_handler.py`; the per-test filterwarnings
        suppressor is no longer required."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.post(
                "/api/v1/cases/public/submit",
                json={"title": "x"},
            )
        assert r.status_code == 422

    async def test_submit_increments_sequence_per_year(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_public_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from src.utils import welcome_email_service as wmod

        class _Stub:
            def __init__(self, *a, **kw):
                pass

            def send_public_request_confirmation(self, **kw):
                return True

        monkeypatch.setattr(wmod, "WelcomeEmailService", _Stub)

        payload = {
            "title": "Seq test",
            "description": "x",
            "requester": {"name": "A", "email": "a@e.com"},
        }
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r1 = await c.post("/api/v1/cases/public/submit", json=payload)
            r2 = await c.post("/api/v1/cases/public/submit", json=payload)

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["tracking_number"] != r2.json()["tracking_number"]


# ---------------------------------------------------------------------------
# GET /track/{tracking_number} (anonymous)
# ---------------------------------------------------------------------------


class TestTrackPublicRequest:
    async def test_track_returns_status_for_existing_case(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_public_routes_db,
    ) -> None:
        tracking = "FOI-2026-0001-AB"
        doc = make_case(
            tracking_number=tracking,
            status="in_progress",
            comments=[
                {
                    "id": "c1",
                    "author_id": "u1",
                    "author_name": "Officer",
                    "text": "Public update",
                    "type": "public",
                    "created_at": datetime.utcnow(),
                },
                {
                    "id": "c2",
                    "author_id": "u1",
                    "author_name": "Officer",
                    "text": "Internal note",
                    "type": "internal",
                    "created_at": datetime.utcnow(),
                },
            ],
        )
        await db.cases.insert_one(doc)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.get(f"/api/v1/cases/public/track/{tracking}")

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tracking_number"] == tracking
        assert body["status"] == "in_progress"
        assert len(body["comments"]) == 1
        assert body["comments"][0]["type"] == "public"

    async def test_track_missing_tracking_number_returns_404(
        self,
        app,
        patch_public_routes_db,
    ) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.get("/api/v1/cases/public/track/FOI-NOPE-9999")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /my-requests (auth: public user JWT)
# ---------------------------------------------------------------------------


class TestGetMyRequests:
    async def test_my_requests_returns_user_cases_only(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_public_routes_db,
    ) -> None:
        await db.cases.insert_one(
            make_case(
                requester={
                    "name": "Me",
                    "email": "me@example.com",
                    "phone": None,
                    "organization": None,
                },
                title="Mine 1",
            )
        )
        await db.cases.insert_one(
            make_case(
                requester={
                    "name": "Me",
                    "email": "me@example.com",
                    "phone": None,
                    "organization": None,
                },
                title="Mine 2",
            )
        )
        await db.cases.insert_one(
            make_case(
                requester={
                    "name": "Other",
                    "email": "other@example.com",
                    "phone": None,
                    "organization": None,
                },
                title="Theirs",
            )
        )

        client = await _public_client(app, "user-1", "me@example.com")
        try:
            r = await client.get("/api/v1/cases/public/my-requests")
        finally:
            await client.aclose()

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 2
        titles = {c["title"] for c in body["requests"]}
        assert titles == {"Mine 1", "Mine 2"}

    async def test_my_requests_empty_when_user_has_none(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_public_routes_db,
    ) -> None:
        client = await _public_client(app, "user-empty", "empty@example.com")
        try:
            r = await client.get("/api/v1/cases/public/my-requests")
        finally:
            await client.aclose()
        assert r.status_code == 200
        assert r.json()["total"] == 0

    async def test_my_requests_unauthenticated_returns_401(
        self,
        app,
        patch_public_routes_db,
    ) -> None:
        """HTTPBearer with no header returns 401 'Not authenticated'
        when auto_error=True (the default)."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.get("/api/v1/cases/public/my-requests")
        assert r.status_code == 401

    async def test_my_requests_invalid_jwt_returns_401(
        self,
        app,
        patch_public_routes_db,
    ) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": "Bearer garbage"},
        ) as c:
            r = await c.get("/api/v1/cases/public/my-requests")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /{request_id} (auth: public user JWT)
# ---------------------------------------------------------------------------


class TestGetRequestDetails:
    """As of c07b458, public_routes looks up by app-level UUID
    (case["id"]) — not the Mongo ObjectId — so the URL path takes the
    UUID. Previously the route accepted an ObjectId and would 400 on
    invalid format; now any string is valid until the lookup and
    misses return 404."""

    async def test_get_details_happy_path(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_public_routes_db,
    ) -> None:
        case = make_case(
            requester={
                "name": "Me",
                "email": "me@example.com",
                "phone": None,
                "organization": None,
            },
            audit_log=[
                {
                    "action": "case_created",
                    "user_id": "system",
                    "username": "Portal",
                    "timestamp": datetime.utcnow(),
                    "details": {},
                },
                {
                    "action": "status_changed",
                    "user_id": "u1",
                    "username": "U1",
                    "timestamp": datetime.utcnow(),
                    "details": {"old": "new", "new": "in_progress"},
                },
                {
                    "action": "internal_thing",
                    "user_id": "u1",
                    "username": "U1",
                    "timestamp": datetime.utcnow(),
                    "details": {},
                },
            ],
        )
        await db.cases.insert_one(case)

        await db.documents.insert_one(
            {
                "_id": ObjectId(),
                "id": str(uuid.uuid4()),
                "case_id": case["id"],
                "filename": "x.pdf",
                "file_type": "pdf",
                "file_size": 100,
                "created_at": datetime.utcnow(),
                "status": "uploaded",
            }
        )

        client = await _public_client(app, "user-1", "me@example.com")
        try:
            r = await client.get(f"/api/v1/cases/public/{case['id']}")
        finally:
            await client.aclose()

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["id"] == case["id"]
        assert body["document_count"] == 1
        timeline_actions = {e["event"] for e in body["timeline"]}
        assert "case_created" in timeline_actions
        assert "status_changed" in timeline_actions
        assert "internal_thing" not in timeline_actions

    async def test_get_details_unknown_id_returns_404(
        self,
        app,
        patch_public_routes_db,
    ) -> None:
        """The route used to return 400 for malformed ObjectIds; now it
        accepts any string and returns 404 when no case matches that id
        for the authenticated requester."""
        client = await _public_client(app, "u", "me@example.com")
        try:
            r = await client.get("/api/v1/cases/public/not-a-valid-uuid")
        finally:
            await client.aclose()
        assert r.status_code == 404
        assert "not found" in r.json()["error"]["message"].lower()

    async def test_get_details_other_users_case_returns_404(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_public_routes_db,
    ) -> None:
        """SECURITY: even with a valid UUID, a different requester gets
        404 because the lookup filters on requester.email too."""
        case = make_case(
            requester={
                "name": "Owner",
                "email": "owner@example.com",
                "phone": None,
                "organization": None,
            },
        )
        await db.cases.insert_one(case)

        client = await _public_client(app, "u", "intruder@example.com")
        try:
            r = await client.get(f"/api/v1/cases/public/{case['id']}")
        finally:
            await client.aclose()
        assert r.status_code == 404

    async def test_get_details_tolerates_string_dates(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_public_routes_db,
    ) -> None:
        """Some pre-migration cases have date fields stored as ISO
        strings rather than BSON Date (created_at/due_date in
        particular). The _iso() helper in public_routes must handle
        both shapes without raising. Pre-fix, this would have raised
        AttributeError: 'str' object has no attribute 'isoformat'."""
        case = make_case(
            requester={
                "name": "Me",
                "email": "me@example.com",
                "phone": None,
                "organization": None,
            },
        )
        # Deliberately write date fields as ISO strings (the pre-fix
        # case-create wrote due_date this way).
        case["due_date"] = "2026-12-31T23:59:59"
        case["created_at"] = "2026-01-01T00:00:00"
        case["updated_at"] = datetime.utcnow()  # mixed — also legitimate
        await db.cases.insert_one(case)

        client = await _public_client(app, "u", "me@example.com")
        try:
            r = await client.get(f"/api/v1/cases/public/{case['id']}")
        finally:
            await client.aclose()
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["due_date"] == "2026-12-31T23:59:59"
        assert body["created_at"] == "2026-01-01T00:00:00"
        # datetime field still gets serialised to ISO
        assert isinstance(body["updated_at"], str)
        assert body["updated_at"].startswith("2026-")

    async def test_get_details_includes_released_package_metadata(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_public_routes_db,
    ) -> None:
        case = make_case(
            requester={
                "name": "Me",
                "email": "me@example.com",
                "phone": None,
                "organization": None,
            },
        )
        await db.cases.insert_one(case)

        await db.release_packages.insert_one(
            {
                "id": str(uuid.uuid4()),
                "case_id": case["id"],
                "status": "released",
                "filename": "rel.zip",
                "size_bytes": 1000,
                "document_count": 2,
                "download_count": 0,
                "max_downloads": 5,
                "expires_at": datetime.utcnow() + timedelta(days=7),
                "access_token": "tok-abc",
                "released_at": datetime.utcnow(),
            }
        )

        client = await _public_client(app, "u", "me@example.com")
        try:
            r = await client.get(f"/api/v1/cases/public/{case['id']}")
        finally:
            await client.aclose()

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["release_status"] == "available"
        assert len(body["release_packages"]) == 1

    async def test_get_details_excludes_expired_released_packages(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_public_routes_db,
    ) -> None:
        case = make_case(
            requester={
                "name": "Me",
                "email": "me@example.com",
                "phone": None,
                "organization": None,
            },
        )
        await db.cases.insert_one(case)

        await db.release_packages.insert_one(
            {
                "id": str(uuid.uuid4()),
                "case_id": case["id"],
                "status": "released",
                "filename": "old.zip",
                "expires_at": datetime.utcnow() - timedelta(days=1),
                "max_downloads": 10,
                "download_count": 0,
                "released_at": datetime.utcnow(),
            }
        )

        client = await _public_client(app, "u", "me@example.com")
        try:
            r = await client.get(f"/api/v1/cases/public/{case['id']}")
        finally:
            await client.aclose()
        assert r.status_code == 200
        assert r.json()["release_packages"] == []

    async def test_get_details_excludes_exhausted_packages(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_public_routes_db,
    ) -> None:
        case = make_case(
            requester={
                "name": "Me",
                "email": "me@example.com",
                "phone": None,
                "organization": None,
            },
        )
        await db.cases.insert_one(case)

        await db.release_packages.insert_one(
            {
                "id": str(uuid.uuid4()),
                "case_id": case["id"],
                "status": "released",
                "filename": "spent.zip",
                "expires_at": datetime.utcnow() + timedelta(days=30),
                "max_downloads": 3,
                "download_count": 3,
                "released_at": datetime.utcnow(),
            }
        )

        client = await _public_client(app, "u", "me@example.com")
        try:
            r = await client.get(f"/api/v1/cases/public/{case['id']}")
        finally:
            await client.aclose()
        assert r.status_code == 200
        assert r.json()["release_packages"] == []

    async def test_get_details_release_package_string_expires_at(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_public_routes_db,
    ) -> None:
        """Release packages with expires_at stored as ISO string should
        still be filtered correctly by the expiry check. Mixed shapes
        like this exist on disk pre-migration."""
        case = make_case(
            requester={
                "name": "Me",
                "email": "me@example.com",
                "phone": None,
                "organization": None,
            },
        )
        await db.cases.insert_one(case)
        # String-shaped expires_at in the past — should be excluded.
        past_iso = (datetime.utcnow() - timedelta(days=2)).isoformat()
        await db.release_packages.insert_one(
            {
                "id": str(uuid.uuid4()),
                "case_id": case["id"],
                "status": "released",
                "filename": "expired.zip",
                "expires_at": past_iso,
                "max_downloads": 10,
                "download_count": 0,
                "released_at": datetime.utcnow(),
            }
        )

        client = await _public_client(app, "u", "me@example.com")
        try:
            r = await client.get(f"/api/v1/cases/public/{case['id']}")
        finally:
            await client.aclose()
        assert r.status_code == 200
        assert r.json()["release_packages"] == []


# ---------------------------------------------------------------------------
# GET /stats/summary (auth: public user JWT)
# ---------------------------------------------------------------------------


class TestGetRequestSummary:
    async def test_summary_aggregates_by_status(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_public_routes_db,
    ) -> None:
        for status in ("open", "open", "in_progress", "completed", "closed", "closed"):
            await db.cases.insert_one(
                make_case(
                    status=status,
                    requester={
                        "name": "Me",
                        "email": "me@example.com",
                        "phone": None,
                        "organization": None,
                    },
                )
            )

        client = await _public_client(app, "u", "me@example.com")
        try:
            r = await client.get("/api/v1/cases/public/stats/summary")
        finally:
            await client.aclose()
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["open"] == 2
        assert body["in_progress"] == 1
        assert body["completed"] == 1
        assert body["closed"] == 2
        assert body["total"] == 6

    async def test_summary_empty_when_no_user_cases(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_public_routes_db,
    ) -> None:
        client = await _public_client(app, "u", "nobody@example.com")
        try:
            r = await client.get("/api/v1/cases/public/stats/summary")
        finally:
            await client.aclose()
        assert r.status_code == 200
        body = r.json()
        assert body == {"open": 0, "in_progress": 0, "completed": 0, "closed": 0, "total": 0}

    async def test_summary_unauthenticated_returns_401(
        self,
        app,
        patch_public_routes_db,
    ) -> None:
        """HTTPBearer auto_error=True default → 401."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.get("/api/v1/cases/public/stats/summary")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /release/{access_token} (anonymous, token-gated)
# ---------------------------------------------------------------------------


class TestDownloadReleasePackage:
    async def test_release_unknown_token_returns_404(
        self,
        app,
        patch_public_routes_db,
    ) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.get("/api/v1/cases/public/release/nonexistent-tok")
        assert r.status_code == 404

    async def test_release_revoked_status_returns_410(
        self,
        app,
        patch_public_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from src.cases import public_routes
        from src.cases.release_package_models import ReleasePackageStatus

        class _Pkg:
            id = "p1"
            status = ReleasePackageStatus.REVOKED
            expires_at = None
            max_downloads = None
            download_count = 0

        async def _fake_get(token, db):
            return _Pkg()

        monkeypatch.setattr(
            public_routes.release_package_service,
            "get_release_package_by_token",
            _fake_get,
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.get("/api/v1/cases/public/release/tok-revoked")
        assert r.status_code == 410
        assert "revoked" in r.json()["error"]["message"].lower()

    async def test_release_expired_status_returns_410(
        self,
        app,
        patch_public_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from src.cases import public_routes
        from src.cases.release_package_models import ReleasePackageStatus

        class _Pkg:
            id = "p2"
            status = ReleasePackageStatus.EXPIRED
            expires_at = None
            max_downloads = None
            download_count = 0

        async def _fake_get(token, db):
            return _Pkg()

        monkeypatch.setattr(
            public_routes.release_package_service,
            "get_release_package_by_token",
            _fake_get,
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.get("/api/v1/cases/public/release/tok-exp")
        assert r.status_code == 410

    async def test_release_draft_status_returns_400(
        self,
        app,
        patch_public_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from src.cases import public_routes
        from src.cases.release_package_models import ReleasePackageStatus

        class _Pkg:
            id = "p3"
            status = ReleasePackageStatus.DRAFT
            expires_at = None
            max_downloads = None
            download_count = 0

        async def _fake_get(token, db):
            return _Pkg()

        monkeypatch.setattr(
            public_routes.release_package_service,
            "get_release_package_by_token",
            _fake_get,
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.get("/api/v1/cases/public/release/tok-draft")
        assert r.status_code == 400

    async def test_release_expired_via_timestamp_updates_status(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_public_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Pin the expires_at-runtime-check branch (lines 481-487)."""
        from src.cases import public_routes
        from src.cases.release_package_models import ReleasePackageStatus

        class _Pkg:
            id = "pkg-time-exp"
            status = ReleasePackageStatus.RELEASED
            expires_at = datetime.utcnow() - timedelta(hours=1)
            max_downloads = None
            download_count = 0

        async def _fake_get(token, db):
            return _Pkg()

        monkeypatch.setattr(
            public_routes.release_package_service,
            "get_release_package_by_token",
            _fake_get,
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.get("/api/v1/cases/public/release/tok-old")
        assert r.status_code == 410
        assert "expired" in r.json()["error"]["message"].lower()

    async def test_release_download_limit_reached_returns_410(
        self,
        app,
        patch_public_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from src.cases import public_routes
        from src.cases.release_package_models import ReleasePackageStatus

        class _Pkg:
            id = "pkg-spent"
            status = ReleasePackageStatus.RELEASED
            expires_at = None
            max_downloads = 3
            download_count = 3

        async def _fake_get(token, db):
            return _Pkg()

        monkeypatch.setattr(
            public_routes.release_package_service,
            "get_release_package_by_token",
            _fake_get,
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.get("/api/v1/cases/public/release/tok-spent")
        assert r.status_code == 410
        assert "limit" in r.json()["error"]["message"].lower()

    async def test_release_successful_download(
        self,
        app,
        patch_public_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from src.cases import public_routes
        from src.cases.release_package_models import ReleasePackageStatus

        class _Pkg:
            id = "pkg-good"
            status = ReleasePackageStatus.RELEASED
            expires_at = datetime.utcnow() + timedelta(days=1)
            max_downloads = None
            download_count = 0

        async def _fake_get(token, db):
            return _Pkg()

        async def _fake_download(pkg, db, ip_address=None, user_agent=None):
            return (b"ZIPCONTENT", "rel.zip")

        monkeypatch.setattr(
            public_routes.release_package_service,
            "get_release_package_by_token",
            _fake_get,
        )
        monkeypatch.setattr(
            public_routes.release_package_service,
            "download_public_package",
            _fake_download,
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.get("/api/v1/cases/public/release/tok-ok")
        assert r.status_code == 200
        assert r.content == b"ZIPCONTENT"
        assert r.headers["content-type"] == "application/zip"
        assert 'filename="rel.zip"' in r.headers["content-disposition"]

    async def test_release_value_error_during_download_returns_410(
        self,
        app,
        patch_public_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Pin ValueError -> 410 branch."""
        from src.cases import public_routes
        from src.cases.release_package_models import ReleasePackageStatus

        class _Pkg:
            id = "p4"
            status = ReleasePackageStatus.RELEASED
            expires_at = None
            max_downloads = None
            download_count = 0

        async def _fake_get(token, db):
            return _Pkg()

        async def _fake_download(pkg, db, **kw):
            raise ValueError("package no longer accessible")

        monkeypatch.setattr(
            public_routes.release_package_service,
            "get_release_package_by_token",
            _fake_get,
        )
        monkeypatch.setattr(
            public_routes.release_package_service,
            "download_public_package",
            _fake_download,
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.get("/api/v1/cases/public/release/tok-err")
        assert r.status_code == 410

    async def test_release_unexpected_error_returns_500(
        self,
        app,
        patch_public_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Pin generic-Exception -> 500 branch."""
        from src.cases import public_routes
        from src.cases.release_package_models import ReleasePackageStatus

        class _Pkg:
            id = "p5"
            status = ReleasePackageStatus.RELEASED
            expires_at = None
            max_downloads = None
            download_count = 0

        async def _fake_get(token, db):
            return _Pkg()

        async def _fake_download(pkg, db, **kw):
            raise RuntimeError("storage offline")

        monkeypatch.setattr(
            public_routes.release_package_service,
            "get_release_package_by_token",
            _fake_get,
        )
        monkeypatch.setattr(
            public_routes.release_package_service,
            "download_public_package",
            _fake_download,
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.get("/api/v1/cases/public/release/tok-boom")
        assert r.status_code == 500
