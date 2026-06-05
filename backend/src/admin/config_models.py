"""
System Configuration Models
Defines configurable settings for the application
"""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class SystemConfiguration(BaseModel):
    """System-wide configuration settings"""

    # Organization Branding
    org_name: str = Field(
        default="Freedom of Information Office",
        max_length=100,
        description="Organization display name",
    )
    org_logo_url: str | None = Field(
        default=None, description="URL or data URI for organization logo"
    )
    contact_email: EmailStr = Field(default="foi@example.com", description="Support contact email")
    primary_color: str = Field(
        default="#0366d6", pattern="^#[0-9A-Fa-f]{6}$", description="Primary theme color (hex)"
    )
    footer_text: str | None = Field(
        default=None, max_length=500, description="Custom footer/disclaimer text"
    )

    # Workflow Defaults
    default_due_days: int = Field(
        default=30, ge=1, le=365, description="Default days until case due date"
    )
    default_assignee_id: str | None = Field(
        default=None, description="User ID to auto-assign new cases"
    )
    default_priority: str = Field(
        default="normal",
        pattern="^(low|normal|high|urgent)$",
        description="Default priority for new cases",
    )

    # Security Settings
    session_timeout_minutes: int = Field(
        default=60, ge=15, le=480, description="Session timeout in minutes"
    )
    password_min_length: int = Field(default=12, ge=8, le=32, description="Minimum password length")

    # Public Portal
    enable_public_requests: bool = Field(default=True, description="Allow public FOI submissions")
    enable_request_tracking: bool = Field(default=True, description="Allow tracking by number")
    enable_public_upload: bool = Field(default=True, description="Allow document uploads via links")

    # Request Categories
    request_categories: list[str] = Field(
        default=[
            "General Records",
            "Personnel Files",
            "Financial Records",
            "Meeting Minutes",
            "Correspondence",
            "Contracts & Agreements",
            "Policy Documents",
            "Other",
        ],
        description="Available request type categories",
    )

    # Document Handling
    auto_generate_ai_suggestions: bool = Field(
        default=False,
        description="Automatically generate AI redaction suggestions on document upload",
    )
    # AI suggestion timeout is configured globally — see admin settings, not per-pack.

    # Metadata
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    updated_by: str = Field(default="system", description="User ID who last updated")

    class Config:
        json_schema_extra = {
            "example": {
                "org_name": "BC Transit FOI Office",
                "contact_email": "foi@bctransit.com",
                "primary_color": "#003366",
                "default_due_days": 30,
                "session_timeout_minutes": 60,
            }
        }


class SystemConfigurationUpdate(BaseModel):
    """Update model - all fields optional"""

    org_name: str | None = Field(None, max_length=100)
    org_logo_url: str | None = None
    contact_email: EmailStr | None = None
    primary_color: str | None = Field(None, pattern="^#[0-9A-Fa-f]{6}$")
    footer_text: str | None = Field(None, max_length=500)
    default_due_days: int | None = Field(None, ge=1, le=365)
    default_assignee_id: str | None = None
    default_priority: str | None = Field(None, pattern="^(low|normal|high|urgent)$")
    session_timeout_minutes: int | None = Field(None, ge=15, le=480)
    password_min_length: int | None = Field(None, ge=8, le=32)
    enable_public_requests: bool | None = None
    enable_request_tracking: bool | None = None
    enable_public_upload: bool | None = None
    request_categories: list[str] | None = None
    auto_generate_ai_suggestions: bool | None = None
    # AI suggestion timeout is configured globally — see admin settings, not per-pack.


class PublicConfiguration(BaseModel):
    """Public-facing configuration (non-sensitive)"""

    org_name: str
    org_logo_url: str | None
    primary_color: str
    contact_email: str
    footer_text: str | None
    enable_public_requests: bool
    enable_request_tracking: bool
    enable_public_upload: bool
    request_categories: list[str]
    # Demo mode: when the BLACKBAR_DEMO_MODE env var is "true", the
    # frontend renders a "Log in as demo requester" button on the public
    # login page that mints a JWT without requiring a magic link. Always
    # false in production builds.
    demo_mode: bool = False
