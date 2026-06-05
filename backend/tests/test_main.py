"""Smoke tests for `src.main` — FastAPI app construction & startup events.

Target: ≥70% coverage. The module is mostly app setup + router wiring +
a small `/`, `/health`, and security-headers middleware. We don't try to
re-test every router or the full middleware lifecycle here — that's
covered by `tests/core/test_*` and the per-feature route tests.

Covers:
- Module imports cleanly and exposes `app` as a FastAPI instance.
- The `/` root route returns the welcome JSON.
- `/health` healthy path (db ping ok).
- `/health` unhealthy path (db ping raises).
- Security headers added on every response.
- Startup event runs without exception (init_telemetry, create_indexes,
  seed_default_templates all mocked).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

# ---------------------------------------------------------------------------
# Module-level smoke
# ---------------------------------------------------------------------------


def test_app_is_fastapi(app: FastAPI):
    """The `app` fixture from conftest yields the real src.main:app. Pin
    that it's a FastAPI instance with the expected base shape."""
    assert isinstance(app, FastAPI)
    # Has the expected exception handlers registered
    assert app.exception_handlers


def test_api_router_includes_versioned_prefix(app: FastAPI):
    """Smoke-check that at least some routes are mounted under /api/v1."""
    paths = [r.path for r in app.routes if hasattr(r, "path")]
    api_paths = [p for p in paths if p.startswith("/api/v1")]
    assert len(api_paths) > 0


def test_root_route_registered(app: FastAPI):
    paths = [r.path for r in app.routes if hasattr(r, "path")]
    assert "/" in paths


def test_health_route_registered(app: FastAPI):
    paths = [r.path for r in app.routes if hasattr(r, "path")]
    assert "/health" in paths


def test_metrics_route_registered(app: FastAPI):
    paths = [r.path for r in app.routes if hasattr(r, "path")]
    assert "/metrics" in paths


# ---------------------------------------------------------------------------
# HTTP-driven smoke (via httpx + ASGITransport)
# ---------------------------------------------------------------------------


@pytest.fixture
async def main_client(app: FastAPI):
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


async def test_root_returns_welcome(main_client: httpx.AsyncClient):
    r = await main_client.get("/")
    assert r.status_code == 200
    assert r.json() == {"message": "FOI Document API"}


async def test_root_response_has_security_headers(main_client: httpx.AsyncClient):
    """The `add_security_headers` middleware should set these on every
    response."""
    r = await main_client.get("/")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-XSS-Protection"] == "1; mode=block"
    assert "Strict-Transport-Security" in r.headers
    assert r.headers["Content-Security-Policy"] == "default-src 'self'"


async def test_health_endpoint_healthy(main_client: httpx.AsyncClient):
    r = await main_client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert body["database"] == "connected"
    assert "timestamp" in body
    assert "correlation_id" in body


async def test_health_endpoint_unhealthy_when_db_down(
    monkeypatch: pytest.MonkeyPatch, main_client: httpx.AsyncClient
):
    """Force the `db.command('ping')` call to raise. The handler re-imports
    `db` from `src.database` inside the function body, so we monkeypatch
    that module's `db` attribute."""
    import src.database as db_mod

    class _BrokenDb:
        async def command(self, *args, **kwargs):
            raise RuntimeError("mongo down")

    monkeypatch.setattr(db_mod, "db", _BrokenDb())

    r = await main_client.get("/health")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "unhealthy"
    assert body["database"] == "disconnected"
    assert "mongo down" in body["error"]


# ---------------------------------------------------------------------------
# Startup event — drive via lifespan / direct call
# ---------------------------------------------------------------------------


async def test_startup_event_runs_without_exception(monkeypatch: pytest.MonkeyPatch, db):
    """Call the registered startup handler directly. All the heavy
    side-effect functions (init_telemetry, create_indexes,
    seed_default_templates) are mocked to no-ops."""
    import src.main as main_mod

    # Replace the side-effect functions in their import sources.
    monkeypatch.setattr("src.core.telemetry.init_telemetry", MagicMock())
    monkeypatch.setattr("src.core.database.create_indexes", AsyncMock(return_value=None))
    monkeypatch.setattr(
        "src.utils.seed_templates.seed_default_templates",
        AsyncMock(return_value=None),
    )
    # UsersRepository.create_indexes is async; stub it too.
    monkeypatch.setattr(
        "src.users.repository.UsersRepository.create_indexes",
        AsyncMock(return_value=None),
    )

    # The startup handlers are registered via @app.on_event. They live on
    # app.router.on_startup. Find ours and invoke it.
    startup_handlers = main_mod.app.router.on_startup
    assert len(startup_handlers) > 0
    for handler in startup_handlers:
        await handler()
