from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, EmailStr, Field


class CaseStatus(str, Enum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    CLOSED = "closed"


class CasePriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CommentType(str, Enum):
    INTERNAL = "internal"
    PUBLIC = "public"


class Requester(BaseModel):
    """Information about the person making the FOI request"""

    name: str
    email: EmailStr
    phone: str | None = None
    organization: str | None = None


class Comment(BaseModel):
    """Case comment (internal or public)"""

    id: str
    author_id: str
    author_name: str
    text: str
    type: CommentType = CommentType.INTERNAL
    created_at: datetime | None = None


class AuditLogEntry(BaseModel):
    """Audit log entry for case actions"""

    action: str  # e.g., "case_created", "assigned", "status_changed"
    user_id: str
    username: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    details: dict[str, Any] = Field(default_factory=dict)


class CaseTeamMember(BaseModel):
    """Member of a case-specific collaboration team"""

    user_id: str
    role: str  # analyst, legal, sme, reviewer, approver, third_party, manager
    department: str | None = None
    permissions: list[str] = Field(default_factory=list)  # Derived from role
    added_at: datetime = Field(default_factory=datetime.utcnow)
    added_by: str  # User ID who added this member
    status: str = "active"  # active, removed
    notes: str | None = None
    review_status: str | None = None  # pending, in_review, approved, rejected
    review_completed_at: datetime | None = None
    approval_status: str | None = None  # For approvers: pending, approved, rejected


class CaseBase(BaseModel):
    title: str
    description: str | None = None
    status: CaseStatus = CaseStatus.NEW
    priority: CasePriority = CasePriority.MEDIUM
    due_date: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CaseCreate(CaseBase):
    """Create a new case (internal use)"""

    assigned_user_ids: list[str] = Field(default_factory=list)
    privacy_officer_id: str | None = None
    requester: Requester | None = None  # Optional for internal cases
    assignee: str | None = None  # Single assignee (primary)
    team: str | None = None  # Team assignment


class PublicRequestCreate(BaseModel):
    """Public FOI request submission (no auth required)"""

    title: str
    description: str
    category: str | None = None
    requester: Requester


class CaseUpdate(BaseModel):
    """Update case fields"""

    title: str | None = None
    description: str | None = None
    status: CaseStatus | None = None
    priority: CasePriority | None = None
    assigned_user_ids: list[str] | None = None  # Multiple analysts
    privacy_officer_id: str | None = None
    assignee: str | None = None
    team: str | None = None
    category: str | None = None
    due_date: datetime | None = None
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None
    # Workflow stage
    workflow_stage: str | None = None
    # Priority override
    priority_override: int | None = None


class CommentCreate(BaseModel):
    """Create a new comment"""

    text: str
    type: CommentType = CommentType.INTERNAL


class CaseDB(CaseBase):
    """Complete case document in database"""

    id: str
    tracking_number: str  # e.g., "FOI-2024-001-ABC"

    # Requester info
    requester: Requester | None = None

    # Assignment (organizational)
    assigned_user_ids: list[str] = Field(default_factory=list)  # Multiple analysts
    privacy_officer_id: str | None = None
    assignee: str | None = None  # Primary assignee (assigned_to)
    team: str | None = None  # Legacy field
    work_team_id: str | None = None  # Organizational team for workload distribution

    # Case-specific collaboration team
    case_team: list[CaseTeamMember] = Field(default_factory=list)

    # Tracking
    received_date: datetime = Field(default_factory=datetime.utcnow)
    extended_due_date: datetime | None = None
    workflow_stage: str | None = (
        None  # intake, collection, review, redaction, approval, release, pending_fee_payment, privacy_commission_review, closed
    )
    estimated_completion: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Statutory clock management
    clock_status: str = "running"  # running, paused
    clock_paused_at: datetime | None = None
    clock_pause_reason: str | None = None
    total_paused_days: int = 0
    adjusted_due_date: datetime | None = None

    # Records confirmation
    all_records_uploaded: bool = False
    all_records_confirmed_by: str | None = None
    all_records_confirmed_by_name: str | None = None
    all_records_confirmed_at: datetime | None = None
    all_records_confirmation_notes: str | None = None

    # Priority override
    priority_override: int | None = None

    # Comments and audit
    comments: list[Comment] = Field(default_factory=list)
    audit_log: list[AuditLogEntry] = Field(default_factory=list)

    # Documents
    document_ids: list[str] = Field(default_factory=list)
    created_by: str  # User ID of creator (or "system" for public requests)
