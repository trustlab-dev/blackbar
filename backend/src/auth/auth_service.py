"""
Authentication service - pluggable auth abstraction layer
Supports local email/password auth with future SSO extensibility
"""

import logging
from typing import Literal

from jwt import InvalidTokenError as JWTError
from pydantic import BaseModel, ValidationError

from src.auth import security
from src.auth.security import INTERNAL_AUDIENCE, PUBLIC_ROLE
from src.users.models import User
from src.users.repository import UsersRepository
from src.utils.log_utils import hash_email_for_logs

logger = logging.getLogger(__name__)


class TokenPayload(BaseModel):
    """JWT token payload structure"""

    sub: str  # user_id
    role: str
    exp: int
    realm: Literal["public", "org", "admin"] = "org"
    # Session revocation counter; compared with users.token_version (AUTH-14).
    tv: int = 0


class AuthService:
    """
    Authentication service providing pluggable auth layer
    Currently supports local email/password, designed for future SSO
    """

    def __init__(self, users_repo: UsersRepository):
        self.users_repo = users_repo

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password using bcrypt (raises PasswordTooLongError > 72 bytes)."""
        return security.hash_password(password)

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash"""
        return security.verify_password(plain_password, hashed_password)

    async def authenticate_local(self, email: str, password: str) -> User | None:
        """
        Authenticate user with email and password

        Every failure path spends one bcrypt comparison, so response time does
        not reveal whether the account exists or is active (AUTH-23).

        Args:
            email: User email
            password: Plain text password

        Returns:
            User object if authentication successful, None otherwise
        """
        user = await self.users_repo.get_by_email(email)

        if not user:
            security.burn_password_check(password)
            logger.warning(
                f"Authentication failed: user not found for email {hash_email_for_logs(email)}"
            )
            return None

        if user.status != "active":
            security.burn_password_check(password)
            logger.warning(f"Authentication failed: user {user.id} is {user.status}")
            return None

        if not user.password_hash:
            security.burn_password_check(password)
            logger.warning(f"Authentication failed: user {user.id} has no password (SSO-only?)")
            return None

        if not self.verify_password(password, user.password_hash):
            logger.warning(f"Authentication failed: invalid password for user {user.id}")
            return None

        logger.info(f"User {user.id} authenticated successfully")
        return user

    async def issue_token(self, user: User) -> str:
        """
        Issue a JWT token for a user

        Args:
            user: User object

        Returns:
            JWT token string
        """
        # Determine realm based on user role
        realm = "admin" if user.role == "admin" else "org"

        token = security.create_access_token(
            {
                "sub": user.id,
                "role": user.role,
                "realm": realm,
                "aud": INTERNAL_AUDIENCE,
                "tv": user.token_version,
            }
        )

        logger.info(
            f"Issued token for user {user.id}", extra={"user_id": user.id, "role": user.role}
        )

        return token

    @staticmethod
    def validate_token(token: str) -> TokenPayload | None:
        """
        Validate and decode a JWT token

        Public (magic-link) tokens are mapped to realm "public" with the
        `public_user` role, never to an internal role (AUTH-03). A staff token
        without a role claim is rejected rather than defaulted.

        Args:
            token: JWT token string

        Returns:
            TokenPayload if valid, None otherwise
        """
        try:
            payload = security.decode_token(token)
        except JWTError as e:
            logger.warning(f"Token validation failed: {str(e)}")
            return None

        sub = payload.get("sub")
        if not isinstance(sub, str) or not sub:
            logger.warning("Token validation failed: missing subject")
            return None

        try:
            if security.is_public_claims(payload):
                return TokenPayload(sub=sub, role=PUBLIC_ROLE, exp=payload["exp"], realm="public")

            role = payload.get("role")
            # Support legacy tokens that have 'roles' list instead of 'role' string
            if not role and payload.get("roles"):
                role = payload["roles"][0]
            if not isinstance(role, str) or not role:
                logger.warning("Token validation failed: staff token has no role claim")
                return None

            return TokenPayload(
                sub=sub,
                role=role,
                exp=payload["exp"],
                realm=payload.get("realm", "org"),
                tv=payload.get("tv", 0),
            )
        except ValidationError as e:
            # An unknown realm value (e.g. legacy "tenant") fails the
            # Literal["public","org","admin"] constraint on TokenPayload.realm.
            # Reject the token gracefully rather than 500.
            logger.warning(f"Token validation failed: payload shape rejected ({str(e)})")
            return None
