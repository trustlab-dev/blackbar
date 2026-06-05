"""Tests for `src.core.correlation`.

Covers:
- `generate_correlation_id` / `get_correlation_id` / `set_correlation_id`
- `CorrelationMiddleware.dispatch` (full lifecycle: header propagation,
  generation, state binding, metrics inc/dec, response-header emit)
- `MetricsMiddleware.dispatch` (lightweight variant; skips /metrics)
- `_normalize_path` (UUID / ObjectId / numeric ID rewriting)
- Exception path (5xx mapping when call_next raises)

Strategy: build a tiny FastAPI app with the middleware mounted and a
mix of routes (happy path, ID-bearing path, error path, /metrics).
Drive through `httpx.AsyncClient` + `ASGITransport`.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport

from src.core.correlation import (
    CORRELATION_ID_HEADER,
    REQUEST_ID_HEADER,
    CorrelationMiddleware,
    MetricsMiddleware,
    correlation_id_ctx,
    generate_correlation_id,
    get_correlation_id,
    set_correlation_id,
)

# ---------------------------------------------------------------------------
# Pure helpers (no middleware lifecycle)
# ---------------------------------------------------------------------------


class TestPureHelpers:
    def test_generate_correlation_id_is_uuid_shape(self):
        cid = generate_correlation_id()
        # UUIDs are 36 chars: 8-4-4-4-12
        assert len(cid) == 36
        assert cid.count("-") == 4

    def test_generate_correlation_id_is_unique(self):
        a = generate_correlation_id()
        b = generate_correlation_id()
        assert a != b

    def test_set_and_get_correlation_id(self):
        # Reset contextvar fresh
        token = correlation_id_ctx.set(None)
        try:
            assert get_correlation_id() is None
            set_correlation_id("custom-id-1")
            assert get_correlation_id() == "custom-id-1"
        finally:
            correlation_id_ctx.reset(token)


# ---------------------------------------------------------------------------
# CorrelationMiddleware end-to-end (with a real FastAPI app + httpx)
# ---------------------------------------------------------------------------


def _make_corr_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CorrelationMiddleware)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    @app.get("/cases/{case_id}")
    async def get_case(case_id: str):
        return {"id": case_id}

    @app.get("/boom")
    async def boom():
        raise HTTPException(status_code=500, detail="boom")

    @app.get("/raise")
    async def raise_route():
        raise RuntimeError("explode")

    return app


@pytest.fixture
async def corr_client():
    app = _make_corr_app()
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


class TestCorrelationMiddleware:
    async def test_generates_id_when_no_header(self, corr_client):
        r = await corr_client.get("/ping")
        assert r.status_code == 200
        cid = r.headers[CORRELATION_ID_HEADER]
        # generated UUID shape
        assert len(cid) == 36
        # also echoed via X-Request-ID
        assert r.headers[REQUEST_ID_HEADER] == cid
        # X-Response-Time header present
        assert "X-Response-Time" in r.headers

    async def test_propagates_correlation_id_header(self, corr_client):
        r = await corr_client.get("/ping", headers={CORRELATION_ID_HEADER: "preset-1"})
        assert r.headers[CORRELATION_ID_HEADER] == "preset-1"
        assert r.headers[REQUEST_ID_HEADER] == "preset-1"

    async def test_falls_back_to_request_id_header(self, corr_client):
        """X-Correlation-ID absent, but X-Request-ID present → use it."""
        r = await corr_client.get("/ping", headers={REQUEST_ID_HEADER: "alt-id-7"})
        assert r.headers[CORRELATION_ID_HEADER] == "alt-id-7"

    async def test_uuid_path_gets_normalized_in_metrics(self, corr_client):
        """Hit a UUID-bearing path. We can't easily read the labels here
        without scraping /metrics, but the request must succeed without
        crashing the _normalize_path regex."""
        r = await corr_client.get("/cases/12345678-1234-1234-1234-123456789012")
        assert r.status_code == 200

    async def test_objectid_path_does_not_crash(self, corr_client):
        """24-hex MongoDB ObjectId in path."""
        r = await corr_client.get("/cases/507f1f77bcf86cd799439011")
        assert r.status_code == 200

    async def test_numeric_id_path_does_not_crash(self, corr_client):
        r = await corr_client.get("/cases/42")
        assert r.status_code == 200

    async def test_http_exception_response_still_emits_corr_id(self, corr_client):
        r = await corr_client.get("/boom")
        # FastAPI default exception handler returns 500
        assert r.status_code == 500
        assert CORRELATION_ID_HEADER in r.headers

    async def test_unhandled_exception_propagates(self, corr_client):
        """The middleware re-raises after recording metrics. Without a
        catching ExceptionMiddleware above it, the RuntimeError propagates
        out of the ASGI stack (httpx surfaces it directly). The point of
        the test is that the `except` branch executes and the `finally`
        block still records metrics; behavior is asserted by reaching this
        test under 100% branch coverage."""
        with pytest.raises(RuntimeError, match="explode"):
            await corr_client.get("/raise")


# ---------------------------------------------------------------------------
# CorrelationMiddleware._normalize_path — direct unit tests
# ---------------------------------------------------------------------------


class TestNormalizePath:
    def setup_method(self):
        # The method is defined on instances but doesn't use self state.
        # Build a dummy instance bound to a no-op ASGI callable.
        self.mw = CorrelationMiddleware(app=lambda *a, **kw: None)

    def test_replaces_uuid(self):
        path = "/cases/12345678-1234-1234-1234-123456789012/docs"
        assert self.mw._normalize_path(path) == "/cases/{id}/docs"

    def test_replaces_objectid(self):
        path = "/cases/507f1f77bcf86cd799439011"
        assert self.mw._normalize_path(path) == "/cases/{id}"

    def test_replaces_numeric_id(self):
        assert self.mw._normalize_path("/cases/42") == "/cases/{id}"

    def test_replaces_numeric_id_mid_path(self):
        assert self.mw._normalize_path("/cases/42/docs") == "/cases/{id}/docs"

    def test_static_path_unchanged(self):
        assert self.mw._normalize_path("/health") == "/health"


# ---------------------------------------------------------------------------
# MetricsMiddleware
# ---------------------------------------------------------------------------


def _make_metrics_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(MetricsMiddleware)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    @app.get("/metrics")
    async def metrics():
        return {"prometheus": "stub"}

    @app.get("/boom")
    async def boom():
        raise RuntimeError("explode")

    @app.get("/cases/{case_id}")
    async def get_case(case_id: str):
        return {"id": case_id}

    return app


@pytest.fixture
async def metrics_client():
    app = _make_metrics_app()
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


class TestMetricsMiddleware:
    async def test_metrics_endpoint_skips_middleware(self, metrics_client):
        """The /metrics path is short-circuited (no normalization, no
        timing). Returns the stub directly."""
        r = await metrics_client.get("/metrics")
        assert r.status_code == 200

    async def test_normal_path_runs_through_middleware(self, metrics_client):
        r = await metrics_client.get("/ping")
        assert r.status_code == 200

    async def test_uuid_path_normalized_no_crash(self, metrics_client):
        r = await metrics_client.get("/cases/12345678-1234-1234-1234-123456789012")
        assert r.status_code == 200

    async def test_objectid_path_normalized_no_crash(self, metrics_client):
        r = await metrics_client.get("/cases/507f1f77bcf86cd799439011")
        assert r.status_code == 200

    async def test_numeric_path_normalized_no_crash(self, metrics_client):
        r = await metrics_client.get("/cases/7")
        assert r.status_code == 200

    async def test_unhandled_exception_propagates(self, metrics_client):
        """Same as CorrelationMiddleware: re-raises without a higher-level
        exception handler, surfacing to httpx."""
        with pytest.raises(RuntimeError, match="explode"):
            await metrics_client.get("/boom")


class TestMetricsMiddlewareNormalizePath:
    def setup_method(self):
        self.mw = MetricsMiddleware(app=lambda *a, **kw: None)

    def test_uuid_replaced(self):
        assert (
            self.mw._normalize_path("/cases/12345678-1234-1234-1234-123456789012") == "/cases/{id}"
        )

    def test_objectid_replaced(self):
        assert self.mw._normalize_path("/cases/507f1f77bcf86cd799439011") == "/cases/{id}"

    def test_numeric_replaced(self):
        assert self.mw._normalize_path("/cases/42") == "/cases/{id}"

    def test_static_unchanged(self):
        assert self.mw._normalize_path("/health") == "/health"
