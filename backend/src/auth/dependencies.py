"""
Authentication dependencies for route protection
Handles both internal users and public users (RFC-007)
"""

import logging

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError as JWTError

from src.config import ALGORITHM, JWT_SECRET

logger = logging.getLogger(__name__)

# JWT Configuration — single source of truth from config.py
SECRET_KEY = JWT_SECRET

security = HTTPBearer()


async def get_current_user_public(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    Dependency to get current authenticated public user from JWT

    Validates:
    - Token signature
    - Token expiration
    - user_type is "public"

    Returns:
        dict with user_id, email, user_type

    Raises:
        HTTPException 401 if token invalid or user not public
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        user_id: str = payload.get("sub")
        email: str = payload.get("email")
        user_type: str = payload.get("user_type")

        if user_id is None or email is None:
            logger.warning("Token missing required fields")
            raise credentials_exception

        if user_type != "public":
            logger.warning(f"Non-public user attempted to access public endpoint: {user_type}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This endpoint is for public users only",
            )

        return {"user_id": user_id, "email": email, "user_type": user_type}

    except HTTPException:
        # Phase 4 Batch 4.4 (audit B6): preserve intentional HTTPException
        # status codes (e.g. the 403 raised above for non-public realms);
        # otherwise the broad `except Exception` below would re-emit them
        # as 401 with the wrong detail.
        raise
    except JWTError as e:
        logger.error(f"JWT validation failed: {str(e)}")
        raise credentials_exception
    except Exception as e:
        logger.error(f"Unexpected error in auth: {str(e)}")
        raise credentials_exception


async def get_optional_public_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict | None:
    """
    Optional authentication for public users
    Returns user dict if authenticated, None if not

    Useful for endpoints that work both authenticated and unauthenticated
    """
    if not credentials:
        return None

    try:
        return await get_current_user_public(credentials)
    except HTTPException:
        return None
