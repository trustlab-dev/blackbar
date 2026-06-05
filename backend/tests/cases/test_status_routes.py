"""Integration tests for `src.cases.status_routes` endpoints.

Phase 2.2.D (3/3). Target >=80% line coverage on src.cases.status_routes.

Endpoints under test (mounted at /api/v1/config/...):
    GET    /statuses     -- pack-driven status enum
    GET    /priorities   -- pack-driven priority enum
    GET    /timelines    -- pack-driven timeline config

These endpoints describe themselves as "Public endpoint - no auth
required". B19 fix (2026-05-12) added `/api/v1/config/` to the
AuthMiddleware ``public_routes_prefix`` allowlist so the docstring is
now accurate. The endpoints return enum-style reference data with zero
PII — used by the public request form (status pickers before login)
and frontend init. Unauthenticated callers get 200.
"""

from __future__ import annotations

from httpx import AsyncClient

# ---------------------------------------------------------------------------
# GET /api/v1/config/statuses
# ---------------------------------------------------------------------------


class TestStatuses:
    async def test_admin_can_get_statuses(self, authed_client_factory) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/config/statuses")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "statuses" in body
        assert isinstance(body["statuses"], list)

    async def test_statuses_is_public_no_auth_required(self, client) -> None:
        """Public endpoint — no JWT required (B19 fix, 2026-05-12)."""
        r = client.get("/api/v1/config/statuses")
        assert r.status_code == 200, r.text
        assert "statuses" in r.json()


# ---------------------------------------------------------------------------
# GET /api/v1/config/priorities
# ---------------------------------------------------------------------------


class TestPriorities:
    async def test_user_can_get_priorities(self, authed_client_factory) -> None:
        client: AsyncClient = await authed_client_factory(role="user")
        r = await client.get("/api/v1/config/priorities")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "priorities" in body

    async def test_priorities_is_public_no_auth_required(self, client) -> None:
        """Public endpoint — no JWT required (B19 fix, 2026-05-12)."""
        r = client.get("/api/v1/config/priorities")
        assert r.status_code == 200, r.text
        assert "priorities" in r.json()


# ---------------------------------------------------------------------------
# GET /api/v1/config/timelines
# ---------------------------------------------------------------------------


class TestTimelines:
    async def test_analyst_can_get_timelines(self, authed_client_factory) -> None:
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get("/api/v1/config/timelines")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "timelines" in body
        # Pack-driven; not asserting concrete keys beyond presence

    async def test_timelines_is_public_no_auth_required(self, client) -> None:
        """Public endpoint — no JWT required (B19 fix, 2026-05-12)."""
        r = client.get("/api/v1/config/timelines")
        assert r.status_code == 200, r.text
        assert "timelines" in r.json()
