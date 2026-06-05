"""
Correlation ID Middleware for BlackBar

Provides request tracing across services by:
- Generating unique correlation IDs for each request
- Propagating correlation IDs from incoming headers
- Adding correlation IDs to response headers
- Making correlation IDs available in request state
"""

import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.core.telemetry import (
    add_span_attributes,
    http_request_duration_seconds,
    http_requests_in_progress,
    http_requests_total,
)

# Context variable for correlation ID (thread-safe)
correlation_id_ctx: ContextVar[str | None] = ContextVar("correlation_id", default=None)

# Header names
CORRELATION_ID_HEADER = "X-Correlation-ID"
REQUEST_ID_HEADER = "X-Request-ID"


def get_correlation_id() -> str | None:
    """Get the current correlation ID from context."""
    return correlation_id_ctx.get()


def set_correlation_id(correlation_id: str) -> None:
    """Set the correlation ID in context."""
    correlation_id_ctx.set(correlation_id)


def generate_correlation_id() -> str:
    """Generate a new correlation ID."""
    return str(uuid.uuid4())


class CorrelationMiddleware(BaseHTTPMiddleware):
    """
    Middleware that handles correlation IDs and request metrics.

    Features:
    - Extracts or generates correlation ID for each request
    - Records HTTP metrics (requests, duration, in-progress)
    - Adds correlation ID to response headers
    - Makes correlation ID available via request.state
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Extract or generate correlation ID
        correlation_id = (
            request.headers.get(CORRELATION_ID_HEADER)
            or request.headers.get(REQUEST_ID_HEADER)
            or generate_correlation_id()
        )

        # Set in context var (for logging and other uses)
        set_correlation_id(correlation_id)

        # Add to request state for easy access
        request.state.correlation_id = correlation_id

        # Get endpoint path for metrics (normalize dynamic segments)
        endpoint = self._normalize_path(request.url.path)
        method = request.method

        # Add to current trace span
        add_span_attributes(
            {
                "correlation.id": correlation_id,
                "http.method": method,
                "http.url": str(request.url),
            }
        )

        # Track in-progress requests
        http_requests_in_progress.labels(method=method, endpoint=endpoint).inc()

        # Record request timing
        start_time = time.perf_counter()

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            status_code = 500
            raise
        finally:
            # Calculate duration
            duration = time.perf_counter() - start_time

            # Record metrics
            http_requests_total.labels(
                method=method, endpoint=endpoint, status=str(status_code)
            ).inc()

            http_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(duration)

            http_requests_in_progress.labels(method=method, endpoint=endpoint).dec()

        # Add correlation ID to response headers
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        response.headers[REQUEST_ID_HEADER] = correlation_id

        # Add timing header (useful for debugging)
        response.headers["X-Response-Time"] = f"{duration:.3f}s"

        return response

    def _normalize_path(self, path: str) -> str:
        """
        Normalize URL path for metrics labels.
        Replaces dynamic segments (UUIDs, IDs) with placeholders.
        """
        import re

        # Replace UUIDs
        path = re.sub(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            "{id}",
            path,
            flags=re.IGNORECASE,
        )

        # Replace MongoDB ObjectIds (24 hex chars)
        path = re.sub(r"[0-9a-f]{24}", "{id}", path, flags=re.IGNORECASE)

        # Replace numeric IDs
        path = re.sub(r"/\d+(?=/|$)", "/{id}", path)

        return path


class MetricsMiddleware(BaseHTTPMiddleware):
    """
    Lightweight middleware for just metrics (if correlation is handled elsewhere).
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip metrics endpoint to avoid recursion
        if request.url.path == "/metrics":
            return await call_next(request)

        endpoint = self._normalize_path(request.url.path)
        method = request.method

        start_time = time.perf_counter()

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            status_code = 500
            raise
        finally:
            duration = time.perf_counter() - start_time

            http_requests_total.labels(
                method=method, endpoint=endpoint, status=str(status_code)
            ).inc()

            http_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(duration)

        return response

    def _normalize_path(self, path: str) -> str:
        """Normalize URL path for metrics labels."""
        import re

        path = re.sub(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            "{id}",
            path,
            flags=re.IGNORECASE,
        )
        path = re.sub(r"[0-9a-f]{24}", "{id}", path, flags=re.IGNORECASE)
        path = re.sub(r"/\d+(?=/|$)", "/{id}", path)
        return path
