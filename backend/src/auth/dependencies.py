"""
Authentication dependencies for route protection
Handles both internal users and public users (RFC-007)
"""

import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError as JWTError

from src.auth.security import decode_token, is_public_claims
from src.core.database import get_database_from_request

logger = logging.getLogger(__name__)

security = HTTPBearer()


async def get_current_user_public(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    Dependency to get current authenticated public user from JWT

    Validates:
    - Token signature, algorithm, expiry and audience
    - The token is a public-realm (magic-link) token

    Returns:
        dict with user_id, email, user_type

    Raises:
        HTTPException 401 if token invalid, 403 if not a public-user token
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        token = credentials.credentials
        payload = decode_token(token)

        user_id = payload.get("sub")
        email = payload.get("email")

        if user_id is None or email is None:
            logger.warning("Token missing required fields")
            raise credentials_exception

        if not is_public_claims(payload) or payload.get("user_type") != "public":
            logger.warning(
                f"Non-public token attempted to access public endpoint: {payload.get('user_type')}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This endpoint is for public users only",
            )

        return {"user_id": user_id, "email": email, "user_type": "public"}

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


async def get_active_public_user(
    current_user: dict = Depends(get_current_user_public),
    db=Depends(get_database_from_request),
) -> dict:
    """Public principal whose account still exists and is not suspended.

    Suspension used to be recorded but never enforced (AUTH-28): an 8-hour
    public session kept working after staff suspended the requester.
    """
    record = await db.public_users.find_one({"_id": current_user["user_id"]}, {"status": 1})
    if not record:
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    if record.get("status", "active") != "active":
        raise HTTPException(status_code=403, detail="This account has been suspended")
    return current_user


async def get_optional_public_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
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
