"""
FastAPI dependencies for request context

Every authorization decision here goes through
``src.dependencies.get_current_user``, which re-reads the user from the
database (status, role, token_version) instead of trusting token claims
(AUTH-14) and refuses public-realm principals (AUTH-03).
"""

import logging

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)


async def _principal(request: Request) -> dict:
    # Imported lazily: src.dependencies pulls in the database module.
    from src.dependencies import get_current_user

    return await get_current_user(request, token=None)


async def get_current_user_id(request: Request) -> str:
    """Get the current internal user's ID (requires an active staff account)."""
    if not getattr(request.state, "user_id", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    principal = await _principal(request)
    return principal["id"]


def get_current_user_id_optional(request: Request) -> str | None:
    """Get current user ID from request state (optional, unverified)"""
    return getattr(request.state, "user_id", None)


def get_user_roles(request: Request) -> list[str]:
    """Roles claimed by the token (unverified; do not use for authorization)."""
    return getattr(request.state, "roles", [])


def require_role(required_roles: list[str]):
    """
    Dependency factory to require specific roles (checked against the DB role)

    Usage:
        @router.get("/admin-only", dependencies=[Depends(require_role(["admin"]))])
    """

    async def role_checker(request: Request):
        user_id = await get_current_user_id(request)  # Ensures authentication
        role = (await _principal(request))["role"]

        if role not in required_roles:
            logger.warning(f"User {user_id} with role {role} denied; requires {required_roles}")
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        return True

    return role_checker


async def require_admin(request: Request):
    """
    Dependency to require admin access

    Raises:
        HTTPException: If user doesn't have admin role
    """
    await get_current_user_id(request)
    role = (await _principal(request))["role"]

    if role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    return True


async def require_admin_access(request: Request):
    """
    Dependency to require admin access (owner or admin, from the DB)

    Raises:
        HTTPException: If user doesn't have admin access
    """
    # SECURITY: public-realm tokens are refused outright.
    if getattr(request.state, "realm", None) == "public":
        user_id = get_current_user_id_optional(request)
        logger.warning(
            f"Public user {user_id} attempted to access admin route: {request.url.path}",
            extra={"user_id": user_id, "path": request.url.path, "realm": "public"},
        )
        raise HTTPException(
            status_code=403,
            detail="Admin access required. Public users cannot access admin routes.",
        )

    user_id = await get_current_user_id(request)
    role = (await _principal(request))["role"]

    if role.lower() not in ("owner", "admin"):
        logger.warning(
            f"User {user_id} with insufficient role attempted admin access",
            extra={"user_id": user_id, "role": role, "path": request.url.path},
        )
        raise HTTPException(status_code=403, detail="Admin role required.")

    return True


def get_correlation_id(request: Request) -> str:
    """Get correlation ID for request tracing"""
    return getattr(request.state, "correlation_id", "unknown")
