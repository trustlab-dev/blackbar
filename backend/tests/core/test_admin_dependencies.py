"""Tests for `src.core.admin_dependencies` — admin realm guard.

Critical-path security boundary. Target: 100% line + branch coverage.

Module under test:
- `get_token_from_request(request)` — extracts/validates the Bearer header
- `decode_token(token)` — JWT decode + error mapping
- `require_admin_realm(request)` — realm=="admin"|"org" gate, with extra
  role-membership check ("owner" / "admin") for org realm. Public realm
  is explicitly rejected (post-Phase-1.7 fix).
- `require_global_admin(request)` — strict realm=="admin" OR role=="admin"
  gate.

Strategy: call dependencies directly with a duck-typed Request rather
than driving an ASGI app. The functions are sync (FastAPI dependencies),
take only `Request`, and don't access request.state beyond `url.path`
for logging.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import jwt
import pytest
from fastapi import HTTPException

from src.config import ALGORITHM, JWT_SECRET
from src.core.admin_dependencies import (
    decode_token,
    get_token_from_request,
    require_admin_realm,
    require_global_admin,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(auth_header: str | None = None, path: str = "/api/v1/admin/example"):
    """Duck-typed Request: provides .headers.get() and .url.path."""
    headers_dict = {}
    if auth_header is not None:
        headers_dict["Authorization"] = auth_header

    class _Headers:
        def __init__(self, d: dict):
            self._d = d

        def get(self, key: str, default=None):
            return self._d.get(key, default)

    url = SimpleNamespace(path=path)
    return SimpleNamespace(headers=_Headers(headers_dict), url=url)


def _make_jwt(payload: dict[str, Any], secret: str = JWT_SECRET) -> str:
    base = {"exp": int(time.time() + 600)}
    base.update(payload)
    return jwt.encode(base, secret, algorithm=ALGORITHM)


# ---------------------------------------------------------------------------
# get_token_from_request
# ---------------------------------------------------------------------------


class TestGetTokenFromRequest:
    def test_missing_header_raises_401(self):
        request = _make_request(auth_header=None)
        with pytest.raises(HTTPException) as exc:
            get_token_from_request(request)
        assert exc.value.status_code == 401
        assert exc.value.detail == "Authentication required"

    def test_wrong_scheme_raises_401(self):
        request = _make_request(auth_header="Basic abc.def.ghi")
        with pytest.raises(HTTPException) as exc:
            get_token_from_request(request)
        assert exc.value.status_code == 401
        assert "Expected 'Bearer <token>'" in exc.value.detail

    def test_valid_bearer_returns_token(self):
        request = _make_request(auth_header="Bearer my.token.value")
        assert get_token_from_request(request) == "my.token.value"


# ---------------------------------------------------------------------------
# decode_token
# ---------------------------------------------------------------------------


class TestDecodeToken:
    def test_valid_token_returns_payload(self):
        token = _make_jwt({"sub": "u-1", "realm": "org"})
        payload = decode_token(token)
        assert payload["sub"] == "u-1"
        assert payload["realm"] == "org"

    def test_malformed_token_raises_401(self):
        with pytest.raises(HTTPException) as exc:
            decode_token("not.a.jwt")
        assert exc.value.status_code == 401
        assert "Invalid or expired token" in exc.value.detail

    def test_expired_token_raises_401(self):
        token = _make_jwt({"sub": "u-1", "exp": int(time.time() - 600)})
        with pytest.raises(HTTPException) as exc:
            decode_token(token)
        assert exc.value.status_code == 401

    def test_wrong_signature_raises_401(self):
        token = _make_jwt({"sub": "u-1"}, secret="x" * 32 + "y" * 16)
        with pytest.raises(HTTPException) as exc:
            decode_token(token)
        assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# require_admin_realm
# ---------------------------------------------------------------------------


class TestRequireAdminRealm:
    async def test_realm_admin_passes(self):
        token = _make_jwt({"sub": "u-admin", "realm": "admin"})
        request = _make_request(auth_header=f"Bearer {token}")
        payload = await require_admin_realm(request)
        assert payload["realm"] == "admin"
        assert payload["sub"] == "u-admin"

    async def test_realm_org_with_owner_role_passes(self):
        token = _make_jwt({"sub": "u-1", "realm": "org", "roles": ["owner"]})
        request = _make_request(auth_header=f"Bearer {token}")
        payload = await require_admin_realm(request)
        assert payload["realm"] == "org"

    async def test_realm_org_with_admin_role_passes(self):
        token = _make_jwt({"sub": "u-1", "realm": "org", "roles": ["admin"]})
        request = _make_request(auth_header=f"Bearer {token}")
        payload = await require_admin_realm(request)
        assert payload["realm"] == "org"

    async def test_realm_org_with_mixed_case_role_passes(self):
        """roles_lower normalizes — 'Admin' should pass."""
        token = _make_jwt({"sub": "u-1", "realm": "org", "roles": ["Admin"]})
        request = _make_request(auth_header=f"Bearer {token}")
        payload = await require_admin_realm(request)
        assert payload["realm"] == "org"

    async def test_realm_org_with_no_admin_role_raises_403(self):
        token = _make_jwt({"sub": "u-1", "realm": "org", "roles": ["analyst"]})
        request = _make_request(auth_header=f"Bearer {token}")
        with pytest.raises(HTTPException) as exc:
            await require_admin_realm(request)
        assert exc.value.status_code == 403
        assert "Admin role required" in exc.value.detail

    async def test_realm_org_with_empty_roles_raises_403(self):
        """Pin the `roles = payload.get('roles', [])` default branch."""
        token = _make_jwt({"sub": "u-1", "realm": "org"})  # no roles key
        request = _make_request(auth_header=f"Bearer {token}")
        with pytest.raises(HTTPException) as exc:
            await require_admin_realm(request)
        assert exc.value.status_code == 403

    async def test_realm_org_with_anonymous_user_id_falls_through_to_403(self):
        """Edge: token has realm=org but no sub field. The role check fires
        (no roles) and logs 'unknown' for user_id. Pins the `or 'unknown'`
        default."""
        token = _make_jwt({"realm": "org", "roles": []})  # no sub
        request = _make_request(auth_header=f"Bearer {token}")
        with pytest.raises(HTTPException) as exc:
            await require_admin_realm(request)
        assert exc.value.status_code == 403

    async def test_realm_public_raises_403_with_distinct_message(self):
        token = _make_jwt({"sub": "u-pub", "realm": "public"})
        request = _make_request(auth_header=f"Bearer {token}")
        with pytest.raises(HTTPException) as exc:
            await require_admin_realm(request)
        assert exc.value.status_code == 403
        assert "Public users cannot access admin routes" in exc.value.detail

    async def test_realm_public_with_missing_sub_logs_unknown(self):
        """Pin the `payload.get('sub', 'unknown')` default in the public-realm
        warning branch."""
        token = _make_jwt({"realm": "public"})
        request = _make_request(auth_header=f"Bearer {token}")
        with pytest.raises(HTTPException) as exc:
            await require_admin_realm(request)
        assert exc.value.status_code == 403

    async def test_realm_tenant_legacy_rejected_as_invalid(self):
        """Post-Phase-1.7: legacy 'tenant' realm string is NOT in the
        allowed list. Pin this so a regression that re-adds 'tenant' fails
        loudly."""
        token = _make_jwt({"sub": "u-1", "realm": "tenant"})
        request = _make_request(auth_header=f"Bearer {token}")
        with pytest.raises(HTTPException) as exc:
            await require_admin_realm(request)
        assert exc.value.status_code == 403
        assert "Invalid realm" in exc.value.detail

    async def test_realm_missing_treated_as_invalid(self):
        """Token without a realm key → realm is None → fails the
        `not in ['admin','org']` check."""
        token = _make_jwt({"sub": "u-1"})
        request = _make_request(auth_header=f"Bearer {token}")
        with pytest.raises(HTTPException) as exc:
            await require_admin_realm(request)
        assert exc.value.status_code == 403
        assert "Invalid realm" in exc.value.detail

    async def test_missing_auth_header_propagates_401(self):
        request = _make_request(auth_header=None)
        with pytest.raises(HTTPException) as exc:
            await require_admin_realm(request)
        assert exc.value.status_code == 401

    async def test_malformed_token_propagates_401(self):
        request = _make_request(auth_header="Bearer not.a.jwt")
        with pytest.raises(HTTPException) as exc:
            await require_admin_realm(request)
        assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# require_global_admin
# ---------------------------------------------------------------------------


class TestRequireGlobalAdmin:
    async def test_role_admin_passes(self):
        token = _make_jwt({"sub": "u-1", "role": "admin", "realm": "org"})
        request = _make_request(auth_header=f"Bearer {token}")
        payload = await require_global_admin(request)
        assert payload["role"] == "admin"

    async def test_realm_admin_passes(self):
        token = _make_jwt({"sub": "u-1", "role": "user", "realm": "admin"})
        request = _make_request(auth_header=f"Bearer {token}")
        payload = await require_global_admin(request)
        assert payload["realm"] == "admin"

    async def test_neither_admin_nor_admin_realm_raises_403(self):
        token = _make_jwt({"sub": "u-1", "role": "analyst", "realm": "org"})
        request = _make_request(auth_header=f"Bearer {token}")
        with pytest.raises(HTTPException) as exc:
            await require_global_admin(request)
        assert exc.value.status_code == 403
        assert "Global admin access required" in exc.value.detail

    async def test_empty_role_and_realm_raises_403(self):
        """Token with no role/realm fields → both default to '' → rejected.
        Pins the `payload.get('role', '')` / `payload.get('realm', '')`
        defaults."""
        token = _make_jwt({"sub": "u-1"})
        request = _make_request(auth_header=f"Bearer {token}")
        with pytest.raises(HTTPException) as exc:
            await require_global_admin(request)
        assert exc.value.status_code == 403

    async def test_missing_sub_logs_unknown(self):
        token = _make_jwt({"role": "analyst", "realm": "org"})
        request = _make_request(auth_header=f"Bearer {token}")
        with pytest.raises(HTTPException) as exc:
            await require_global_admin(request)
        assert exc.value.status_code == 403
