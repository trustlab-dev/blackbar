"""Smoke tests for the test infrastructure itself."""

from __future__ import annotations

import pytest


@pytest.mark.integration
async def test_mongo_testcontainer_responds(db) -> None:
    """The MongoDB testcontainer is reachable and basic ops work."""
    await db.smoke.insert_one({"hello": "world"})
    doc = await db.smoke.find_one({"hello": "world"})
    assert doc is not None
    assert doc["hello"] == "world"


@pytest.mark.integration
async def test_db_isolation_between_tests_part_1(db) -> None:
    """Inserts a doc that the next test will fail to see if isolation works."""
    await db.isolation_check.insert_one({"id": "phase-2"})
    count = await db.isolation_check.count_documents({})
    assert count == 1


@pytest.mark.integration
async def test_db_isolation_between_tests_part_2(db) -> None:
    """If isolation is broken, this finds the doc from the previous test."""
    count = await db.isolation_check.count_documents({})
    assert count == 0


def test_app_imports(app) -> None:
    """FastAPI app boots without errors under test env."""
    routes = [r.path for r in app.routes if hasattr(r, "path")]
    assert any("/api/v1" in r for r in routes), "API router missing"


def test_unauth_client(client) -> None:
    """An unauthed health check works (no JWT required)."""
    r = client.get("/health")
    assert r.status_code in (200, 503)  # 503 if DB ping fails before fixtures wire it


@pytest.mark.integration
async def test_authed_client_factory_calls_protected_route(
    authed_client_factory,
) -> None:
    """Pins the post-I1 factory shape: returns an `httpx.AsyncClient` that
    can drive a real auth-required route end-to-end through the ASGI stack.

    `/api/v1/auth/roles` requires AuthMiddleware to accept the JWT but does
    not itself touch Mongo, so this test verifies the JWT plumbing through
    middleware without depending on per-test DB rebinds in route modules.
    """
    client = await authed_client_factory(role="analyst")
    r = await client.get("/api/v1/auth/roles")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "roles" in body
    role_ids = {role["id"] for role in body["roles"]}
    assert {"admin", "analyst", "user", "guest"}.issubset(role_ids)
