import logging

import jwt
from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError as JWTError

from src.config import ALGORITHM, JWT_SECRET
from src.database import users

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)


async def get_current_user(request: Request, token: str = Security(oauth2_scheme)):
    """
    Extracts user info from JWT token.
    Checks request.state first (set by AuthMiddleware).
    """
    # Check if AuthMiddleware already validated the token
    if hasattr(request.state, "user_id") and request.state.user_id:
        # Get user from database
        user = await users.find_one({"id": request.state.user_id})
        if user:
            role = request.state.roles[0] if request.state.roles else user.get("role", "user")
            return {
                "id": user.get("id"),
                "username": user.get("email"),
                "email": user.get("email"),
                "role": role,
            }

    # Fall back to token validation
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])

        # New token format: sub = user_id, role = string
        user_id = payload.get("sub")
        if user_id:
            user = await users.find_one({"id": user_id})
            if not user:
                raise HTTPException(status_code=401, detail="User not found")

            role = payload.get("role", "user")
            # Support legacy tokens with roles list
            if not role and "roles" in payload:
                roles = payload.get("roles", [])
                role = roles[0] if roles else "user"

            return {
                "id": user.get("id"),
                "username": user.get("email"),
                "email": user.get("email"),
                "role": role,
            }

        raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


def check_role(required_roles: list):
    async def role_checker(user=Depends(get_current_user)):
        user_role = user["role"]

        if user_role not in required_roles:
            logger.warning(
                f"Access denied for user {user.get('id')}: "
                f"required {required_roles}, has {user_role}"
            )
            raise HTTPException(status_code=403, detail="Permission denied")
        return user

    return role_checker
