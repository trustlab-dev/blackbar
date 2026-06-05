"""
Public user models for external FOI requesters
Simplified for magic link authentication (RFC-007)
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, EmailStr, Field, validator


class PublicUserStatus(str, Enum):
    """Public user status"""

    ACTIVE = "active"
    SUSPENDED = "suspended"


class PublicUserBase(BaseModel):
    """Base public user model"""

    email: EmailStr = Field(..., description="User email address")
    name: str | None = Field(None, description="User full name")

    @validator("email")
    def normalize_email(cls, v):
        """Normalize email to lowercase for consistent storage and comparison"""
        return v.lower().strip() if v else v


class PublicUserCreate(PublicUserBase):
    """Model for creating a new public user"""

    pass


class PublicUserUpdate(BaseModel):
    """Model for updating a public user"""

    name: str | None = None
    status: PublicUserStatus | None = None


class PublicUser(PublicUserBase):
    """Full public user model"""

    id: str = Field(..., description="Unique user ID")
    email_verified: bool = Field(default=True, description="Email verified via magic link")
    status: PublicUserStatus = Field(default=PublicUserStatus.ACTIVE)
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None
    request_ids: list[str] = Field(default_factory=list, description="FOI request IDs")

    class Config:
        from_attributes = True


class MagicLinkToken(BaseModel):
    """Magic link token model"""

    id: str = Field(..., description="Token ID")
    email: EmailStr = Field(..., description="Email address")
    token_hash: str = Field(..., description="Bcrypt hash of token")
    expires_at: datetime = Field(..., description="Token expiration time")
    used: bool = Field(default=False, description="Whether token has been used")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    ip_address: str | None = Field(None, description="Request IP for audit")
    user_agent: str | None = Field(None, description="User agent for audit")

    @validator("email")
    def normalize_email(cls, v):
        """Normalize email to lowercase for consistent comparison"""
        return v.lower().strip() if v else v

    class Config:
        from_attributes = True
