"""Tests for ``src.utils.error_handler``.

Regression coverage for B8 (Pydantic V2 ``ctx.error`` JSON serialization
crash, fixed 2026-05-12). Previously, any route with a custom
``@field_validator`` that raised ``ValueError`` returned 500 with a
TypeError when the ``validation_exception_handler`` tried to JSON-encode
the non-serializable ``ValueError`` inside ``ctx.error``. The handler
now runs ``exc.errors()`` through ``jsonable_encoder`` with an
Exception-to-str fallback.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, field_validator

from src.utils.error_handler import validation_exception_handler

# Phase 4 Batch 4.4 (audit B7): error_handler now uses
# `HTTP_422_UNPROCESSABLE_CONTENT`, the post-Starlette-0.45+ name. The
# DeprecationWarning filter from the pre-fix era is no longer needed.


class _ModelWithCustomValidator(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _no_forbidden(cls, v: str) -> str:
        if v == "forbidden":
            raise ValueError("forbidden-marker-string")
        return v


def _build_app() -> FastAPI:
    """Build an isolated FastAPI app wired with only the handler under test."""
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    @app.post("/check")
    async def check(payload: _ModelWithCustomValidator) -> dict[str, str]:
        return {"ok": payload.name}

    return app


def test_custom_validator_value_error_returns_422_not_500() -> None:
    """A ``raise ValueError`` from a custom validator must surface as 422.

    Pre-fix this returned 500 because the handler crashed JSON-encoding
    the ``ValueError`` instance Pydantic V2 placed in ``ctx.error``.
    """
    client = TestClient(_build_app())
    response = client.post("/check", json={"name": "forbidden"})

    assert response.status_code == 422
    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_custom_validator_error_message_survives_serialization() -> None:
    """The custom ValueError message must be retrievable in the response.

    The Exception-to-str fallback in jsonable_encoder stringifies the
    ValueError to its message, so the original "forbidden-marker-string"
    appears somewhere in the response payload.
    """
    client = TestClient(_build_app())
    response = client.post("/check", json={"name": "forbidden"})

    assert response.status_code == 422
    assert "forbidden-marker-string" in response.text


def test_standard_validation_error_still_returns_422() -> None:
    """A plain type-mismatch (no custom validator involved) is unaffected."""
    client = TestClient(_build_app())
    # Missing required field 'name' -> standard pydantic missing-field error
    response = client.post("/check", json={})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "errors" in body["error"]["details"]


def test_validation_error_envelope_includes_correlation_id() -> None:
    """The 422 response must carry a correlation_id per the envelope contract."""
    client = TestClient(_build_app())
    response = client.post("/check", json={"name": "forbidden"})

    assert response.status_code == 422
    assert response.json()["error"]["correlation_id"]


# ---------------------------------------------------------------------------
# Sub-phase 2.9 gap-fill: cover remaining error_handler helpers and the
# http / generic exception handlers.
# ---------------------------------------------------------------------------

from fastapi import HTTPException

from src.utils.error_handler import (
    StandardHTTPException,
    create_error_response,
    generate_correlation_id,
    generic_exception_handler,
    http_exception_handler,
)


class TestGenerateCorrelationId:
    def test_returns_uuid_string(self) -> None:
        cid = generate_correlation_id()
        assert isinstance(cid, str)
        # uuid4 has 4 hyphens and is 36 chars long
        assert cid.count("-") == 4
        assert len(cid) == 36

    def test_unique_each_call(self) -> None:
        ids = {generate_correlation_id() for _ in range(10)}
        assert len(ids) == 10


class TestCreateErrorResponse:
    def test_includes_all_fields(self) -> None:
        resp = create_error_response(
            code="VALIDATION_ERROR",
            message="bad input",
            details={"field": "email"},
            correlation_id="custom-id",
        )
        err = resp["error"]
        assert err["code"] == "VALIDATION_ERROR"
        assert err["message"] == "bad input"
        assert err["details"]["field"] == "email"
        assert err["correlation_id"] == "custom-id"

    def test_generates_correlation_id_when_omitted(self) -> None:
        resp = create_error_response(code="X", message="y")
        # Should not be empty
        assert resp["error"]["correlation_id"]
        # And different on each call
        resp2 = create_error_response(code="X", message="y")
        assert resp["error"]["correlation_id"] != resp2["error"]["correlation_id"]

    def test_empty_details_when_none(self) -> None:
        resp = create_error_response(code="X", message="y", details=None)
        assert resp["error"]["details"] == {}


class TestStandardHTTPException:
    def test_subclasses_http_exception_with_envelope(self) -> None:
        exc = StandardHTTPException(
            status_code=404,
            code="NOT_FOUND",
            message="missing",
            details={"id": "abc"},
        )
        assert isinstance(exc, HTTPException)
        assert exc.status_code == 404
        # detail is the standard envelope dict
        assert exc.detail["error"]["code"] == "NOT_FOUND"
        assert exc.detail["error"]["details"]["id"] == "abc"
        assert exc.correlation_id

    def test_custom_correlation_id_threads_through(self) -> None:
        exc = StandardHTTPException(
            status_code=400,
            code="X",
            message="y",
            correlation_id="cid-123",
        )
        assert exc.correlation_id == "cid-123"
        assert exc.detail["error"]["correlation_id"] == "cid-123"


class TestHttpExceptionHandler:
    """Direct unit tests on http_exception_handler — exercises both the
    "already-wrapped" and "needs-wrapping" branches."""

    @pytest.mark.asyncio
    async def test_passes_through_already_wrapped_detail(self) -> None:
        from unittest.mock import MagicMock

        req = MagicMock()
        req.url.path = "/x"
        req.method = "GET"
        exc = HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "correlation_id": "cid"}},
        )
        resp = await http_exception_handler(req, exc)
        assert resp.status_code == 404
        # JSONResponse.body is bytes; rough check via the body content
        assert b"NOT_FOUND" in resp.body

    @pytest.mark.asyncio
    async def test_wraps_plain_detail_in_envelope(self) -> None:
        from unittest.mock import MagicMock

        req = MagicMock()
        req.url.path = "/x"
        req.method = "POST"
        exc = HTTPException(status_code=400, detail="bad request")
        resp = await http_exception_handler(req, exc)
        assert resp.status_code == 400
        assert b"HTTP_400" in resp.body
        assert b"bad request" in resp.body

    @pytest.mark.asyncio
    async def test_no_detail_falls_back_to_default_message(self) -> None:
        """FastAPI's HTTPException auto-fills ``detail`` with a default
        when None is passed (HTTPException(500) -> 'Internal Server Error'),
        so the handler renders THAT message. Pin the actual behavior."""
        from unittest.mock import MagicMock

        req = MagicMock()
        req.url.path = "/x"
        req.method = "GET"
        exc = HTTPException(status_code=500, detail=None)
        resp = await http_exception_handler(req, exc)
        assert resp.status_code == 500
        # FastAPI fills in "Internal Server Error" by default for 500
        assert b"Internal Server Error" in resp.body


class TestGenericExceptionHandler:
    @pytest.mark.asyncio
    async def test_wraps_arbitrary_exception_in_500_envelope(self) -> None:
        from unittest.mock import MagicMock

        req = MagicMock()
        req.url.path = "/x"
        req.method = "GET"
        exc = ValueError("boom")
        resp = await generic_exception_handler(req, exc)
        assert resp.status_code == 500
        assert b"INTERNAL_ERROR" in resp.body
        assert b"ValueError" in resp.body  # type name in details
