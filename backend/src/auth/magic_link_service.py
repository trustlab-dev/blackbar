"""
Magic Link Authentication Service (RFC-007)
Handles passwordless email authentication for public users
"""

import logging
import os
import secrets
from datetime import datetime, timedelta

import bcrypt

from src.auth.security import create_access_token
from src.public_users.models import PublicUser, PublicUserCreate
from src.public_users.repository import MagicLinkTokensRepository, PublicUsersRepository
from src.utils.log_utils import hash_email_for_logs

logger = logging.getLogger(__name__)


class MagicLinkService:
    """Service for magic link authentication"""

    def __init__(
        self,
        users_repo: PublicUsersRepository,
        tokens_repo: MagicLinkTokensRepository,
        token_expiration_minutes: int = 15,
    ):
        self.users_repo = users_repo
        self.tokens_repo = tokens_repo
        self.token_expiration_minutes = token_expiration_minutes

    def generate_token(self) -> str:
        """
        Generate a cryptographically secure random token
        Returns 32-byte URL-safe token (256 bits of entropy)
        """
        return secrets.token_urlsafe(32)

    def hash_token(self, token: str) -> str:
        """Hash token with bcrypt for secure storage"""
        return bcrypt.hashpw(token.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    def verify_token(self, token: str, token_hash: str) -> bool:
        """Verify token against stored hash"""
        try:
            return bcrypt.checkpw(token.encode("utf-8"), token_hash.encode("utf-8"))
        except Exception as e:
            logger.error(f"Token verification failed: {str(e)}")
            return False

    async def request_magic_link(
        self,
        email: str,
        name: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[str, datetime]:
        """
        Generate and store a magic link token

        Returns:
            Tuple of (token, expires_at)

        Raises:
            ValueError: If rate limit exceeded
        """
        # Check rate limiting (configurable via env vars)
        rate_limit_max = int(os.getenv("MAGIC_LINK_RATE_LIMIT_MAX", "3"))
        rate_limit_window_hours = int(os.getenv("MAGIC_LINK_RATE_LIMIT_HOURS", "1"))

        window_start = datetime.utcnow() - timedelta(hours=rate_limit_window_hours)
        recent_count = await self.tokens_repo.count_recent_requests(email, window_start)

        if recent_count >= rate_limit_max:
            email_hash = hash_email_for_logs(email)
            logger.warning(
                f"Rate limit exceeded for {email_hash} ({recent_count}/{rate_limit_max} in {rate_limit_window_hours}h)"
            )
            raise ValueError("RATE_LIMIT_EXCEEDED")

        # Generate token
        token = self.generate_token()
        token_hash = self.hash_token(token)
        expires_at = datetime.utcnow() + timedelta(minutes=self.token_expiration_minutes)

        # Store token
        await self.tokens_repo.create_token(
            email=email,
            token_hash=token_hash,
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # Find or create user (but don't activate until they click link)
        user = await self.users_repo.get_by_email(email)
        if not user:
            # Create placeholder user (will be activated on verification)
            user_create = PublicUserCreate(email=email, name=name)
            await self.users_repo.create(user_create)
            email_hash = hash_email_for_logs(email)
            logger.info(f"Created new public user for {email_hash}")

        email_hash = hash_email_for_logs(email)
        logger.info(f"Magic link requested for {email_hash}")
        return token, expires_at

    async def verify_magic_link(self, token: str, email: str) -> PublicUser | None:
        """
        Verify magic link token and return user

        Returns:
            PublicUser if valid, None if invalid/expired
        """
        # Get most recent unused token for this email
        stored_token = await self.tokens_repo.get_by_email(email)

        if not stored_token:
            email_hash = hash_email_for_logs(email)
            logger.warning(f"No valid token found for {email_hash}")
            return None

        # Verify token matches
        if not self.verify_token(token, stored_token.token_hash):
            email_hash = hash_email_for_logs(email)
            logger.warning(f"Token mismatch for {email_hash}")
            return None

        # Check expiration
        if stored_token.expires_at < datetime.utcnow():
            email_hash = hash_email_for_logs(email)
            logger.warning(f"Expired token for {email_hash}")
            return None

        # Check if already used
        if stored_token.used:
            email_hash = hash_email_for_logs(email)
            logger.warning(f"Token already used for {email_hash}")
            return None

        # Mark token as used
        await self.tokens_repo.mark_as_used(stored_token.id)

        # Get user
        user = await self.users_repo.get_by_email(email)
        if not user:
            email_hash = hash_email_for_logs(email)
            logger.error(f"User not found for {email_hash}")
            return None

        # Update last login
        await self.users_repo.update_last_login(user.id)

        email_hash = hash_email_for_logs(email)
        logger.info(f"Magic link verified for {email_hash}")
        return user

    def issue_token(self, user: PublicUser) -> str:
        """
        Issue JWT token for authenticated public user

        Token payload includes:
        - sub: user_id
        - email: user email
        - realm: "public" (security boundary — prevents access to admin routes)
        - user_type: "public" (legacy field for backward compatibility)

        Public users get longer sessions (8 hours) since they may be
        filling out forms or reviewing documents.
        """
        payload = {
            "sub": user.id,
            "email": user.email,
            "realm": "public",  # Prevents admin access
            "user_type": "public",  # Legacy field for backward compatibility
        }

        # Public users get 8 hour sessions (configurable via env)
        session_hours = int(os.getenv("PUBLIC_USER_SESSION_HOURS", "8"))
        expires_delta = timedelta(hours=session_hours)

        token = create_access_token(payload, expires_delta=expires_delta)
        logger.info(f"Issued JWT for public user {user.id} (expires in {session_hours}h)")
        return token

    async def cleanup_expired_tokens(self) -> int:
        """
        Clean up expired tokens (call from background task)
        Returns number of tokens deleted
        """
        deleted = await self.tokens_repo.cleanup_expired()
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} expired magic link tokens")
        return deleted
