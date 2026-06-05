"""
Centralized error handling utilities.
Implements standard error format per CODING_STANDARDS.md
"""

import logging
import uuid
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def generate_correlation_id() -> str:
    """Generate a unique correlation ID for request tracking."""
    return str(uuid.uuid4())


def create_error_response(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    status_code: int = 400,
) -> dict[str, Any]:
    """
    Create a standardized error response.

    Args:
        code: Error code (e.g., "VALIDATION_ERROR", "NOT_FOUND")
        message: Human-readable error message
        details: Additional error details
        correlation_id: Unique ID for tracking (auto-generated if not provided)
        status_code: HTTP status code

    Returns:
        Standardized error response dict
    """
    if correlation_id is None:
        correlation_id = generate_correlation_id()

    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "correlation_id": correlation_id,
        }
    }


class StandardHTTPException(HTTPException):
    """
    HTTPException that follows the standard error format.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ):
        self.correlation_id = correlation_id or generate_correlation_id()
        detail = create_error_response(
            code=code,
            message=message,
            details=details,
            correlation_id=self.correlation_id,
            status_code=status_code,
        )
        super().__init__(status_code=status_code, detail=detail)


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """
    Global HTTP exception handler that ensures standard error format.
    """
    correlation_id = generate_correlation_id()

    # If the exception already has our standard format, use it
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)

    # Otherwise, wrap it in standard format
    error_response = create_error_response(
        code=f"HTTP_{exc.status_code}",
        message=str(exc.detail) if exc.detail else "An error occurred",
        correlation_id=correlation_id,
        status_code=exc.status_code,
    )

    # Log the error with correlation ID
    logger.error(
        f"HTTP {exc.status_code}: {exc.detail}",
        extra={
            "correlation_id": correlation_id,
            "path": request.url.path,
            "method": request.method,
        },
    )

    return JSONResponse(status_code=exc.status_code, content=error_response)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """
    Handle validation errors with standard format.
    """
    correlation_id = generate_correlation_id()

    # Pydantic V2's RequestValidationError.errors() can carry a
    # non-JSON-serializable ValueError instance in ctx.error for custom
    # validators that `raise ValueError(...)`. Run the output through
    # jsonable_encoder with a fallback that stringifies Exception
    # instances so JSONResponse never crashes (B8 fixed 2026-05-12).
    serializable_errors = jsonable_encoder(
        exc.errors(),
        custom_encoder={Exception: str},
    )

    error_response = create_error_response(
        code="VALIDATION_ERROR",
        message="Invalid request data",
        details={"errors": serializable_errors},
        correlation_id=correlation_id,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )

    logger.error(
        f"Validation error: {serializable_errors}",
        extra={
            "correlation_id": correlation_id,
            "path": request.url.path,
            "method": request.method,
        },
    )

    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=error_response)


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Handle unexpected exceptions with standard format.
    """
    correlation_id = generate_correlation_id()

    error_response = create_error_response(
        code="INTERNAL_ERROR",
        message="An unexpected error occurred",
        details={"type": type(exc).__name__},
        correlation_id=correlation_id,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )

    logger.exception(
        f"Unexpected error: {str(exc)}",
        extra={
            "correlation_id": correlation_id,
            "path": request.url.path,
            "method": request.method,
        },
    )

    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=error_response)
