"""Tests for `src.core.auth_middleware.AuthMiddleware`.

Critical-path security boundary. Target: 100% line + branch coverage.

Strategy: mount a tiny FastAPI app that includes the middleware and a
single `/protected` route. Drive it through `httpx.AsyncClient` +
`ASGITransport` so middleware dispatch runs end-to-end (no shortcuts).
Avoids the full `src.main` import to keep tests fast and isolated from
unrelated startup side effects.

Pins the post-Phase-1.8 allowlist (B9/B14/B19 fixes):
- exact: /api/v1/auth/login, /api/v1/auth/me, /api/v1/auth/activate-owner,
  /api/v1/admin/config/public
- prefix: /health, /docs, /openapi.json, /redoc, /api/v1/auth/public,
  /api/v1/cases/public/, /api/v1/cases/collect/, /api/v1/contribute/,
  /api/v1/config/
- frontend prefix: /request, /track/, /collect/, /contribute/
- and the literal "/" exact match
"""

from __future__ import annotations

import time

import httpx
import jwt
import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport

from src.config import ALGORITHM, JWT_SECRET
from src.core.auth_middleware import AuthMiddleware


def _make_app() -> FastAPI:
    """Build a minimal FastAPI app that has AuthMiddleware mounted plus a
    handful of routes whose paths land in (or outside of) the allowlist.

    The `/protected` route echoes back `request.state.user_id` and
    `request.state.roles` so tests can verify population.
    """
    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/protected")
    async def protected(request: Request):
        return {
            "user_id": getattr(request.state, "user_id", None),
            "roles": getattr(request.state, "roles", None),
        }

    @app.get("/api/v1/auth/login")
    async def login_route():
        return {"ok": "login"}

    @app.get("/api/v1/auth/me")
    async def me_route():
        return {"ok": "me"}

    @app.get("/api/v1/auth/activate-owner")
    async def activate_owner_route():
        return {"ok": "activate-owner"}

    @app.get("/api/v1/admin/config/public")
    async def admin_config_public_route():
        return {"ok": "admin-config-public"}

    @app.get("/health")
    async def health_route():
        return {"ok": "health"}

    @app.get("/docs")
    async def docs_route():
        return {"ok": "docs"}

    @app.get("/openapi.json")
    async def openapi_route():
        return {"ok": "openapi"}

    @app.get("/redoc")
    async def redoc_route():
        return {"ok": "redoc"}

    @app.get("/api/v1/auth/public/anything")
    async def auth_public_prefix_route():
        return {"ok": "auth-public-prefix"}

    @app.get("/api/v1/cases/public/list")
    async def cases_public_route():
        return {"ok": "cases-public"}

    @app.get("/api/v1/cases/collect/some-token")
    async def cases_collect_route():
        return {"ok": "cases-collect"}

    @app.get("/api/v1/contribute/foo")
    async def contribute_route():
        return {"ok": "contribute"}

    @app.get("/api/v1/config/statuses")
    async def config_statuses_route():
        return {"ok": "config-statuses"}

    @app.get("/request")
    async def request_route():
        return {"ok": "request"}

    @app.get("/track/abc")
    async def track_route():
        return {"ok": "track"}

    @app.get("/collect/abc")
    async def collect_frontend_route():
        return {"ok": "collect-frontend"}

    @app.get("/contribute/abc")
    async def contribute_frontend_route():
        return {"ok": "contribute-frontend"}

    @app.get("/")
    async def root_route():
        return {"ok": "root"}

    return app


@pytest.fixture
def mw_app() -> FastAPI:
    return _make_app()


@pytest.fixture
async def aclient(mw_app: FastAPI):
    transport = ASGITransport(app=mw_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


def _make_jwt(payload: dict, secret: str = JWT_SECRET) -> str:
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def _valid_token(user_id: str = "user-1", role: str = "analyst") -> str:
    future = int(time.time() + 600)
    return _make_jwt({"sub": user_id, "role": role, "realm": "org", "exp": future})


# ---------------------------------------------------------------------------
# Public route allowlist — bypasses auth entirely
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        # exact matches
        "/api/v1/auth/login",
        "/api/v1/auth/me",
        "/api/v1/auth/activate-owner",
        "/api/v1/admin/config/public",
        "/",
    ],
)
async def test_public_routes_exact_bypass_auth(aclient: httpx.AsyncClient, path: str):
    """Each exact-allowlist entry returns 200 with no Authorization header."""
    r = await aclient.get(path)
    assert r.status_code == 200, f"path={path} body={r.text}"


@pytest.mark.parametrize(
    "path",
    [
        # prefix matches — API
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/api/v1/auth/public/anything",
        "/api/v1/cases/public/list",
        "/api/v1/cases/collect/some-token",
        "/api/v1/contribute/foo",
        "/api/v1/config/statuses",
        # prefix matches — frontend
        "/request",
        "/track/abc",
        "/collect/abc",
        "/contribute/abc",
    ],
)
async def test_public_routes_prefix_bypass_auth(aclient: httpx.AsyncClient, path: str):
    """Each prefix-allowlist entry returns 200 with no Authorization header."""
    r = await aclient.get(path)
    assert r.status_code == 200, f"path={path} body={r.text}"


