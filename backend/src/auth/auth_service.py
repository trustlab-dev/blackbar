"""
Authentication service - pluggable auth abstraction layer
Supports local email/password auth with future SSO extensibility
"""

import logging
from datetime import datetime, timedelta
from typing import Literal

import bcrypt
import jwt
from jwt import InvalidTokenError as JWTError
from pydantic import BaseModel, ValidationError

from src.config import ACCESS_TOKEN_EXPIRE_MINUTES, ALGORITHM, JWT_SECRET
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


class AuthService:
    """
    Authentication service providing pluggable auth layer
    Currently supports local email/password, designed for future SSO
    """

    def __init__(self, users_repo: UsersRepository):
        self.users_repo = users_repo

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password using bcrypt"""
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash"""
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))

    async def authenticate_local(self, email: str, password: str) -> User | None:
        """
        Authenticate user with email and password

        Args:
            email: User email
            password: Plain text password

        Returns:
            User object if authentication successful, None otherwise
        """
        user = await self.users_repo.get_by_email(email)

        if not user:
            logger.warning(
                f"Authentication failed: user not found for email {hash_email_for_logs(email)}"
            )
            return None

        if user.status != "active":
            logger.warning(f"Authentication failed: user {user.id} is {user.status}")
            return None

        if not user.password_hash:
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
        # Create token payload
        expiration = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

        # Determine realm based on user role
        realm = "admin" if user.role == "admin" else "org"

        payload = {
            "sub": user.id,
            "role": user.role,
            "realm": realm,
            "exp": int(expiration.timestamp()),
        }

        token = jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)

        logger.info(
            f"Issued token for user {user.id}", extra={"user_id": user.id, "role": user.role}
        )

        return token

    @staticmethod
    def validate_token(token: str) -> TokenPayload | None:
        """
        Validate and decode a JWT token

        Args:
            token: JWT token string

        Returns:
            TokenPayload if valid, None otherwise
        """
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
            # Support legacy tokens that have 'roles' list instead of 'role' string
            if "roles" in payload and "role" not in payload:
                roles = payload.get("roles", [])
                payload["role"] = roles[0] if roles else "user"
            if "role" not in payload:
                payload["role"] = "user"
            return TokenPayload(
                sub=payload.get("sub", ""),
                role=payload.get("role", "user"),
                exp=payload.get("exp", 0),
                realm=payload.get("realm", "org"),
            )
        except JWTError as e:
            logger.warning(f"Token validation failed: {str(e)}")
            return None
        except ValidationError as e:
            # An unknown realm value (e.g. legacy "tenant") fails the
            # Literal["public","org","admin"] constraint on TokenPayload.realm.
            # Reject the token gracefully rather than 500.
            logger.warning(f"Token validation failed: payload shape rejected ({str(e)})")
            return None
