"""Tests for `src.core.metrics_routes` — Prometheus exposition endpoint.

Tiny module (only `GET /metrics`). Target ≥80%.

Verifies:
- The endpoint returns 200 with Prometheus text-format content.
- Response includes at least one of the registered metrics
  (e.g. `http_requests_total` — registered at import time).
- Content-Type is the Prometheus exposition media type.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from prometheus_client import CONTENT_TYPE_LATEST

from src.core.metrics_routes import router


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
async def metrics_client():
    app = _make_app()
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


async def test_metrics_endpoint_returns_200(metrics_client):
    r = await metrics_client.get("/metrics")
    assert r.status_code == 200


async def test_metrics_endpoint_content_type_is_prometheus(metrics_client):
    r = await metrics_client.get("/metrics")
    # CONTENT_TYPE_LATEST is e.g. "text/plain; version=0.0.4; charset=utf-8"
    assert r.headers["content-type"] == CONTENT_TYPE_LATEST


async def test_metrics_body_includes_telemetry_counter(metrics_client):
    """When `src.core.telemetry` is imported, `http_requests_total` gets
    registered to the default registry and appears in the exposition.
    We import telemetry here explicitly to make the dependency obvious
    (the metrics_routes module itself doesn't import telemetry)."""
    import src.core.telemetry  # noqa: F401  — side-effect import

    r = await metrics_client.get("/metrics")
    body = r.text
    assert "http_requests_total" in body


async def test_metrics_body_includes_python_gc_default_metric(metrics_client):
    """The Python default registry always exposes GC metrics. Pin a
    framework-level metric so the test is robust to other module imports."""
    r = await metrics_client.get("/metrics")
    body = r.text
    assert "python_gc_objects_collected_total" in body


async def test_metrics_body_is_text_format(metrics_client):
    """Prometheus exposition format starts each metric with `# HELP` and
    `# TYPE` comments. Pin that we're producing the text format (vs JSON
    or anything else)."""
    r = await metrics_client.get("/metrics")
    body = r.text
    assert "# HELP" in body
    assert "# TYPE" in body
