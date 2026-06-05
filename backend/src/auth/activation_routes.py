"""
Account Activation Routes for Org Owners
Handles activation token verification and password setup
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, field_validator

from src.auth.activation_service import ActivationService
from src.core.dependencies import get_correlation_id
from src.database import db
from src.users.repository import UsersRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication - Activation"])


class ActivateAccountRequest(BaseModel):
    """Request model for account activation"""

    email: EmailStr = Field(..., description="User email address")
    token: str = Field(..., description="Activation token from welcome email")
    password: str = Field(
        ...,
        min_length=8,
        description="New password (min 8 chars, must include uppercase, lowercase, digit, and special character)",
    )

    @field_validator("password")
    @classmethod
    def validate_password_complexity(cls, v):
        import re

        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least one digit")
        if not re.search(r"[^A-Za-z0-9]", v):
            raise ValueError("Password must contain at least one special character")
        return v


class ActivateAccountResponse(BaseModel):
    """Response model for account activation"""

    message: str
    user_id: str
    email: str


@router.post("/activate-owner", response_model=ActivateAccountResponse)
async def activate_owner_account(request: Request, activation_data: ActivateAccountRequest):
    """
    Activate org owner account with token and set password

    This endpoint is called when an org owner clicks the activation link
    in their welcome email and sets their password.

    No authentication required - uses activation token for verification
    """
    users_repo = UsersRepository(db)
    activation_service = ActivationService(users_repo)

    # Activate account
    user = await activation_service.activate_account(
        email=activation_data.email, token=activation_data.token, password=activation_data.password
    )

    if not user:
        logger.warning(
            "Account activation failed for email",
            extra={"correlation_id": get_correlation_id(request)},
        )
        raise HTTPException(status_code=400, detail="Invalid or expired activation token")

    logger.info(
        f"Account activated successfully: {user.id}",
        extra={"correlation_id": get_correlation_id(request), "user_id": user.id},
    )

    return ActivateAccountResponse(
        message="Account activated successfully. You can now log in with your email and password.",
        user_id=user.id,
        email=user.email,
    )