# ---------------------------------------------------------------------------
# Protected route — missing / malformed / invalid auth
# ---------------------------------------------------------------------------


async def test_protected_route_missing_auth_returns_401(aclient: httpx.AsyncClient):
    r = await aclient.get("/protected")
    assert r.status_code == 401
    body = r.json()
    assert body["error"]["code"] == "AUTH_REQUIRED"
    assert body["error"]["message"] == "Authentication required"
    # correlation_id falls back to "unknown" when CorrelationMiddleware isn't mounted
    assert "correlation_id" in body["error"]


@pytest.mark.parametrize(
    "auth_header",
    [
        "NotBearer abc.def.ghi",  # wrong scheme
        "Bearer",  # one part only
        "Bearer x y z",  # three parts
        "abc.def.ghi",  # bare token, no scheme
    ],
)
async def test_protected_route_malformed_auth_returns_401(
    aclient: httpx.AsyncClient, auth_header: str
):
    r = await aclient.get("/protected", headers={"Authorization": auth_header})
    assert r.status_code == 401
    body = r.json()
    assert body["error"]["code"] == "INVALID_AUTH_HEADER"
    assert body["error"]["message"] == "Invalid Authorization header format"


async def test_protected_route_invalid_token_returns_401(
    aclient: httpx.AsyncClient,
):
    r = await aclient.get("/protected", headers={"Authorization": "Bearer not.a.real.jwt"})
    assert r.status_code == 401
    body = r.json()
    assert body["error"]["code"] == "INVALID_TOKEN"
    assert body["error"]["message"] == "Invalid or expired token"


async def test_protected_route_expired_token_returns_401(
    aclient: httpx.AsyncClient,
):
    # `time.time()` is the correct UTC-anchored epoch. `datetime.utcnow()` is
    # naive and on Python 3.12+ its `.timestamp()` treats the value as local
    # time, which on non-UTC machines emits a future-shifted exp and the
    # token is NOT treated as expired (see audit Section 11 / pyproject
    # filterwarnings note on `datetime.utcnow`).
    past = int(time.time() - 600)
    token = _make_jwt({"sub": "u-1", "role": "analyst", "exp": past})
    r = await aclient.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    body = r.json()
    assert body["error"]["code"] == "INVALID_TOKEN"


async def test_protected_route_wrong_secret_token_returns_401(
    aclient: httpx.AsyncClient,
):
    """Token signed with a different secret -> validate_token returns None
    -> INVALID_TOKEN. Pins the JWTError->None branch in AuthService."""
    future = int(time.time() + 600)
    token = _make_jwt(
        {"sub": "u-1", "role": "analyst", "exp": future},
        secret="wrong-secret-also-32-chars-min-aaaaaaa",
    )
    r = await aclient.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    body = r.json()
    assert body["error"]["code"] == "INVALID_TOKEN"


# ---------------------------------------------------------------------------
# Protected route — valid token populates request.state
# ---------------------------------------------------------------------------


async def test_protected_route_valid_token_populates_state(
    aclient: httpx.AsyncClient,
):
    token = _valid_token(user_id="user-42", role="analyst")
    r = await aclient.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "user-42"
    assert body["roles"] == ["analyst"]


async def test_protected_route_valid_token_without_role_yields_empty_roles(
    aclient: httpx.AsyncClient,
):
    """validate_token() backfills role='user' for tokens missing the field,
    so request.state.roles should be `['user']`, not empty. Pins the
    `[token_payload.role] if token_payload.role else []` branch."""
    future = int(time.time() + 600)
    # No `role` key at all → validate_token() sets payload['role']='user'.
    token = _make_jwt({"sub": "u-7", "exp": future})
    r = await aclient.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "u-7"
    assert body["roles"] == ["user"]


async def test_lower_case_bearer_accepted(aclient: httpx.AsyncClient):
    """The middleware does parts[0].lower() == 'bearer' so 'bearer ...' works."""
    token = _valid_token(user_id="lower-1", role="admin")
    r = await aclient.get("/protected", headers={"Authorization": f"bearer {token}"})
    assert r.status_code == 200
    assert r.json()["user_id"] == "lower-1"


# ---------------------------------------------------------------------------
# Correlation-ID surfaces in error envelopes (when set upstream)
# ---------------------------------------------------------------------------


async def test_error_envelope_uses_correlation_id_when_set(mw_app: FastAPI):
    """If an earlier middleware set request.state.correlation_id, the error
    envelope echoes it back. We simulate that with a tiny inline middleware."""
    from starlette.middleware.base import BaseHTTPMiddleware

    class _SetCorr(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.correlation_id = "test-corr-id-123"
            return await call_next(request)

    # Mount AFTER AuthMiddleware so it runs first (FastAPI middleware ordering
    # is LIFO — the last-added runs outermost / earliest).
    mw_app.add_middleware(_SetCorr)

    transport = ASGITransport(app=mw_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.get("/protected")  # missing auth → AUTH_REQUIRED 401
        assert r.status_code == 401
        body = r.json()
        assert body["error"]["correlation_id"] == "test-corr-id-123"
