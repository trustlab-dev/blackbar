"""
Release Package Models
Data models for release package generation and tracking

Three-step workflow:
1. GENERATE - Creates draft package in background
2. REVIEW - Analyst downloads and reviews draft
3. RELEASE - Publishes to public portal, notifies requester
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ReleasePackageStatus(str, Enum):
    """Release package status - follows three-step workflow"""

    GENERATING = "generating"  # Background task in progress
    DRAFT = "draft"  # Ready for analyst review
    RELEASED = "released"  # Published to public portal
    EXPIRED = "expired"  # Past expiration date
    REVOKED = "revoked"  # Manually revoked


class IncludedDocument(BaseModel):
    """Document included in release package"""

    document_id: str
    filename: str
    original_filename: str | None = None
    page_count: int | None = None
    redaction_count: int = 0
    exemptions: list[str] = []


class DownloadRecord(BaseModel):
    """Record of a download"""

    downloaded_at: datetime
    ip_address: str | None = None
    user_agent: str | None = None
    downloaded_by: str | None = None  # "analyst" or "requester"


class ReleasePackageGenerate(BaseModel):
    """Request to generate a release package (Step 1)"""

    document_ids: list[str] | None = Field(
        None, description="Specific docs to include (all approved if omitted)"
    )
    include_cover_letter: bool = Field(default=True)
    cover_letter_template_id: str | None = None


class ReleasePackageRelease(BaseModel):
    """Request to release a package to public portal (Step 3)"""

    expires_in_days: int | None = Field(None, description="Override default expiration")
    max_downloads: int | None = Field(None, description="Override default max downloads")
    notify_requester: bool = Field(default=True)
    custom_message: str | None = Field(None, description="Custom message for notification email")


class ReleasePackageDB(BaseModel):
    """Release package stored in database"""

    id: str
    case_id: str

    # Package contents
    file_id: str | None = None  # GridFS file ID for ZIP
    filename: str
    size_bytes: int = 0
    document_count: int = 0
    total_redactions: int = 0
    included_documents: list[IncludedDocument] = []

    # Access control (only active when status = RELEASED)
    access_token: str  # Secure token for public download URL
    expires_at: datetime | None = None
    max_downloads: int | None = None
    download_count: int = 0

    # Generation tracking
    created_at: datetime
    created_by: str
    created_by_name: str
    status: ReleasePackageStatus = ReleasePackageStatus.GENERATING
    generation_progress: int = 0  # 0-100 percentage
    generation_message: str | None = None

    # Release tracking (only set when status = RELEASED)
    released_at: datetime | None = None
    released_by: str | None = None
    released_by_name: str | None = None
    requester_notified: bool = False
    requester_notified_at: datetime | None = None
    custom_message: str | None = None

    # Download history
    downloads: list[DownloadRecord] = []

    # Cover letter
    include_cover_letter: bool = True
    cover_letter_template_id: str | None = None


class ReleasePackageResponse(BaseModel):
    """Response when getting a release package"""

    id: str
    case_id: str
    status: ReleasePackageStatus
    filename: str
    size_bytes: int
    document_count: int
    total_redactions: int = 0
    included_documents: list[IncludedDocument] = []

    # Progress (when generating)
    generation_progress: int = 0
    generation_message: str | None = None

    # URLs (only when released)
    download_url: str | None = None
    public_url: str | None = None

    # Expiration (only when released)
    expires_at: datetime | None = None
    download_count: int = 0
    max_downloads: int | None = None

    # Timestamps
    created_at: datetime
    created_by_name: str
    released_at: datetime | None = None
    released_by_name: str | None = None


class GenerateResponse(BaseModel):
    """Response when starting package generation"""

    package_id: str
    status: ReleasePackageStatus
    message: str
    replaced_draft_id: str | None = None


class ReleaseResponse(BaseModel):
    """Response when releasing a package"""

    id: str
    status: ReleasePackageStatus
    public_url: str
    expires_at: datetime
    requester_notified: bool
    message: str


class CurrentPackageState(BaseModel):
    """Current state of release packages for a case"""

    current_draft: ReleasePackageResponse | None = None
    current_release: ReleasePackageResponse | None = None
