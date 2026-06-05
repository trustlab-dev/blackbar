"""Integration tests for `src.admin.config_routes` (system config CRUD).

Phase 2.7. Target >=80% line coverage on `src/admin/config_routes.py`.

Endpoint surface (3 endpoints, mounted at /api/v1/admin/config/...):
    GET  /          (any authed user)         -> SystemConfiguration
    PUT  /          (admin/owner role)         -> SystemConfiguration
    GET  /public    (NO auth required)         -> PublicConfiguration

Reality pins:
- The module captures `config_collection = db.system_config` at import
  time (line 23). Tests MUST monkeypatch `src.admin.config_routes.config_collection`
  to redirect to the per-test motor collection. Same class as B16/B30/B37/B46.
- `GET /` uses `check_role` implicitly via `get_current_user` — any authed
  user can read the config. Only `PUT /` is admin/owner-gated.
- `GET /public` is allowlisted in `core/auth_middleware.py` (exact path)
  — no JWT needed. Returns only non-sensitive fields.
- `update_system_config` upserts; first call inserts defaults if no doc
  exists.
- `default_due_days` override branch: pack-loader `get_pack_timelines()`
  is called inside the GET handler and can override the stored
  `default_due_days` to `default_response_days` from the active pack —
  but only when stored value is the literal default `30` or absent.
- `PUT /` with empty payload (all None) returns 400 "No updates provided".
- `PUT /` strips MongoDB `_id` from response.
- `PUT /` writes `updated_at` (datetime) and `updated_by` (user id).
- `GET /public` falls back to defaults on exception (try/except wraps
  the whole body).
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorDatabase

# ---------------------------------------------------------------------------
# Anonymous client (no JWT) — uses httpx.AsyncClient on the same event
# loop as the db fixture; avoids the TestClient->different-loop teardown
# crash documented in audit I1.
# ---------------------------------------------------------------------------


def _anon_client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_routes_db(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase):
    """Point `src.admin.config_routes.config_collection` at the per-test
    motor collection. Also patches `src.dependencies.users` so that
    `get_current_user` can look up the authenticated user."""
    import src.admin.config_routes as _routes_mod
    import src.dependencies as deps_mod

    monkeypatch.setattr(_routes_mod, "config_collection", db.system_config)
    monkeypatch.setattr(deps_mod, "users", db.users)
    return db


# ---------------------------------------------------------------------------
# GET /api/v1/admin/config/
# ---------------------------------------------------------------------------


class TestGetConfiguration:
    async def test_user_can_read_config(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Any authed user (role=user) can read system config."""
        client: AsyncClient = await authed_client_factory(role="user")
        r = await client.get("/api/v1/admin/config/")
        assert r.status_code == 200, r.text
        body = r.json()
        # Default config inserted on first read
        assert body["org_name"] == "Freedom of Information Office"
        assert body["primary_color"] == "#0366d6"
        # _id stripped from response
        assert "_id" not in body

    async def test_admin_can_read_config(self, authed_client_factory, patch_routes_db) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/admin/config/")
        assert r.status_code == 200

    async def test_get_creates_default_when_none_exists(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """First-call lazy-create branch: `get_system_config` inserts a
        SystemConfiguration() default doc when find_one returns None."""
        # DB is fresh (per-test); no doc exists
        assert await db.system_config.find_one({}) is None

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/admin/config/")
        assert r.status_code == 200

        # The default was persisted
        doc = await db.system_config.find_one({})
        assert doc is not None
        assert doc["org_name"] == "Freedom of Information Office"

    async def test_unauthenticated_request_rejected(self, app) -> None:
        async with _anon_client(app) as c:
            r = await c.get("/api/v1/admin/config/")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# PUT /api/v1/admin/config/
# ---------------------------------------------------------------------------


class TestUpdateConfiguration:
    async def test_admin_can_update_org_name(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.put(
            "/api/v1/admin/config/",
            json={"org_name": "Acme FOI"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["org_name"] == "Acme FOI"
        # Persistence verification
        doc = await db.system_config.find_one({})
        assert doc["org_name"] == "Acme FOI"

    async def test_admin_can_update_multiple_fields(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.put(
            "/api/v1/admin/config/",
            json={
                "org_name": "Multi FOI",
                "primary_color": "#123456",
                "default_due_days": 45,
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["org_name"] == "Multi FOI"
        assert body["primary_color"] == "#123456"
        assert body["default_due_days"] == 45

    async def test_update_writes_updated_by_and_updated_at(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin", email="auditor@example.com")
        r = await client.put(
            "/api/v1/admin/config/",
            json={"org_name": "Audited"},
        )
        assert r.status_code == 200
        doc = await db.system_config.find_one({})
        assert "updated_at" in doc
        assert "updated_by" in doc
        # updated_by is the user's id (not email)
        assert doc["updated_by"]

    async def test_update_empty_payload_returns_400(
        self, authed_client_factory, patch_routes_db
    ) -> None:
        """All-None payload: `{k: v for ... if v is not None}` yields {}.
        Handler raises HTTPException(400, "No updates provided")."""
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.put("/api/v1/admin/config/", json={})
        assert r.status_code == 400
        body = r.json()
        # Global error envelope: error.message contains the detail
        assert "No updates provided" in body.get("error", {}).get("message", "")

    async def test_update_invalid_color_returns_422(
        self, authed_client_factory, patch_routes_db
    ) -> None:
        """Phase 4 Batch 4.4 (audit B7) fixed the deprecated
        `HTTP_422_UNPROCESSABLE_ENTITY` constant in
        `src/utils/error_handler.py`; the per-test filterwarnings
        suppressor is no longer required."""
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.put(
            "/api/v1/admin/config/",
            json={"primary_color": "not-a-hex"},
        )
        assert r.status_code == 422

    async def test_update_invalid_due_days_returns_422(
        self, authed_client_factory, patch_routes_db
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.put(
            "/api/v1/admin/config/",
            json={"default_due_days": 999},
        )
        assert r.status_code == 422

    async def test_non_admin_user_forbidden(self, authed_client_factory, patch_routes_db) -> None:
        """check_role(["admin", "owner"]) rejects regular users."""
        client: AsyncClient = await authed_client_factory(role="user")
        r = await client.put(
            "/api/v1/admin/config/",
            json={"org_name": "Hacker"},
        )
        assert r.status_code == 403

    async def test_analyst_forbidden(self, authed_client_factory, patch_routes_db) -> None:
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.put(
            "/api/v1/admin/config/",
            json={"org_name": "Analyst Edit"},
        )
        assert r.status_code == 403

    async def test_unauthenticated_request_rejected(self, app) -> None:
        async with _anon_client(app) as c:
            r = await c.put("/api/v1/admin/config/", json={"org_name": "X"})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v1/admin/config/public
# ---------------------------------------------------------------------------


class TestGetPublicConfiguration:
    async def test_public_endpoint_returns_default_without_auth(self, app, patch_routes_db) -> None:
        """Audit Section 11 / B19-class: this path is in the
        AuthMiddleware allowlist and serves anonymous traffic."""
        async with _anon_client(app) as c:
            r = await c.get("/api/v1/admin/config/public")
        assert r.status_code == 200, r.text
        body = r.json()
        # Only public-safe fields present
        assert body["org_name"] == "Freedom of Information Office"
        assert body["primary_color"] == "#0366d6"
        assert "enable_public_requests" in body
        assert "request_categories" in body
        # Sensitive admin fields absent from the response shape
        assert "session_timeout_minutes" not in body
        assert "password_min_length" not in body
        assert "default_due_days" not in body
        assert "updated_by" not in body

    async def test_public_reflects_stored_overrides(
        self,
        db: AsyncIOMotorDatabase,
        app,
        patch_routes_db,
    ) -> None:
        """Insert a custom config, then assert /public surfaces it."""
        await db.system_config.insert_one(
            {
                "org_name": "Specific City FOI",
                "primary_color": "#abcdef",
                "contact_email": "specific@example.com",
                "enable_public_requests": False,
                "enable_request_tracking": True,
                "enable_public_upload": False,
                "request_categories": ["Cat A"],
            }
        )
        async with _anon_client(app) as c:
            r = await c.get("/api/v1/admin/config/public")
        assert r.status_code == 200
        body = r.json()
        assert body["org_name"] == "Specific City FOI"
        assert body["primary_color"] == "#abcdef"
        assert body["enable_public_requests"] is False
        assert body["request_categories"] == ["Cat A"]

    async def test_public_fallback_branch_returns_defaults_on_config_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Phase 4 Batch 4.4 (audit B47): the except-branch fallback in
        `get_public_configuration` now constructs a complete
        `PublicConfiguration` (supplying `org_logo_url=None`,
        `contact_email`, and `footer_text=None`). Previously the
        fallback itself raised `pydantic.ValidationError` because those
        required fields were missing.

        Test flipped from `pytest.raises(ValidationError)` to assert the
        handler returns the documented defaults when `get_system_config`
        throws."""
        import src.admin.config_routes as routes_mod
        from src.admin.config_models import PublicConfiguration

        async def _boom() -> dict:
            raise RuntimeError("simulated DB outage")

        monkeypatch.setattr(routes_mod, "get_system_config", _boom)

        result = await routes_mod.get_public_configuration(request=None)
        assert isinstance(result, PublicConfiguration)
        assert result.org_name == "Freedom of Information Office"
        assert result.primary_color == "#0366d6"
        assert result.org_logo_url is None
        assert result.footer_text is None
        assert result.contact_email == "foi@example.com"
        assert result.enable_public_requests is True
        assert result.request_categories[0] == "General Records"

    async def test_get_configuration_500_on_internal_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Pins the authed GET / wrapper try/except: any exception in
        `get_system_config` is rethrown as HTTPException(500)."""
        import src.admin.config_routes as routes_mod

        async def _boom() -> dict:
            raise RuntimeError("simulated outage")

        monkeypatch.setattr(routes_mod, "get_system_config", _boom)

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/admin/config/")
        assert r.status_code == 500

    async def test_update_500_on_internal_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """The PUT / try/except wraps the entire body; an exception
        inside `update_system_config` becomes HTTPException(500)."""
        import src.admin.config_routes as routes_mod

        async def _boom(updates: dict, user_id: str) -> dict:
            raise RuntimeError("simulated write failure")

        monkeypatch.setattr(routes_mod, "update_system_config", _boom)

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.put("/api/v1/admin/config/", json={"org_name": "X"})
        assert r.status_code == 500
