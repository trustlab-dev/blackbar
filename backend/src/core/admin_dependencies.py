"""
Admin authorization dependencies (WP-002)
Middleware to enforce admin-only access for admin routes
"""

import logging
from typing import Any

import jwt
from fastapi import HTTPException, Request, status
from jwt import InvalidTokenError as JWTError

from src.config import ALGORITHM, JWT_SECRET

logger = logging.getLogger(__name__)


def get_token_from_request(request: Request) -> str:
    """
    Extract JWT token from Authorization header

    Raises:
        HTTPException: If no token or invalid format
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )

    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication format. Expected 'Bearer <token>'",
        )

    token = auth_header.split(" ")[1]
    return token


def decode_token(token: str) -> dict[str, Any]:
    """
    Decode and validate JWT token

    Returns:
        Token payload as dictionary

    Raises:
        HTTPException: If token is invalid or expired
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        return payload
    except JWTError as e:
        logger.warning(f"Invalid token: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        )


async def require_admin_realm(request: Request) -> dict[str, Any]:
    """
    Verify user has admin realm access.

    This dependency enforces that only users with "admin" or "org" realm
    can access admin routes. Public users (realm="public") are blocked.

    Returns:
        Token payload if authorized

    Raises:
        HTTPException: If user is not authorized for admin access

    Usage:
        @router.get("/admin/users")
        async def list_users(
            current_user = Depends(require_admin_realm)
        ):
            # Only admin/org users can reach here
            ...
    """
    # Extract and decode token
    token = get_token_from_request(request)
    payload = decode_token(token)

    # Get realm from token
    realm = payload.get("realm")

    # SECURITY: Block public users from accessing admin routes
    if realm == "public":
        user_id = payload.get("sub", "unknown")
        logger.warning(
            f"Public user {user_id} attempted to access admin route: {request.url.path}",
            extra={"user_id": user_id, "path": request.url.path, "realm": realm},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required. Public users cannot access admin routes.",
        )

    # Verify realm is either "admin" or "org"
    if realm not in ["admin", "org"]:
        logger.warning(
            f"User with invalid realm '{realm}' attempted to access admin route",
            extra={"realm": realm, "path": request.url.path},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid realm. Admin or org access required.",
        )

    # For org realm, verify user has admin role
    if realm == "org":
        roles = payload.get("roles", [])
        # Normalize roles to lowercase for comparison
        roles_lower = [r.lower() for r in roles]

        if not any(role in roles_lower for role in ["owner", "admin"]):
            user_id = payload.get("sub", "unknown")
            logger.warning(
                f"Org user {user_id} with insufficient roles attempted admin access",
                extra={"user_id": user_id, "roles": roles, "path": request.url.path},
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin role required. Only owners and admins can access admin routes.",
            )

    # Log successful authorization
    user_id = payload.get("sub", "unknown")
    logger.info(
        f"Admin access granted to user {user_id} (realm: {realm})",
        extra={"user_id": user_id, "realm": realm, "path": request.url.path},
    )

    return payload


async def require_global_admin(request: Request) -> dict[str, Any]:
    """
    Verify user is a global admin.

    This dependency enforces that only users with realm="admin" can access
    global admin routes (e.g., system-wide settings).

    Returns:
        Token payload if authorized

    Raises:
        HTTPException: If user is not a global admin

    Usage:
        @router.put("/admin/config")
        async def update_system_config(
            current_user = Depends(require_global_admin)
        ):
            # Only global admins can reach here
            ...
    """
    # Extract and decode token
    token = get_token_from_request(request)
    payload = decode_token(token)

    # Get role from token
    role = payload.get("role", "")
    realm = payload.get("realm", "")

    # SECURITY: Only allow admin role or admin realm
    if role != "admin" and realm != "admin":
        user_id = payload.get("sub", "unknown")
        logger.warning(
            f"Non-admin user {user_id} attempted to access global admin route",
            extra={"user_id": user_id, "realm": realm, "path": request.url.path},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Global admin access required."
        )

    # Log successful authorization
    user_id = payload.get("sub", "unknown")
    logger.info(
        f"Global admin access granted to user {user_id}",
        extra={"user_id": user_id, "path": request.url.path},
    )

    return payload
