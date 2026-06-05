"""
User models
"""

import re
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class UserStatus(str, Enum):
    """User account status"""

    ACTIVE = "active"
    DISABLED = "disabled"
    PENDING_ACTIVATION = "pending_activation"


class UserBase(BaseModel):
    """Base user model"""

    email: str = Field(..., description="User email address")
    name: str = Field(..., description="Full name")
    status: UserStatus = Field(default=UserStatus.ACTIVE)

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        """Validate email format, allowing .local for development"""
        # Basic email regex that allows .local domains
        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$|^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.local$"
        if not re.match(email_pattern, v.lower()):
            raise ValueError("Invalid email format")
        return v.lower()


class UserCreate(UserBase):
    """Model for creating a new user"""

    password: str = Field(..., description="Plain text password (will be hashed)")


class UserUpdate(BaseModel):
    """Model for updating a user"""

    name: str | None = None
    email: str | None = None
    status: UserStatus | None = None
    password: str | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str | None) -> str | None:
        """Validate email format, allowing .local for development"""
        if v is None:
            return v
        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$|^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.local$"
        if not re.match(email_pattern, v.lower()):
            raise ValueError("Invalid email format")
        return v.lower()


class User(UserBase):
    """Full user model with metadata"""

    id: str = Field(..., description="Unique user ID")
    password_hash: str | None = Field(None, description="Bcrypt password hash")
    external_id: str | None = Field(None, description="External IdP identifier")
    role: str = Field(default="user", description="User role: admin, analyst, user, guest")
    activation_token: str | None = Field(None, description="Account activation token hash")
    activation_token_expires_at: datetime | None = Field(
        None, description="Activation token expiration"
    )
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class UserPublic(BaseModel):
    """Public user model (no sensitive data)"""

    id: str
    email: str
    name: str
    status: UserStatus

    class Config:
        from_attributes = True
