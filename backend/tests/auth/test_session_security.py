"""Security-review 2026-09 regression tests for token realms and sessions.

- AUTH-03: magic-link (public) tokens carry an explicit `public_user` role and
  `blackbar-public` audience, and are refused by every staff endpoint.
- AUTH-14: the staff principal is re-read from the DB on each request: the DB
  role wins over the token claim, disabled/deleted users are refused, and a
  per-user `token_version` lets logout and password changes revoke tokens.
- AUTH-26: the staff `exp` claim is a real Unix epoch, independent of the host
  timezone.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import httpx
import jwt
import pytest
from httpx import ASGITransport
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.auth.auth_service import AuthService
from src.auth.security import INTERNAL_AUDIENCE, PUBLIC_AUDIENCE, PUBLIC_ROLE
from src.config import ACCESS_TOKEN_EXPIRE_MINUTES, ALGORITHM, JWT_SECRET
from src.public_users.models import PublicUser
from src.users.models import UserCreate
from src.users.repository import UsersRepository


@pytest.fixture
def patch_user_lookups(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase):
    """Point every module-level users/db handle the auth path reads at the
    per-test database."""
    import src.auth.routes as auth_routes
    import src.dependencies as deps_mod

    monkeypatch.setattr(deps_mod, "users", db.users)
    monkeypatch.setattr(auth_routes, "db", db)
    return db


def _client(app, token: str | None = None) -> httpx.AsyncClient:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver", headers=headers
    )


async def _seed_user(
    db: AsyncIOMotorDatabase, *, role: str = "user", email: str | None = None
) -> str:
    repo = UsersRepository(db)
    email = email or f"{role}-{time.time_ns()}@example.com"
    user = await repo.create(
        UserCreate(email=email, name="Seed", password="x"),
        AuthService.hash_password("correct-horse-battery"),
    )
    await db.users.update_one({"id": user.id}, {"$set": {"role": role}})
    return user.id


async def _token_for(db: AsyncIOMotorDatabase, user_id: str) -> str:
    repo = UsersRepository(db)
    user = await repo.get_by_id(user_id)
    assert user is not None
    return await AuthService(repo).issue_token(user)


def _public_token() -> str:
    from src.auth.magic_link_service import MagicLinkService

    now = datetime.now(UTC)
    user = PublicUser(
        id="public-user-1",
        email="requester@example.org",
        created_at=now,
        updated_at=now,
    )
    return MagicLinkService(users_repo=None, tokens_repo=None).issue_token(user)  # type: ignore[arg-type]


def _decode(token: str) -> dict[str, Any]:
    return jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM], options={"verify_aud": False})


# ---------------------------------------------------------------------------
# AUTH-03: public tokens
# ---------------------------------------------------------------------------


class TestPublicTokenClaims:
    def test_public_token_has_explicit_role_and_audience(self) -> None:
        claims = _decode(_public_token())
        assert claims["role"] == PUBLIC_ROLE
        assert claims["aud"] == PUBLIC_AUDIENCE
        assert claims["realm"] == "public"

    def test_validate_token_maps_public_token_to_public_realm(self) -> None:
        payload = AuthService.validate_token(_public_token())
        assert payload is not None
        assert payload.realm == "public"
        assert payload.role == PUBLIC_ROLE

    def test_legacy_public_token_without_role_is_still_public(self) -> None:
        """Tokens minted before this fix have no role claim; they must never
        default to the internal `user` role."""
        legacy = jwt.encode(
            {
                "sub": "p1",
                "email": "a@example.org",
                "realm": "public",
                "user_type": "public",
                "exp": int(time.time()) + 600,
            },
            JWT_SECRET,
            algorithm=ALGORITHM,
        )
        payload = AuthService.validate_token(legacy)
        assert payload is not None
        assert payload.role == PUBLIC_ROLE
        assert payload.realm == "public"

    def test_staff_token_without_role_is_rejected(self) -> None:
        token = jwt.encode(
            {"sub": "u1", "realm": "org", "exp": int(time.time()) + 600},
            JWT_SECRET,
            algorithm=ALGORITHM,
        )
        assert AuthService.validate_token(token) is None

    def test_unknown_audience_is_rejected(self) -> None:
        token = jwt.encode(
            {"sub": "u1", "role": "admin", "aud": "someone-else", "exp": int(time.time()) + 600},
            JWT_SECRET,
            algorithm=ALGORITHM,
        )
        assert AuthService.validate_token(token) is None

    def test_token_without_exp_is_rejected(self) -> None:
        token = jwt.encode({"sub": "u1", "role": "admin"}, JWT_SECRET, algorithm=ALGORITHM)
        assert AuthService.validate_token(token) is None


class TestPublicTokenBlockedFromStaffRoutes:
    @pytest.mark.parametrize(
        "method,path",
        [
            ("GET", "/api/v1/auth/users/search"),
            ("GET", "/api/v1/auth/users/assignable"),
            ("GET", "/api/v1/auth/users/guests"),
            ("GET", "/api/v1/auth/users"),
            ("GET", "/api/v1/cases/"),
            ("GET", "/api/v1/categories/"),
            ("GET", "/api/v1/packs/"),
            ("GET", "/api/v1/teams/"),
            ("POST", "/api/v1/auth/logout"),
            ("GET", "/metrics"),
        ],
    )
    async def test_public_token_gets_403(
        self, app, patch_user_lookups, method: str, path: str
    ) -> None:
        async with _client(app, _public_token()) as c:
            r = await c.request(method, path)
        assert r.status_code == 403, f"{method} {path} -> {r.status_code} {r.text}"

    async def test_public_token_still_works_on_public_me(self, app, patch_user_lookups) -> None:
        async with _client(app, _public_token()) as c:
            r = await c.get("/api/v1/auth/me")
        assert r.status_code == 200, r.text
        assert r.json()["user_type"] == "public"

    async def test_public_token_forced_through_dependency_is_refused(
        self, db: AsyncIOMotorDatabase, patch_user_lookups
    ) -> None:
        """Defence in depth: even if a route slipped past the middleware, the
        staff dependency refuses a public-realm principal."""
        from types import SimpleNamespace

        from fastapi import HTTPException

        from src.dependencies import get_current_user

        request = SimpleNamespace(
            state=SimpleNamespace(user_id="public-user-1", roles=[PUBLIC_ROLE], realm="public")
        )
        with pytest.raises(HTTPException) as exc:
            await get_current_user(request, token=None)  # type: ignore[arg-type]
        assert exc.value.status_code == 403


class TestUserDirectoryGates:
    @pytest.mark.parametrize(
        "path",
        ["/api/v1/auth/users/search", "/api/v1/auth/users/assignable", "/api/v1/auth/users/guests"],
    )
    async def test_guest_cannot_list_staff_directory(
        self, app, db: AsyncIOMotorDatabase, patch_user_lookups, path: str
    ) -> None:
        guest_id = await _seed_user(db, role="guest")
        async with _client(app, await _token_for(db, guest_id)) as c:
            r = await c.get(path)
        assert r.status_code == 403, r.text

    async def test_search_limit_is_bounded(
        self, app, db: AsyncIOMotorDatabase, patch_user_lookups
    ) -> None:
        uid = await _seed_user(db, role="analyst")
        async with _client(app, await _token_for(db, uid)) as c:
            r = await c.get("/api/v1/auth/users/search", params={"limit": 100000})
        assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# AUTH-14: DB re-check and revocation
# ---------------------------------------------------------------------------


class TestDatabaseRecheck:
    async def test_forged_admin_token_for_unknown_user_is_refused(
        self, app, patch_user_lookups
    ) -> None:
        forged = jwt.encode(
            {
                "sub": "no-such-user",
                "role": "admin",
                "realm": "admin",
                "aud": INTERNAL_AUDIENCE,
                "exp": int(time.time()) + 600,
            },
            JWT_SECRET,
            algorithm=ALGORITHM,
        )
        async with _client(app, forged) as c:
            r = await c.put("/api/v1/auth/users/whoever", json={"role": "admin"})
        assert r.status_code == 401, r.text

    async def test_disabled_user_token_is_refused(
        self, app, db: AsyncIOMotorDatabase, patch_user_lookups
    ) -> None:
        uid = await _seed_user(db, role="admin")
        token = await _token_for(db, uid)
        await db.users.update_one({"id": uid}, {"$set": {"status": "disabled"}})
        async with _client(app, token) as c:
            staff = await c.get("/api/v1/auth/users")
            other = await c.get("/api/v1/teams/")
        assert staff.status_code == 401, staff.text
        assert other.status_code == 401, other.text

    async def test_deleted_admin_token_is_refused(
        self, app, db: AsyncIOMotorDatabase, patch_user_lookups
    ) -> None:
        uid = await _seed_user(db, role="admin")
        token = await _token_for(db, uid)
        await db.users.delete_one({"id": uid})
        async with _client(app, token) as c:
            r = await c.post(
                "/api/v1/auth/users",
                json={"email": "new@example.com", "full_name": "N", "role": "admin"},
            )
        assert r.status_code == 401, r.text

    async def test_demoted_admin_loses_admin_routes_immediately(
        self, app, db: AsyncIOMotorDatabase, patch_user_lookups
    ) -> None:
        uid = await _seed_user(db, role="admin")
        token = await _token_for(db, uid)
        await db.users.update_one({"id": uid}, {"$set": {"role": "user"}})
        async with _client(app, token) as c:
            r = await c.get("/api/v1/auth/users")
        assert r.status_code == 403, r.text


class TestRevocation:
    async def test_logout_revokes_the_token(
        self, app, db: AsyncIOMotorDatabase, patch_user_lookups
    ) -> None:
        uid = await _seed_user(db, role="analyst")
        token = await _token_for(db, uid)
        async with _client(app, token) as c:
            assert (await c.get("/api/v1/auth/users/search")).status_code == 200
            out = await c.post("/api/v1/auth/logout")
            assert out.status_code == 200, out.text
            after = await c.get("/api/v1/auth/users/search")
        assert after.status_code == 401, after.text

    async def test_new_login_after_logout_works(
        self, app, db: AsyncIOMotorDatabase, patch_user_lookups
    ) -> None:
        uid = await _seed_user(db, role="analyst")
        async with _client(app, await _token_for(db, uid)) as c:
            await c.post("/api/v1/auth/logout")
        async with _client(app, await _token_for(db, uid)) as c:
            assert (await c.get("/api/v1/auth/users/search")).status_code == 200

    async def test_admin_password_reset_revokes_target_sessions(
        self, app, db: AsyncIOMotorDatabase, patch_user_lookups
    ) -> None:
        admin_id = await _seed_user(db, role="admin")
        target_id = await _seed_user(db, role="analyst")
        target_token = await _token_for(db, target_id)
        async with _client(app, await _token_for(db, admin_id)) as admin:
            r = await admin.put(
                f"/api/v1/auth/users/{target_id}", json={"password": "a-brand-new-passphrase"}
            )
            assert r.status_code == 200, r.text
        async with _client(app, target_token) as c:
            assert (await c.get("/api/v1/auth/users/search")).status_code == 401

    async def test_admin_disable_and_role_change_revoke_sessions(
        self, app, db: AsyncIOMotorDatabase, patch_user_lookups
    ) -> None:
        admin_id = await _seed_user(db, role="admin")
        target_id = await _seed_user(db, role="analyst")
        target_token = await _token_for(db, target_id)
        async with _client(app, await _token_for(db, admin_id)) as admin:
            r = await admin.put(f"/api/v1/auth/users/{target_id}", json={"role": "user"})
            assert r.status_code == 200, r.text
        async with _client(app, target_token) as c:
            assert (await c.get("/api/v1/auth/users/search")).status_code == 401


# ---------------------------------------------------------------------------
# AUTH-26: exp is a real epoch
# ---------------------------------------------------------------------------


class TestStaffTokenClaims:
    async def test_staff_token_claims(self, db: AsyncIOMotorDatabase) -> None:
        uid = await _seed_user(db, role="analyst")
        before = int(time.time())
        claims = _decode(await _token_for(db, uid))
        after = int(time.time())
        assert claims["aud"] == INTERNAL_AUDIENCE
        assert claims["role"] == "analyst"
        assert claims["tv"] == 0
        assert before <= claims["iat"] <= after
        expected = ACCESS_TOKEN_EXPIRE_MINUTES * 60
        assert before + expected <= claims["exp"] <= after + expected

    async def test_exp_ignores_host_timezone(
        self, db: AsyncIOMotorDatabase, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TZ", "America/Los_Angeles")
        time.tzset()
        try:
            uid = await _seed_user(db, role="analyst")
            claims = _decode(await _token_for(db, uid))
            assert abs(claims["exp"] - (time.time() + ACCESS_TOKEN_EXPIRE_MINUTES * 60)) < 5
        finally:
            monkeypatch.delenv("TZ")
            time.tzset()
