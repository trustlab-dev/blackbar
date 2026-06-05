"""
Account Activation Service for Org Owners
Handles activation token verification and password setup
"""

import logging
from datetime import datetime

from src.auth.auth_service import AuthService
from src.users.models import User, UserUpdate
from src.users.repository import UsersRepository
from src.utils.log_utils import hash_email_for_logs
from src.utils.welcome_email_service import WelcomeEmailService

logger = logging.getLogger(__name__)


class ActivationService:
    """Service for activating org owner accounts"""

    def __init__(self, users_repo: UsersRepository):
        self.users_repo = users_repo
        self.welcome_service = WelcomeEmailService(None)  # Only need token verification

    async def activate_account(self, email: str, token: str, password: str) -> User | None:
        """
        Activate user account with token and set password

        Args:
            email: User email address
            token: Activation token (unhashed)
            password: New password to set

        Returns:
            User if activation successful, None otherwise
        """
        # Get user by email
        user = await self.users_repo.get_by_email(email)
        if not user:
            email_hash = hash_email_for_logs(email)
            logger.warning(f"Activation failed: user not found for {email_hash}")
            return None

        # Check user status
        if user.status != "pending_activation":
            email_hash = hash_email_for_logs(email)
            logger.warning(
                f"Activation failed: user {email_hash} status is {user.status}, expected pending_activation"
            )
            return None

        # Check if token exists
        if not user.activation_token or not user.activation_token_expires_at:
            email_hash = hash_email_for_logs(email)
            logger.warning(f"Activation failed: no activation token for {email_hash}")
            return None

        # Check token expiration
        if user.activation_token_expires_at < datetime.utcnow():
            email_hash = hash_email_for_logs(email)
            logger.warning(f"Activation failed: token expired for {email_hash}")
            return None

        # Verify token
        if not self.welcome_service.verify_token(token, user.activation_token):
            email_hash = hash_email_for_logs(email)
            logger.warning(f"Activation failed: invalid token for {email_hash}")
            return None

        # Hash new password
        password_hash = AuthService.hash_password(password)

        # Update user: set password, activate status, clear activation token
        update_data = UserUpdate(status="active")

        # Update user with new password and status
        updated_user = await self.users_repo.update(user.id, update_data, password_hash)

        if not updated_user:
            email_hash = hash_email_for_logs(email)
            logger.error(f"Activation failed: could not update user {email_hash}")
            return None

        # Clear activation token (direct DB update)
        from src.database import db

        await db.users.update_one(
            {"id": user.id}, {"$unset": {"activation_token": "", "activation_token_expires_at": ""}}
        )

        email_hash = hash_email_for_logs(email)
        logger.info(f"Account activated successfully for {email_hash}")

        return updated_user
