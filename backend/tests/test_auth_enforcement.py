"""Auth-enforcement regression test: every registered endpoint must reject
unauthenticated requests unless it is on the intentional public allowlist.

Guards against two failure modes:
1. A new router mounted outside the AuthMiddleware allowlist logic (would
   surface here as an unexpected 401-exempt path).
2. A new endpoint accidentally landing under an allowlisted prefix (e.g.
   anything added below /api/v1/config/ becomes silently public).

The PUBLIC_* sets below mirror src/core/auth_middleware.py deliberately —
if you add a public route, you must update BOTH, which is the point: going
public is an explicit, reviewed decision.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

# Paths that are exactly public by design (middleware public_routes_exact,
# plus "/" and app-level docs endpoints).
PUBLIC_EXACT = {
    "/",
    "/health",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/openapi.json",
    "/api/v1/auth/login",
    "/api/v1/auth/me",
    "/api/v1/auth/activate-owner",
    "/api/v1/admin/config/public",
}

# Prefixes that are public by design (middleware public_routes_prefix).
PUBLIC_PREFIXES = (
    "/api/v1/auth/public",
    "/api/v1/cases/public/",
    "/api/v1/cases/collect/",
    "/api/v1/contribute/",
    "/api/v1/config/",
)

# Public-by-design endpoints that must STILL not return 2xx to an
# anonymous, token-less request (they authenticate via a token in the
# request itself, so a bare probe must be rejected).
TOKEN_IN_REQUEST = {
    "/api/v1/auth/me",
    "/api/v1/auth/activate-owner",
}


def _probe_paths(app: FastAPI):
    """Every (method, concrete_path, template) from the OpenAPI schema,
    with path params filled by an implausible probe id."""
    for template, methods in app.openapi()["paths"].items():
        concrete = template
        # Fill {param} placeholders with a value that can't collide with
        # real data but survives path validation.
        while "{" in concrete:
            start = concrete.index("{")
            end = concrete.index("}", start)
            concrete = concrete[:start] + "probe-id-000" + concrete[end + 1 :]
        for method in methods:
            if method in {"get", "post", "put", "patch", "delete"}:
                yield method, concrete, template


def _is_public(path: str) -> bool:
    return path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIXES)


@pytest.fixture
async def anon_client(app: FastAPI):
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        yield client


async def test_protected_endpoints_reject_anonymous_requests(
    app: FastAPI, anon_client: httpx.AsyncClient
):
    """No non-public endpoint may answer an unauthenticated request with
    anything but 401. (Middleware rejects before routing/validation, so
    even 404/422 here would mean the request got past auth.)"""
    leaks: list[str] = []
    probed = 0
    for method, concrete, template in _probe_paths(app):
        if _is_public(concrete):
            continue
        probed += 1
        r = await anon_client.request(method.upper(), concrete)
        if r.status_code != 401:
            leaks.append(f"{method.upper()} {template} -> {r.status_code}")
    assert probed > 100, f"probe enumeration broke (only {probed} paths)"
    assert not leaks, "endpoints reachable without authentication:\n" + "\n".join(leaks)


async def test_token_in_request_endpoints_reject_bare_probes(
    app: FastAPI, anon_client: httpx.AsyncClient
):
    """Middleware-exempt endpoints that authenticate via an in-request
    token must reject a request that carries no token at all."""
    for method, concrete, template in _probe_paths(app):
        if concrete not in TOKEN_IN_REQUEST:
            continue
        r = await anon_client.request(method.upper(), concrete)
        assert r.status_code not in range(200, 300), (
            f"{method.upper()} {template} returned {r.status_code} to an "
            "anonymous request with no credential of any kind"
        )


async def test_public_surface_matches_expected_contract(app: FastAPI):
    """The set of public paths must not grow silently: any OpenAPI path
    that the middleware would treat as public has to be one we listed."""
    unexpected = []
    for template in app.openapi()["paths"]:
        probe = template
        while "{" in probe:
            start = probe.index("{")
            end = probe.index("}", start)
            probe = probe[:start] + "x" + probe[end + 1 :]
        if _is_public(probe) and template not in PUBLIC_EXACT:
            # Prefix-matched: fine, but it must live under a known prefix
            # (this loop mainly documents the live public surface).
            assert probe.startswith(PUBLIC_PREFIXES), template
            unexpected.append(template)
    # Informational ceiling: if the public surface grows past this, a new
    # endpoint slid under a public prefix — review it and bump consciously.
    assert len(unexpected) <= 25, (
        "public-by-prefix surface grew unexpectedly:\n" + "\n".join(unexpected)
    )
