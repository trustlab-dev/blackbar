"""
Authentication middleware
Validates JWT tokens and attaches user context to requests
"""

import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from src.auth.auth_service import AuthService

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware to validate JWT tokens and attach user context

    Extracts Bearer token from Authorization header
    Validates token and attaches user info to request.state
    Allows anonymous requests (no token required for some routes)
    """

    async def dispatch(self, request: Request, call_next):
        # Skip auth for public routes
        # /auth/activate-owner: invitation recipient has no JWT yet by design;
        # the route authenticates via the activation token in the request body.
        public_routes_exact = [
            "/api/v1/auth/login",
            "/api/v1/auth/me",
            "/api/v1/auth/activate-owner",
            "/api/v1/admin/config/public",
        ]

        public_routes_prefix = [
            "/health",
            "/docs",
            "/openapi.json",
            "/redoc",
            "/api/v1/auth/public",
            "/api/v1/cases/public/",
            # /cases/collect/{token} authenticates via request-body token,
            # not via JWT — same pattern as /auth/activate-owner above.
            "/api/v1/cases/collect/",
            "/api/v1/contribute/",
            # /api/v1/config/{statuses,priorities,timelines} return
            # enum-style reference data with zero PII. Used by the public
            # request form (status pickers before login) and by the
            # frontend at general init. Docstrings claim "Public endpoint
            # - no auth required"; this allowlist entry makes that true
            # (B19 fix, 2026-05-12).
            "/api/v1/config/",
        ]

        # Explicit public paths for frontend-served routes (not API endpoints)
        public_frontend_routes = [
            "/request",
            "/track/",
            "/collect/",
            "/contribute/",
        ]

        # Check exact matches first
        if request.url.path in public_routes_exact or request.url.path == "/":
            return await call_next(request)

        # Check prefix matches (API and frontend routes)
        if any(request.url.path.startswith(route) for route in public_routes_prefix) or any(
            request.url.path.startswith(route) for route in public_frontend_routes
        ):
            return await call_next(request)

        # Extract token from Authorization header
        auth_header = request.headers.get("Authorization")

        if not auth_header:
            # No token on a protected route — reject
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "AUTH_REQUIRED",
                        "message": "Authentication required",
                        "correlation_id": getattr(request.state, "correlation_id", "unknown"),
                    }
                },
            )

        # Parse Bearer token
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "INVALID_AUTH_HEADER",
                        "message": "Invalid Authorization header format",
                        "correlation_id": getattr(request.state, "correlation_id", "unknown"),
                    }
                },
            )

        token = parts[1]

        # Validate token
        token_payload = AuthService.validate_token(token)

        if not token_payload:
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "INVALID_TOKEN",
                        "message": "Invalid or expired token",
                        "correlation_id": getattr(request.state, "correlation_id", "unknown"),
                    }
                },
            )

        # Attach user context to request
        request.state.user_id = token_payload.sub
        request.state.roles = [token_payload.role] if token_payload.role else []

        logger.info(
            f"Authenticated user {token_payload.sub} with role {token_payload.role}",
            extra={
                "correlation_id": getattr(request.state, "correlation_id", "unknown"),
                "user_id": token_payload.sub,
            },
        )

        return await call_next(request)
