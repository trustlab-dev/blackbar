"""Tests for `src.core.dependencies` — request-state-driven auth helpers.

Critical-path: 100% line + branch.

Functions under test:
- get_current_user_id / get_current_user_id_optional
- get_user_roles
- require_role (factory) — wraps get_current_user_id + role membership
- require_admin (4-tier: admin role)
- _get_jwt_realm (private)
- require_admin_access — realm-aware check with extra role gate
- get_correlation_id

All take only a duck-typed Request. The middleware sets request.state.user_id
and request.state.roles upstream; these helpers consume that state.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import jwt
import pytest
from fastapi import HTTPException

from src.config import ALGORITHM, JWT_SECRET
from src.core.dependencies import (
    _get_jwt_realm,
    get_correlation_id,
    get_current_user_id,
    get_current_user_id_optional,
    get_user_roles,
    require_admin,
    require_admin_access,
    require_role,
)


def _make_request(
    *,
    state: dict | None = None,
    auth_header: str | None = None,
    path: str = "/api/v1/example",
):
    """Duck-typed Request with .state (SimpleNamespace), .headers.get(), .url.path."""
    headers_dict = {}
    if auth_header is not None:
        headers_dict["Authorization"] = auth_header

    class _Headers:
        def __init__(self, d):
            self._d = d

        def get(self, key, default=None):
            return self._d.get(key, default)

    return SimpleNamespace(
        state=SimpleNamespace(**(state or {})),
        headers=_Headers(headers_dict),
        url=SimpleNamespace(path=path),
    )


def _make_jwt(payload: dict[str, Any], secret: str = JWT_SECRET) -> str:
    base = {"exp": int(time.time() + 600)}
    base.update(payload)
    return jwt.encode(base, secret, algorithm=ALGORITHM)


# ---------------------------------------------------------------------------
# get_current_user_id / *_optional
# ---------------------------------------------------------------------------


class TestGetCurrentUserId:
    def test_state_populated_returns_id(self):
        req = _make_request(state={"user_id": "u-1"})
        assert get_current_user_id(req) == "u-1"

    def test_missing_state_raises_401(self):
        req = _make_request(state={})
        with pytest.raises(HTTPException) as exc:
            get_current_user_id(req)
        assert exc.value.status_code == 401
        assert exc.value.detail == "Authentication required"

    def test_empty_state_user_id_raises_401(self):
        """state.user_id is set but falsy (empty string)."""
        req = _make_request(state={"user_id": ""})
        with pytest.raises(HTTPException) as exc:
            get_current_user_id(req)
        assert exc.value.status_code == 401


class TestGetCurrentUserIdOptional:
    def test_state_populated_returns_id(self):
        req = _make_request(state={"user_id": "u-2"})
        assert get_current_user_id_optional(req) == "u-2"

    def test_missing_state_returns_none(self):
        req = _make_request(state={})
        assert get_current_user_id_optional(req) is None


# ---------------------------------------------------------------------------
# get_user_roles
# ---------------------------------------------------------------------------


class TestGetUserRoles:
    def test_populated_returns_list(self):
        req = _make_request(state={"roles": ["admin", "analyst"]})
        assert get_user_roles(req) == ["admin", "analyst"]

    def test_missing_returns_empty(self):
        req = _make_request(state={})
        assert get_user_roles(req) == []


# ---------------------------------------------------------------------------
# require_role factory
# ---------------------------------------------------------------------------


class TestRequireRole:
    def test_user_with_matching_role_passes(self):
        gate = require_role(["admin"])
        req = _make_request(state={"user_id": "u-1", "roles": ["admin"]})
        assert gate(req) is True

    def test_user_with_one_of_many_roles_passes(self):
        gate = require_role(["admin", "analyst"])
        req = _make_request(state={"user_id": "u-1", "roles": ["analyst"]})
        assert gate(req) is True

    def test_no_matching_role_raises_403(self):
        gate = require_role(["admin"])
        req = _make_request(state={"user_id": "u-1", "roles": ["user"]})
        with pytest.raises(HTTPException) as exc:
            gate(req)
        assert exc.value.status_code == 403
        assert exc.value.detail == "Insufficient permissions"

    def test_unauthenticated_raises_401_not_403(self):
        """The factory calls get_current_user_id first; auth fails before
        the role check fires."""
        gate = require_role(["admin"])
        req = _make_request(state={})
        with pytest.raises(HTTPException) as exc:
            gate(req)
        assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# require_admin (4-tier role-based)
# ---------------------------------------------------------------------------


class TestRequireAdmin:
    def test_admin_role_passes(self):
        req = _make_request(state={"user_id": "u-1", "roles": ["admin"]})
        assert require_admin(req) is True

    def test_mixed_case_admin_passes(self):
        req = _make_request(state={"user_id": "u-1", "roles": ["Admin"]})
        assert require_admin(req) is True

    def test_non_admin_raises_403(self):
        req = _make_request(state={"user_id": "u-1", "roles": ["analyst"]})
        with pytest.raises(HTTPException) as exc:
            require_admin(req)
        assert exc.value.status_code == 403
        assert exc.value.detail == "Admin access required"

    def test_unauthenticated_raises_401(self):
        req = _make_request(state={})
        with pytest.raises(HTTPException) as exc:
            require_admin(req)
        assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# _get_jwt_realm (private helper)
# ---------------------------------------------------------------------------


class TestGetJwtRealm:
    def test_valid_token_returns_realm(self):
        token = _make_jwt({"sub": "u-1", "realm": "org"})
        req = _make_request(auth_header=f"Bearer {token}")
        assert _get_jwt_realm(req) == "org"

    def test_no_realm_in_token_returns_none(self):
        token = _make_jwt({"sub": "u-1"})  # no realm key
        req = _make_request(auth_header=f"Bearer {token}")
        assert _get_jwt_realm(req) is None

    def test_no_auth_header_returns_none(self):
        req = _make_request(auth_header=None)
        assert _get_jwt_realm(req) is None

    def test_wrong_scheme_returns_none(self):
        req = _make_request(auth_header="Basic abc.def.ghi")
        assert _get_jwt_realm(req) is None

    def test_malformed_token_returns_none(self):
        req = _make_request(auth_header="Bearer not.a.jwt")
        assert _get_jwt_realm(req) is None

    def test_expired_token_returns_none(self):
        token = _make_jwt({"sub": "u-1", "realm": "org", "exp": int(time.time() - 600)})
        req = _make_request(auth_header=f"Bearer {token}")
        assert _get_jwt_realm(req) is None


# ---------------------------------------------------------------------------
# require_admin_access (realm + role)
# ---------------------------------------------------------------------------


class TestRequireAdminAccess:
    def test_admin_role_with_no_realm_passes(self):
        """No token at all (realm=None) → not 'public' → falls through to
        the role check, which passes for 'admin'."""
        req = _make_request(state={"user_id": "u-1", "roles": ["admin"]})
        assert require_admin_access(req) is True

    def test_owner_role_with_no_realm_passes(self):
        req = _make_request(state={"user_id": "u-1", "roles": ["owner"]})
        assert require_admin_access(req) is True

    def test_mixed_case_owner_passes(self):
        req = _make_request(state={"user_id": "u-1", "roles": ["Owner"]})
        assert require_admin_access(req) is True

    def test_public_realm_rejected_403(self):
        token = _make_jwt({"sub": "u-1", "realm": "public"})
        req = _make_request(
            state={"user_id": "u-1", "roles": ["admin"]},
            auth_header=f"Bearer {token}",
        )
        with pytest.raises(HTTPException) as exc:
            require_admin_access(req)
        assert exc.value.status_code == 403
        assert "Public users cannot access admin routes" in exc.value.detail

    def test_public_realm_without_state_user_id_still_403(self):
        """The public-realm warning uses get_current_user_id_optional which
        returns None when state is empty. Pin that None doesn't crash."""
        token = _make_jwt({"sub": "u-1", "realm": "public"})
        req = _make_request(state={}, auth_header=f"Bearer {token}")
        with pytest.raises(HTTPException) as exc:
            require_admin_access(req)
        assert exc.value.status_code == 403

    def test_org_realm_with_admin_role_passes(self):
        token = _make_jwt({"sub": "u-1", "realm": "org"})
        req = _make_request(
            state={"user_id": "u-1", "roles": ["admin"]},
            auth_header=f"Bearer {token}",
        )
        assert require_admin_access(req) is True

    def test_org_realm_with_no_admin_role_raises_403(self):
        token = _make_jwt({"sub": "u-1", "realm": "org"})
        req = _make_request(
            state={"user_id": "u-1", "roles": ["analyst"]},
            auth_header=f"Bearer {token}",
        )
        with pytest.raises(HTTPException) as exc:
            require_admin_access(req)
        assert exc.value.status_code == 403
        assert "Admin role required" in exc.value.detail

    def test_org_realm_no_admin_role_unauthenticated_raises_403(self):
        """Phase 4 Batch 4.4 (audit B42): when the role check fails and
        `state.user_id` is unset, the warning block now uses the
        None-safe `get_current_user_id_optional` so the intentional
        403 reaches the caller instead of being masked by a 401 from
        the strict getter. Test flipped from `_raises_401`."""
        token = _make_jwt({"sub": "u-1", "realm": "org"})
        req = _make_request(state={"roles": ["analyst"]}, auth_header=f"Bearer {token}")
        with pytest.raises(HTTPException) as exc:
            require_admin_access(req)
        assert exc.value.status_code == 403
        assert "Admin role required" in exc.value.detail


# ---------------------------------------------------------------------------
# get_correlation_id
# ---------------------------------------------------------------------------


class TestGetCorrelationId:
    def test_state_populated_returns_id(self):
        req = _make_request(state={"correlation_id": "abc-123"})
        assert get_correlation_id(req) == "abc-123"

    def test_missing_state_returns_unknown(self):
        req = _make_request(state={})
        assert get_correlation_id(req) == "unknown"
