"""
Workflow models — advanced workflow and queue management.

This module contains models for:
- Clock events (statutory clock pause/resume)
- Case messages (internal staff messaging)
- Case contributors (named record contributors)
- Case reminders (milestone notifications)
- Workflow stages
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, EmailStr, Field

# =============================================================================
# Workflow Stages
# =============================================================================


class WorkflowStage(str, Enum):
    """
    Case workflow stages including fee and review holds.
    These extend the basic CaseStatus for more granular tracking.
    """

    INTAKE = "intake"
    COLLECTION = "collection"
    REVIEW = "review"
    REDACTION = "redaction"
    APPROVAL = "approval"
    RELEASE = "release"
    PENDING_FEE_PAYMENT = "pending_fee_payment"
    PRIVACY_COMMISSION_REVIEW = "privacy_commission_review"
    CLOSED = "closed"


# =============================================================================
# Clock Events (Statutory Clock Management)
# =============================================================================


class ClockEventType(str, Enum):
    """Types of statutory clock events"""

    START = "start"
    PAUSE = "pause"
    RESUME = "resume"
    EXTEND = "extend"


class ClockPauseReason(str, Enum):
    """Reasons for pausing the statutory clock"""

    FEE_PENDING = "fee_pending"
    SCOPE_NARROWING = "scope_narrowing"
    THIRD_PARTY_CONSULTATION = "third_party_consultation"
    PRIVACY_COMMISSION_REVIEW = "privacy_commission_review"
    APPLICANT_REQUEST = "applicant_request"
    MANUAL = "manual"


class ClockEventCreate(BaseModel):
    """Create a new clock event"""

    event_type: ClockEventType
    reason: ClockPauseReason | None = None
    notes: str | None = None


class ClockEvent(BaseModel):
    """Statutory clock event for audit trail"""

    id: str
    case_id: str
    event_type: ClockEventType
    reason: ClockPauseReason | None = None
    event_date: datetime = Field(default_factory=datetime.utcnow)
    created_by: str  # User ID
    created_by_name: str | None = None  # Denormalized for display
    notes: str | None = None

    # Calculated fields (set by service)
    days_elapsed_at_event: int | None = None  # Days elapsed when event occurred

    class Config:
        from_attributes = True


class ClockStatus(BaseModel):
    """Current clock status for a case"""

    case_id: str
    status: str  # "running" or "paused"
    original_due_date: datetime | None = None
    adjusted_due_date: datetime | None = None
    total_paused_days: int = 0
    current_pause_start: datetime | None = None
    current_pause_reason: ClockPauseReason | None = None
    events: list[ClockEvent] = Field(default_factory=list)


# =============================================================================
# Case Messages (Internal Staff Messaging)
# =============================================================================


class MessageCreate(BaseModel):
    """Create a new internal message"""

    content: str = Field(..., min_length=1, max_length=10000)
    mentions: list[str] = Field(default_factory=list)  # User IDs to @mention


class MessageUpdate(BaseModel):
    """Update an existing message"""

    content: str = Field(..., min_length=1, max_length=10000)


class CaseMessage(BaseModel):
    """Internal message on a case (staff-to-staff)"""

    id: str
    case_id: str
    author_id: str
    author_name: str  # Denormalized for display
    content: str
    mentions: list[str] = Field(default_factory=list)  # User IDs mentioned
    created_at: datetime = Field(default_factory=datetime.utcnow)
    edited_at: datetime | None = None

    class Config:
        from_attributes = True


# =============================================================================
# Case Contributors (Named Record Contributors)
# =============================================================================


class ContributorStatus(str, Enum):
    """Status of a contributor invitation"""

    INVITED = "invited"
    ACTIVE = "active"
    COMPLETED = "completed"
    EXPIRED = "expired"


class ContributorCreate(BaseModel):
    """Invite a new contributor to provide records"""

    name: str
    email: EmailStr
    department: str | None = None
    notes: str | None = None
    # Token expiration in days (default 14 days)
    token_expiration_days: int = Field(default=14, ge=1, le=90)


class ContributorUpdate(BaseModel):
    """Update contributor details"""

    name: str | None = None
    department: str | None = None
    notes: str | None = None
    status: ContributorStatus | None = None


class CaseContributor(BaseModel):
    """
    Named contributor who can upload records to a case.
    Supports both named contributors (tracked) and anonymous links.
    """

    id: str
    case_id: str
    name: str
    email: str
    department: str | None = None
    status: ContributorStatus = ContributorStatus.INVITED

    # Magic link access
    upload_token: str  # Hashed token for secure access
    token_expires_at: datetime

    # Tracking
    documents_uploaded: int = 0
    last_upload_at: datetime | None = None
    invited_by: str  # User ID who invited
    invited_by_name: str | None = None  # Denormalized

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    first_access_at: datetime | None = None
    last_access_at: datetime | None = None
    completed_at: datetime | None = None

    # Contributor confirmation
    records_confirmed: bool = False
    records_confirmed_at: datetime | None = None

    # Notes
    notes: str | None = None

    class Config:
        from_attributes = True


class BulkContributorCreate(BaseModel):
    """Bulk invite multiple contributors"""

    contributors: list[ContributorCreate]


class ContributorUploadInfo(BaseModel):
    """Public info returned when contributor accesses upload link"""

    contributor_id: str
    contributor_name: str
    case_tracking_number: str
    case_title: str
    org_name: str
    documents_uploaded: int
    uploaded_documents: list[dict] = Field(default_factory=list)  # List of their uploaded docs
    is_expired: bool
    expires_at: datetime
    records_confirmed: bool = False


# =============================================================================
# Case Reminders (Milestone Notifications)
# =============================================================================


class ReminderType(str, Enum):
    """Types of automated reminders"""

    DUE_DATE = "due_date"
    COLLECTION_DEADLINE = "collection_deadline"
    FEE_PENDING = "fee_pending"
    REVIEW_NOT_STARTED = "review_not_started"
    PACKAGE_NOT_GENERATED = "package_not_generated"
    CONTRIBUTOR_FOLLOWUP = "contributor_followup"
    CUSTOM = "custom"


class ReminderStatus(str, Enum):
    """Status of a reminder"""

    PENDING = "pending"
    SENT = "sent"
    DISMISSED = "dismissed"
    CANCELLED = "cancelled"


class ReminderCreate(BaseModel):
    """Create a custom reminder"""

    reminder_type: ReminderType = ReminderType.CUSTOM
    trigger_date: datetime
    recipient_ids: list[str]  # User IDs to notify
    message: str = Field(..., min_length=1, max_length=1000)


class CaseReminder(BaseModel):
    """Reminder/notification for a case milestone"""

    id: str
    case_id: str
    reminder_type: ReminderType
    trigger_date: datetime
    recipient_ids: list[str]
    message: str
    status: ReminderStatus = ReminderStatus.PENDING

    # Delivery tracking
    sent_at: datetime | None = None
    sent_via: list[str] = Field(default_factory=list)  # ["email", "in_app"]

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str | None = None  # User ID or "system"
    dismissed_by: str | None = None
    dismissed_at: datetime | None = None

    class Config:
        from_attributes = True


# =============================================================================
# All Records Uploaded Confirmation
# =============================================================================


class RecordsConfirmation(BaseModel):
    """Confirmation that all records have been uploaded for a case"""

    confirmed: bool
    confirmed_by: str | None = None  # User ID
    confirmed_by_name: str | None = None
    confirmed_at: datetime | None = None
    notes: str | None = None


class RecordsConfirmationCreate(BaseModel):
    """Confirm all records have been uploaded"""

    notes: str | None = None


# =============================================================================
# Priority Queue
# =============================================================================


class CasePriorityScore(BaseModel):
    """Calculated priority score for queue ordering"""

    case_id: str
    tracking_number: str
    title: str

    # Priority factors
    due_date: datetime | None = None
    days_until_due: int | None = None
    case_age_days: int = 0
    document_count: int = 0

    # Calculated score (higher = more urgent)
    priority_score: float = 0.0
    priority_override: int | None = None  # Manual override

    # Status info
    status: str
    workflow_stage: str | None = None
    clock_status: str = "running"
    analyst_ids: list[str] = Field(default_factory=list)


class QueueFilter(BaseModel):
    """Filters for the prioritized queue"""

    analyst_id: str | None = None
    workflow_stages: list[str] | None = None
    clock_status: str | None = None  # "running" or "paused"
    include_closed: bool = False
    limit: int = Field(default=50, le=200)
    offset: int = 0


# =============================================================================
# Request Transfer (to another public body)
# =============================================================================


class TransferCreate(BaseModel):
    """Transfer a request to another public body"""

    recipient_organization: str = Field(..., min_length=1, max_length=500)
    recipient_email: EmailStr
    recipient_name: str | None = None
    include_documents: bool = False  # Whether to include uploaded documents
    included_document_ids: list[str] | None = None  # Selective document inclusion
    transfer_reason: str = Field(..., min_length=1, max_length=2000)
    notes: str | None = None


class CaseTransfer(BaseModel):
    """Record of a case transfer"""

    id: str
    case_id: str
    tracking_number: str

    # Transfer details
    recipient_organization: str
    recipient_email: str
    recipient_name: str | None = None
    include_documents: bool = False
    included_document_ids: list[str] = Field(default_factory=list)  # Selective docs
    transfer_reason: str
    notes: str | None = None

    # Secure access
    access_token: str  # Hashed token for secure download
    token_expires_at: datetime

    # Status
    status: str = "pending"  # pending, accessed, downloaded, expired

    # Tracking
    transferred_by: str  # User ID
    transferred_by_name: str | None = None
    transferred_at: datetime = Field(default_factory=datetime.utcnow)
    accessed_at: datetime | None = None
    downloaded_at: datetime | None = None

    class Config:
        from_attributes = True


class TransferPackageInfo(BaseModel):
    """Public info returned when recipient accesses transfer link"""

    transfer_id: str
    case_tracking_number: str
    case_title: str
    case_description: str | None = None
    requester_name: str
    requester_email: str
    requester_organization: str | None = None
    transfer_reason: str
    transferred_from: str  # Org name
    transferred_at: datetime
    includes_documents: bool
    document_count: int = 0
    is_expired: bool
    expires_at: datetime
