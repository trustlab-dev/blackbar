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


# Versioned API prefix. Starlette no longer flattens included routers, so the
# matched route's template lacks the outer "/api/v1" router prefix.
API_PREFIX = "/api/v1"
UNMATCHED_ENDPOINT = "unmatched"
IN_FLIGHT_ENDPOINT = "all"


def route_template(request: Request) -> str:
    """Metric/span label for a request: the matched route template (e.g.
    ``/api/v1/cases/collect/{token}``), never the raw path.

    Raw paths carry capability tokens (collection links, release packages)
    and arbitrary attacker-chosen segments, which leaked into /metrics and
    gave unbounded label cardinality (AUTH-15). Requests that match no route
    share the single ``unmatched`` label.
    """
    route = request.scope.get("route")
    template = getattr(route, "path_format", None) or getattr(route, "path", None)
    if not template:
        return UNMATCHED_ENDPOINT
    if request.url.path.startswith(API_PREFIX + "/") and not template.startswith(API_PREFIX):
        template = API_PREFIX + template
    return template


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

        method = request.method

        # Add to current trace span. Never the raw URL: its path and query
        # string can carry capability tokens (AUTH-15).
        add_span_attributes({"correlation.id": correlation_id, "http.method": method})

        # The route is only known after routing, so the in-flight gauge uses a
        # constant endpoint label.
        http_requests_in_progress.labels(method=method, endpoint=IN_FLIGHT_ENDPOINT).inc()

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
            endpoint = route_template(request)

            # Record metrics
            http_requests_total.labels(
                method=method, endpoint=endpoint, status=str(status_code)
            ).inc()

            http_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(duration)

            http_requests_in_progress.labels(method=method, endpoint=IN_FLIGHT_ENDPOINT).dec()

            add_span_attributes({"http.route": endpoint})

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
            endpoint = route_template(request)

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
