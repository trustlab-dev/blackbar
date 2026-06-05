"""
FastAPI dependencies for request context
"""

import logging

import jwt
from fastapi import HTTPException, Request
from jwt import InvalidTokenError as JWTError

from src.config import ALGORITHM, JWT_SECRET

logger = logging.getLogger(__name__)


def get_current_user_id(request: Request) -> str:
    """Get current user ID from request state (requires authentication)"""
    if not hasattr(request.state, "user_id") or not request.state.user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return request.state.user_id


def get_current_user_id_optional(request: Request) -> str | None:
    """Get current user ID from request state (optional)"""
    return getattr(request.state, "user_id", None)


def get_user_roles(request: Request) -> list[str]:
    """Get current user's roles"""
    return getattr(request.state, "roles", [])


def require_role(required_roles: list[str]):
    """
    Dependency factory to require specific roles

    Usage:
        @router.get("/admin-only", dependencies=[Depends(require_role(["admin"]))])
    """

    def role_checker(request: Request):
        user_id = get_current_user_id(request)  # Ensures authentication
        roles = get_user_roles(request)

        if not any(role in required_roles for role in roles):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        return True

    return role_checker


def require_admin(request: Request):
    """
    Dependency to require admin access

    Raises:
        HTTPException: If user doesn't have admin role
    """
    user_id = get_current_user_id(request)
    roles = get_user_roles(request)
    roles_lower = [r.lower() for r in roles]

    if "admin" not in roles_lower:
        raise HTTPException(status_code=403, detail="Admin access required")

    return True


def _get_jwt_realm(request: Request) -> str | None:
    """
    Extract realm from JWT token

    Returns:
        Realm string ("public", "org", "admin") or None if not found
    """
    try:
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None

        token = auth_header.split(" ")[1]
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        return payload.get("realm")
    except JWTError:
        return None


def require_admin_access(request: Request):
    """
    Dependency to require admin access (checks role)

    Raises:
        HTTPException: If user doesn't have admin access
    """
    # SECURITY: Check JWT realm first
    realm = _get_jwt_realm(request)

    if realm == "public":
        user_id = get_current_user_id_optional(request)
        logger.warning(
            f"Public user {user_id} attempted to access admin route: {request.url.path}",
            extra={"user_id": user_id, "path": request.url.path, "realm": realm},
        )
        raise HTTPException(
            status_code=403,
            detail="Admin access required. Public users cannot access admin routes.",
        )

    # Verify user has admin role
    roles = get_user_roles(request)
    roles_lower = [r.lower() for r in roles]

    if not any(role in roles_lower for role in ["owner", "admin"]):
        # Phase 4 Batch 4.4 (audit B42): use the None-safe id getter so
        # the intentional 403 surfaces even when `state.user_id` is
        # missing (otherwise `get_current_user_id` raises 401 first,
        # masking the lacks-admin signal).
        user_id = get_current_user_id_optional(request)
        logger.warning(
            f"User {user_id} with insufficient roles attempted admin access",
            extra={"user_id": user_id, "roles": roles, "path": request.url.path},
        )
        raise HTTPException(status_code=403, detail="Admin role required.")

    return True


def get_correlation_id(request: Request) -> str:
    """Get correlation ID for request tracing"""
    return getattr(request.state, "correlation_id", "unknown")
