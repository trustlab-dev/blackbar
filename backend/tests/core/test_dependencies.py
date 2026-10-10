"""Tests for `src.core.dependencies` — request-context auth helpers.

Since the 2026-09 security review (AUTH-14) every authorization helper here
resolves the principal through `src.dependencies.get_current_user`, which
re-reads the user from the database: the DB role is authoritative, inactive
or deleted users are refused, and public-realm principals are refused.

Functions under test:
- get_current_user_id / get_current_user_id_optional
- get_user_roles
- require_role (factory)
- require_admin
- require_admin_access
- get_correlation_id

All take only a duck-typed Request whose `.state` mimics what AuthMiddleware
sets (user_id, roles, realm, token_version).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.core.dependencies import (
    get_correlation_id,
    get_current_user_id,
    get_current_user_id_optional,
    get_user_roles,
    require_admin,
    require_admin_access,
    require_role,
)


def _make_request(*, state: dict | None = None, path: str = "/api/v1/example"):
    """Duck-typed Request with .state (SimpleNamespace) and .url.path."""
    return SimpleNamespace(
        state=SimpleNamespace(**(state or {})),
        url=SimpleNamespace(path=path),
    )


@pytest.fixture
def seed_user(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase):
    """Point `src.dependencies.users` at the test DB and return a seeder."""
    import src.dependencies as deps_mod

    monkeypatch.setattr(deps_mod, "users", db.users)

    async def _seed(role: str = "user", status: str = "active", token_version: int = 0) -> str:
        uid = str(uuid.uuid4())
        await db.users.insert_one(
            {
                "id": uid,
                "email": f"{uid}@example.com",
                "role": role,
                "status": status,
                "token_version": token_version,
            }
        )
        return uid

    return _seed


# ---------------------------------------------------------------------------
# get_current_user_id / *_optional
# ---------------------------------------------------------------------------


class TestGetCurrentUserId:
    async def test_active_user_returns_id(self, seed_user):
        uid = await seed_user("analyst")
        req = _make_request(state={"user_id": uid, "roles": ["analyst"]})
        assert await get_current_user_id(req) == uid

    async def test_missing_state_raises_401(self):
        with pytest.raises(HTTPException) as exc:
            await get_current_user_id(_make_request(state={}))
        assert exc.value.status_code == 401

    async def test_empty_state_user_id_raises_401(self):
        with pytest.raises(HTTPException) as exc:
            await get_current_user_id(_make_request(state={"user_id": ""}))
        assert exc.value.status_code == 401

    async def test_unknown_user_raises_401(self, seed_user):
        req = _make_request(state={"user_id": "ghost", "roles": ["admin"]})
        with pytest.raises(HTTPException) as exc:
            await get_current_user_id(req)
        assert exc.value.status_code == 401

    async def test_disabled_user_raises_401(self, seed_user):
        uid = await seed_user("admin", status="disabled")
        req = _make_request(state={"user_id": uid, "roles": ["admin"]})
        with pytest.raises(HTTPException) as exc:
            await get_current_user_id(req)
        assert exc.value.status_code == 401

    async def test_stale_token_version_raises_401(self, seed_user):
        uid = await seed_user("admin", token_version=3)
        req = _make_request(state={"user_id": uid, "roles": ["admin"], "token_version": 2})
        with pytest.raises(HTTPException) as exc:
            await get_current_user_id(req)
        assert exc.value.status_code == 401

    async def test_public_realm_raises_403(self, seed_user):
        req = _make_request(state={"user_id": "p-1", "roles": ["public_user"], "realm": "public"})
        with pytest.raises(HTTPException) as exc:
            await get_current_user_id(req)
        assert exc.value.status_code == 403


class TestGetCurrentUserIdOptional:
    def test_state_populated_returns_id(self):
        assert get_current_user_id_optional(_make_request(state={"user_id": "u-1"})) == "u-1"

    def test_missing_state_returns_none(self):
        assert get_current_user_id_optional(_make_request(state={})) is None


class TestGetUserRoles:
    def test_populated_returns_list(self):
        assert get_user_roles(_make_request(state={"roles": ["admin"]})) == ["admin"]

    def test_missing_returns_empty(self):
        assert get_user_roles(_make_request(state={})) == []


# ---------------------------------------------------------------------------
# require_role factory
# ---------------------------------------------------------------------------


class TestRequireRole:
    async def test_user_with_matching_role_passes(self, seed_user):
        uid = await seed_user("admin")
        req = _make_request(state={"user_id": uid, "roles": ["admin"]})
        assert await require_role(["admin"])(req) is True

    async def test_user_with_one_of_many_roles_passes(self, seed_user):
        uid = await seed_user("analyst")
        req = _make_request(state={"user_id": uid, "roles": ["analyst"]})
        assert await require_role(["admin", "analyst"])(req) is True

    async def test_no_matching_role_raises_403(self, seed_user):
        uid = await seed_user("user")
        req = _make_request(state={"user_id": uid, "roles": ["user"]})
        with pytest.raises(HTTPException) as exc:
            await require_role(["admin"])(req)
        assert exc.value.status_code == 403
        assert exc.value.detail == "Insufficient permissions"

    async def test_token_role_claim_is_not_trusted(self, seed_user):
        """AUTH-14: the token says admin, the DB says user -> 403."""
        uid = await seed_user("user")
        req = _make_request(state={"user_id": uid, "roles": ["admin"]})
        with pytest.raises(HTTPException) as exc:
            await require_role(["admin"])(req)
        assert exc.value.status_code == 403

    async def test_unauthenticated_raises_401_not_403(self):
        with pytest.raises(HTTPException) as exc:
            await require_role(["admin"])(_make_request(state={}))
        assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# require_admin
# ---------------------------------------------------------------------------


class TestRequireAdmin:
    async def test_admin_role_passes(self, seed_user):
        uid = await seed_user("admin")
        assert await require_admin(_make_request(state={"user_id": uid})) is True

    async def test_mixed_case_admin_passes(self, seed_user):
        uid = await seed_user("Admin")
        assert await require_admin(_make_request(state={"user_id": uid})) is True

    async def test_non_admin_raises_403(self, seed_user):
        uid = await seed_user("analyst")
        with pytest.raises(HTTPException) as exc:
            await require_admin(_make_request(state={"user_id": uid}))
        assert exc.value.status_code == 403
        assert exc.value.detail == "Admin access required"

    async def test_unauthenticated_raises_401(self):
        with pytest.raises(HTTPException) as exc:
            await require_admin(_make_request(state={}))
        assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# require_admin_access (realm + DB role)
# ---------------------------------------------------------------------------


class TestRequireAdminAccess:
    async def test_admin_passes(self, seed_user):
        uid = await seed_user("admin")
        assert await require_admin_access(_make_request(state={"user_id": uid})) is True

    async def test_owner_passes(self, seed_user):
        uid = await seed_user("owner")
        assert await require_admin_access(_make_request(state={"user_id": uid})) is True

    async def test_mixed_case_owner_passes(self, seed_user):
        uid = await seed_user("Owner")
        assert await require_admin_access(_make_request(state={"user_id": uid})) is True

    async def test_public_realm_rejected_403(self, seed_user):
        req = _make_request(state={"user_id": "u-1", "roles": ["admin"], "realm": "public"})
        with pytest.raises(HTTPException) as exc:
            await require_admin_access(req)
        assert exc.value.status_code == 403
        assert "Public users cannot access admin routes" in exc.value.detail

    async def test_public_realm_without_state_user_id_still_403(self):
        req = _make_request(state={"realm": "public"})
        with pytest.raises(HTTPException) as exc:
            await require_admin_access(req)
        assert exc.value.status_code == 403

    async def test_non_admin_raises_403(self, seed_user):
        uid = await seed_user("analyst")
        with pytest.raises(HTTPException) as exc:
            await require_admin_access(_make_request(state={"user_id": uid, "realm": "org"}))
        assert exc.value.status_code == 403
        assert "Admin role required" in exc.value.detail

    async def test_unauthenticated_raises_401(self):
        with pytest.raises(HTTPException) as exc:
            await require_admin_access(_make_request(state={"roles": ["admin"]}))
        assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# get_correlation_id
# ---------------------------------------------------------------------------


class TestGetCorrelationId:
    def test_state_populated_returns_id(self):
        req = _make_request(state={"correlation_id": "abc-123"})
        assert get_correlation_id(req) == "abc-123"

    def test_missing_state_returns_unknown(self):
        assert get_correlation_id(_make_request(state={})) == "unknown"
