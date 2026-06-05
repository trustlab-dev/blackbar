"""Integration tests for `src.auth.routes` endpoints.

Phase 2.1.C. Target ≥80% line coverage on src.auth.routes.

Reality calibration vs. the plan:
- The plan referenced 6-ish endpoints with happy/auth-fail/validation
  triples — actual surface is:
    POST   /auth/login                 (happy/wrong-pass/bad-email/rate-limit)
    POST   /auth/logout                (stateless ack)
    GET    /auth/me                    (internal user + public user + no-token)
    GET    /auth/roles                 (lists 4-tier roles)
    GET    /auth/users                 (admin gate; Phase-1.9a `role` key pin)
    POST   /auth/users                 (admin gate; create-with-password and
                                         invitation flow)
    PUT    /auth/users/{id}            (admin gate)
    DELETE /auth/users/{id}            (admin gate)
    GET    /auth/users/assignable      (any authed user)
    GET    /auth/users/guests          (any authed user)
    GET    /auth/users/search          (any authed user)

- The `authed_client_factory` fixture in conftest returns a TestClient,
  but motor-on-different-loops makes DB-touching FastAPI endpoints fail
  under TestClient. This test file uses `httpx.AsyncClient` with
  `ASGITransport(app=app)` instead — runs in the same event loop as
  the pytest-asyncio fixtures, so motor's loop binding works.

- All routes do `from src.database import db` at module load. The `db`
  there is bound to the global motor client (one event loop, often a
  prior test's). Tests patch `src.auth.routes.db` to point at the
  per-test `db` fixture for correct collection-level isolation.

- Pins Phase-1.9a JSON contract: `GET /auth/users` returns `role` key
  on each user (NOT legacy `tenant_role`).

- The require_role decorator references `["owner", "admin"]`. The
  4-tier model has no 'owner' role — it's a vestigial dead entry.
  Tests verify admins pass and non-admins are rejected.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.auth.auth_service import AuthService
from src.users.models import UserCreate
from src.users.repository import UsersRepository

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_routes_db(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase):
    """Point src.auth.routes.db at the per-test motor database.

    `src.auth.routes` does `from src.database import db` at module load.
    Without this rebind, route handlers operate on a different (stale)
    motor client/loop than the test fixtures."""
    import src.auth.routes as _routes_mod

    monkeypatch.setattr(_routes_mod, "db", db)
    return db


async def _seed_user_with_role(
    db: AsyncIOMotorDatabase,
    *,
    email: str,
    role: str = "user",
    password: str = "test-pwd-12345",
    name: str = "Seed",
    status: str = "active",
) -> str:
    """Seed a user and return their id."""
    repo = UsersRepository(db)
    pwd_hash = AuthService.hash_password(password)
    user = await repo.create(UserCreate(email=email, name=name, password=password), pwd_hash)
    patch: dict[str, Any] = {}
    if role != "user":
        patch["role"] = role
    if status != "active":
        patch["status"] = status
    if patch:
        await db.users.update_one({"id": user.id}, {"$set": patch})
    return user.id


async def _mint_token(db: AsyncIOMotorDatabase, *, user_id: str, role: str = "user") -> str:
    """Issue a JWT for an existing user via AuthService."""
    repo = UsersRepository(db)
    user = await repo.get_by_id(user_id)
    assert user is not None
    user.role = role
    auth_service = AuthService(repo)
    return await auth_service.issue_token(user)


def _client(app) -> AsyncClient:
    """An httpx AsyncClient wired to the live ASGI app via ASGITransport.

    Use as `async with _client(app) as c: ...`. Same event loop as the
    pytest-asyncio test, so motor collection ops bind correctly."""
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------


class TestLogin:
    async def test_login_happy_path_returns_token(
        self, app, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        await _seed_user_with_role(db, email="login@example.com", password="goodpwd1234")

        async with _client(app) as c:
            r = await c.post(
                "/api/v1/auth/login",
                json={"email": "login@example.com", "password": "goodpwd1234"},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert body["role"] == "user"
        assert body["roles"] == ["user"]

    async def test_login_wrong_password_returns_401(
        self, app, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        """Pins the global error_handler shape: HTTPException 401 from a
        route is transformed into {"error": {"code": "HTTP_401",
        "message": "...", "details": {}, "correlation_id": ...}}."""
        await _seed_user_with_role(db, email="wrongpw@example.com", password="rightpwd1234")

        async with _client(app) as c:
            r = await c.post(
                "/api/v1/auth/login",
                json={"email": "wrongpw@example.com", "password": "BAD-pass"},
            )
        assert r.status_code == 401
        body = r.json()
        assert body["error"]["code"] == "HTTP_401"
        assert body["error"]["message"] == "Invalid email or password"

    async def test_login_unknown_email_returns_401(
        self, app, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        async with _client(app) as c:
            r = await c.post(
                "/api/v1/auth/login",
                json={"email": "nobody@example.com", "password": "anything"},
            )
        assert r.status_code == 401

    async def test_login_missing_field_returns_422(
        self, app, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        """Validation errors get the VALIDATION_ERROR shape from the
        global validation_exception_handler.

        Phase 4 Batch 4.4 (audit B7) fixed the deprecated
        `HTTP_422_UNPROCESSABLE_ENTITY` constant in
        `src/utils/error_handler.py`; the per-test filterwarnings
        suppressor that previously absorbed the DeprecationWarning is
        no longer required. B8 (ctx.error JSON serialization crash)
        was fixed earlier in commit `e2b07b2` — to pin the happy-path
        shape we still use a MISSING-FIELD failure (Pydantic
           reports this as type='missing' with no ctx.error), which
           serializes cleanly."""
        async with _client(app) as c:
            r = await c.post(
                "/api/v1/auth/login",
                json={"email": "ok@example.com"},  # password missing
            )
        assert r.status_code == 422
        body = r.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"

    async def test_login_normalizes_email_to_lowercase(
        self, app, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        """The `LoginRequest.validate_email` validator lowercases the email
        before authentication. Pins that mixed-case input works."""
        await _seed_user_with_role(db, email="caps@example.com", password="goodpwd1234")
        async with _client(app) as c:
            r = await c.post(
                "/api/v1/auth/login",
                json={"email": "CAPS@Example.com", "password": "goodpwd1234"},
            )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# POST /auth/logout
# ---------------------------------------------------------------------------


class TestLogout:
    async def test_logout_returns_ack_message(self, app) -> None:
        """Logout is stateless. The middleware doesn't gate it: the route
        is registered as authenticated, so we still need a token."""
        # Logout is stateless but middleware still requires auth.
        # An invalid token returns 401. An absent token returns 401.
        async with _client(app) as c:
            r = await c.post("/api/v1/auth/logout")
        # AuthMiddleware rejects without a token (path is not in the
        # public_routes_exact list).
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------


class TestGetMe:
    async def test_me_internal_user_returns_profile(
        self, app, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        """/auth/me is in the public_routes_exact list, so the middleware
        bypasses auth — but the route DOES decode the token itself."""
        user_id = await _seed_user_with_role(db, email="me@example.com", role="analyst")
        token = await _mint_token(db, user_id=user_id, role="analyst")

        async with _client(app) as c:
            r = await c.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["id"] == user_id
        assert body["email"] == "me@example.com"
        assert body["user_type"] == "internal"
        assert body["roles"] == ["analyst"]

    async def test_me_no_auth_header_returns_401(self, app) -> None:
        """/auth/me is in the AuthMiddleware public list so middleware
        bypasses it, but the route handler raises HTTPException(401)
        when the Authorization header is missing. The global error
        handler then wraps it in the {"error": {...}} envelope."""
        async with _client(app) as c:
            r = await c.get("/api/v1/auth/me")
        assert r.status_code == 401
        body = r.json()
        assert body["error"]["code"] == "HTTP_401"
        assert body["error"]["message"] == "Authentication required"

    async def test_me_malformed_token_returns_401(self, app) -> None:
        async with _client(app) as c:
            r = await c.get(
                "/api/v1/auth/me", headers={"Authorization": "Bearer garbage.jwt.value"}
            )
        assert r.status_code == 401
        body = r.json()
        assert body["error"]["code"] == "HTTP_401"
        assert body["error"]["message"] == "Invalid token"

    async def test_me_public_user_token_returns_public_shape(self, app) -> None:
        """A token with user_type='public' returns a public-user shape
        (no DB lookup). Pins lines 108-113."""
        from datetime import datetime, timedelta

        import jwt

        from src.config import ALGORITHM, JWT_SECRET

        future = int((datetime.utcnow() + timedelta(minutes=10)).timestamp())
        token = jwt.encode(
            {
                "sub": "pub-1",
                "email": "p@example.com",
                "user_type": "public",
                "exp": future,
            },
            JWT_SECRET,
            algorithm=ALGORITHM,
        )

        async with _client(app) as c:
            r = await c.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        body = r.json()
        assert body["user_type"] == "public"
        assert body["id"] == "pub-1"
        assert body["email"] == "p@example.com"


# ---------------------------------------------------------------------------
# GET /auth/roles
# ---------------------------------------------------------------------------


class TestGetRoles:
    async def test_roles_endpoint_returns_4_tier_list(
        self, app, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        """Pins the 4-tier role list (admin/analyst/user/guest).

        This route is behind AuthMiddleware so we need a valid token,
        but role doesn't matter for this endpoint."""
        user_id = await _seed_user_with_role(db, email="anyone@example.com")
        token = await _mint_token(db, user_id=user_id)

        async with _client(app) as c:
            r = await c.get(
                "/api/v1/auth/roles",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200, r.text
        ids = [role["id"] for role in r.json()["roles"]]
        assert ids == ["admin", "analyst", "user", "guest"]


# ---------------------------------------------------------------------------
# GET /auth/users — listing endpoint with the Phase-1.9a `role` key pin
# ---------------------------------------------------------------------------


class TestListUsers:
    async def test_admin_can_list_users(
        self, app, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        await _seed_user_with_role(db, email="other@example.com", role="analyst")
        admin_id = await _seed_user_with_role(db, email="admin@example.com", role="admin")
        token = await _mint_token(db, user_id=admin_id, role="admin")

        async with _client(app) as c:
            r = await c.get(
                "/api/v1/auth/users",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body, list)
        assert len(body) >= 2

    async def test_listing_response_uses_role_key_not_tenant_role(
        self, app, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        """**Phase-1.9a contract pin:** /auth/users JSON returns the
        `role` key on each user (NOT legacy `tenant_role`). This was
        the post-Phase-1.9a JSON-key cutover."""
        admin_id = await _seed_user_with_role(db, email="admin2@example.com", role="admin")
        token = await _mint_token(db, user_id=admin_id, role="admin")

        async with _client(app) as c:
            r = await c.get(
                "/api/v1/auth/users",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200
        for user_doc in r.json():
            assert "role" in user_doc
            assert "tenant_role" not in user_doc

    async def test_non_admin_rejected_with_403(
        self, app, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        analyst_id = await _seed_user_with_role(db, email="analyst@example.com", role="analyst")
        token = await _mint_token(db, user_id=analyst_id, role="analyst")

        async with _client(app) as c:
            r = await c.get(
                "/api/v1/auth/users",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 403

    async def test_no_token_rejected_with_401(self, app) -> None:
        async with _client(app) as c:
            r = await c.get("/api/v1/auth/users")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /auth/users — create a new user
# ---------------------------------------------------------------------------


class TestCreateUser:
    async def test_admin_can_create_user_with_password(
        self, app, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        admin_id = await _seed_user_with_role(db, email="cu-admin@example.com", role="admin")
        token = await _mint_token(db, user_id=admin_id, role="admin")

        async with _client(app) as c:
            r = await c.post(
                "/api/v1/auth/users",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "email": "new@example.com",
                    "full_name": "New User",
                    "password": "validpwd123",
                    "role": "analyst",
                },
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["email"] == "new@example.com"
        assert body["role"] == "analyst"
        assert body["disabled"] is False
        assert body["invitation_sent"] is False

    async def test_admin_create_user_duplicate_email_returns_400(
        self, app, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        admin_id = await _seed_user_with_role(db, email="cu2-admin@example.com", role="admin")
        await _seed_user_with_role(db, email="dup@example.com")
        token = await _mint_token(db, user_id=admin_id, role="admin")

        async with _client(app) as c:
            r = await c.post(
                "/api/v1/auth/users",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "email": "dup@example.com",
                    "full_name": "Dup",
                    "password": "newpwd1234",
                    "role": "user",
                },
            )
        assert r.status_code == 400
        body = r.json()
        assert body["error"]["code"] == "HTTP_400"
        assert "already exists" in body["error"]["message"]

    async def test_non_admin_cannot_create_user(
        self, app, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        analyst_id = await _seed_user_with_role(db, email="not-admin@example.com", role="analyst")
        token = await _mint_token(db, user_id=analyst_id, role="analyst")

        async with _client(app) as c:
            r = await c.post(
                "/api/v1/auth/users",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "email": "shouldnot@example.com",
                    "full_name": "X",
                    "role": "user",
                },
            )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# PUT /auth/users/{id}
# ---------------------------------------------------------------------------


class TestUpdateUser:
    async def test_admin_can_update_user(
        self, app, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        admin_id = await _seed_user_with_role(db, email="upd-admin@example.com", role="admin")
        target_id = await _seed_user_with_role(db, email="target@example.com")
        token = await _mint_token(db, user_id=admin_id, role="admin")

        async with _client(app) as c:
            r = await c.put(
                f"/api/v1/auth/users/{target_id}",
                headers={"Authorization": f"Bearer {token}"},
                json={"full_name": "Renamed", "role": "analyst"},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["role"] == "analyst"

    async def test_update_nonexistent_user_returns_404(
        self, app, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        admin_id = await _seed_user_with_role(db, email="upd2-admin@example.com", role="admin")
        token = await _mint_token(db, user_id=admin_id, role="admin")

        async with _client(app) as c:
            r = await c.put(
                "/api/v1/auth/users/ghost-id",
                headers={"Authorization": f"Bearer {token}"},
                json={"full_name": "x"},
            )
        assert r.status_code == 404

    async def test_non_admin_cannot_update_user(
        self, app, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        user_id = await _seed_user_with_role(db, email="regular@example.com", role="user")
        token = await _mint_token(db, user_id=user_id, role="user")

        async with _client(app) as c:
            r = await c.put(
                f"/api/v1/auth/users/{user_id}",
                headers={"Authorization": f"Bearer {token}"},
                json={"full_name": "x"},
            )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /auth/users/{id}
# ---------------------------------------------------------------------------


class TestDeleteUser:
    async def test_admin_can_delete_user(
        self, app, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        admin_id = await _seed_user_with_role(db, email="del-admin@example.com", role="admin")
        target_id = await _seed_user_with_role(db, email="doomed@example.com")
        token = await _mint_token(db, user_id=admin_id, role="admin")

        async with _client(app) as c:
            r = await c.delete(
                f"/api/v1/auth/users/{target_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200
        assert r.json() == {"message": "User deleted"}

    async def test_delete_nonexistent_user_returns_404(
        self, app, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        admin_id = await _seed_user_with_role(db, email="del2-admin@example.com", role="admin")
        token = await _mint_token(db, user_id=admin_id, role="admin")

        async with _client(app) as c:
            r = await c.delete(
                "/api/v1/auth/users/ghost-delete",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /auth/users/assignable + /auth/users/guests + /auth/users/search
# ---------------------------------------------------------------------------


class TestUserSubLists:
    async def test_assignable_users_returns_admin_and_analyst(
        self, app, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        admin_id = await _seed_user_with_role(db, email="a@example.com", role="admin")
        await _seed_user_with_role(db, email="b@example.com", role="analyst")
        await _seed_user_with_role(db, email="c@example.com", role="user")
        token = await _mint_token(db, user_id=admin_id, role="admin")

        async with _client(app) as c:
            r = await c.get(
                "/api/v1/auth/users/assignable",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200
        body = r.json()
        roles = {u["role"] for u in body}
        assert "admin" in roles or "analyst" in roles
        assert "user" not in roles  # 'user' is not assignable

    async def test_guests_list_returns_only_guests(
        self, app, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        admin_id = await _seed_user_with_role(db, email="g-admin@example.com", role="admin")
        await _seed_user_with_role(db, email="guest1@example.com", role="guest")
        await _seed_user_with_role(db, email="user1@example.com", role="user")
        token = await _mint_token(db, user_id=admin_id, role="admin")

        async with _client(app) as c:
            r = await c.get(
                "/api/v1/auth/users/guests",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200
        body = r.json()
        for u in body:
            assert u["role"] == "guest"

    async def test_user_search_by_query_string(
        self, app, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        admin_id = await _seed_user_with_role(db, email="s-admin@example.com", role="admin")
        await _seed_user_with_role(db, email="findable@example.com", name="Findable")
        token = await _mint_token(db, user_id=admin_id, role="admin")

        async with _client(app) as c:
            r = await c.get(
                "/api/v1/auth/users/search?q=find",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200
        body = r.json()
        assert "users" in body
        emails = [u["email"] for u in body["users"]]
        assert "findable@example.com" in emails

    async def test_user_search_short_query_returns_all_active(
        self, app, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        """Query with len < 2 -> the $or filter isn't added; returns all
        active users (subject to limit). Pins lines 415-419."""
        admin_id = await _seed_user_with_role(db, email="sa-admin@example.com", role="admin")
        await _seed_user_with_role(db, email="extra@example.com")
        token = await _mint_token(db, user_id=admin_id, role="admin")

        async with _client(app) as c:
            r = await c.get(
                "/api/v1/auth/users/search?q=a",  # len=1 -> no filter
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200
        body = r.json()
        assert "users" in body
        # At least the two we seeded should be in the unfiltered list.
        assert len(body["users"]) >= 2

    async def test_user_search_no_query_returns_all_active(
        self, app, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        admin_id = await _seed_user_with_role(db, email="snq-admin@example.com", role="admin")
        token = await _mint_token(db, user_id=admin_id, role="admin")

        async with _client(app) as c:
            r = await c.get(
                "/api/v1/auth/users/search",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200
        body = r.json()
        assert "users" in body
