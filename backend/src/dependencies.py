import logging

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import OAuth2PasswordBearer

from src.auth.auth_service import AuthService
from src.database import users

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)

# Fields the principal lookup needs. Never includes password or token hashes.
_PRINCIPAL_PROJECTION = {
    "_id": 0,
    "id": 1,
    "email": 1,
    "role": 1,
    "status": 1,
    "token_version": 1,
}


async def get_current_user(request: Request, token: str | None = Security(oauth2_scheme)):
    """Resolve the internal (staff) principal for this request.

    The token only identifies the user; authorization data comes from the
    database on every request (AUTH-14):

    - public (magic-link) principals are refused with 403 (AUTH-03);
    - unknown, deleted, disabled or pending users get 401;
    - a token whose `tv` claim no longer matches `users.token_version`
      (bumped by logout, password change, disable, role change) gets 401;
    - the role is the DB role, not the token's role claim.

    The result is cached on ``request.state`` so several dependencies in one
    request cost a single lookup.
    """
    cached = getattr(request.state, "current_user", None)
    if cached is not None:
        return cached

    user_id = getattr(request.state, "user_id", None)
    realm = getattr(request.state, "realm", None)
    token_version = getattr(request.state, "token_version", 0)

    if not user_id:
        # AuthMiddleware did not run for this path; validate the token here.
        if not token:
            raise HTTPException(status_code=401, detail="Not authenticated")
        payload = AuthService.validate_token(token)
        if payload is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        user_id, realm, token_version = payload.sub, payload.realm, payload.tv

    if realm == "public":
        raise HTTPException(status_code=403, detail="Public accounts cannot access this endpoint")

    user = await users.find_one({"id": user_id}, _PRINCIPAL_PROJECTION)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    if user.get("status", "active") != "active":
        logger.warning(f"Refused token for inactive user {user_id} ({user.get('status')})")
        raise HTTPException(status_code=401, detail="Account is not active")

    if int(user.get("token_version") or 0) != int(token_version or 0):
        raise HTTPException(status_code=401, detail="Session has been revoked")

    principal = {
        "id": user.get("id"),
        "username": user.get("email"),
        "email": user.get("email"),
        "role": user.get("role") or "user",
    }
    request.state.current_user = principal
    return principal


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
