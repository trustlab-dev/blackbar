from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class DocumentStatus(str, Enum):
    NEW = "new"
    UNDER_REVIEW = "under_review"
    REDACTION_REQUIRED = "redaction_required"
    REDACTION_IN_PROGRESS = "redaction_in_progress"
    READY_FOR_APPROVAL = "ready_for_approval"
    APPROVED = "approved"
    RELEASED = "released"
    WITHHELD = "withheld"


# Status display names and colors
STATUS_INFO = {
    DocumentStatus.NEW: {"label": "New", "color": "#6c757d"},
    DocumentStatus.UNDER_REVIEW: {"label": "Under Review", "color": "#0dcaf0"},
    DocumentStatus.REDACTION_REQUIRED: {"label": "Redaction Required", "color": "#ffc107"},
    DocumentStatus.REDACTION_IN_PROGRESS: {"label": "Redaction In Progress", "color": "#fd7e14"},
    DocumentStatus.READY_FOR_APPROVAL: {"label": "Ready for Approval", "color": "#20c997"},
    DocumentStatus.APPROVED: {"label": "Approved", "color": "#198754"},
    DocumentStatus.RELEASED: {"label": "Released", "color": "#0d6efd"},
    DocumentStatus.WITHHELD: {"label": "Withheld", "color": "#dc3545"},
}


class RedactionBox(BaseModel):
    x: float
    y: float
    width: float
    height: float
    page: int
    category: str | None = None  # Legacy: single category
    description: str | None = None

    # Multiple sections per redaction
    # sections: List of exemption section codes (e.g., ["S.22(1)", "S.14"])
    # primary_section: The main section (for display/sorting)
    # rationale: Long-form explanation for the redaction
    sections: list[str] = []  # Multiple exemption sections
    primary_section: str | None = None  # Main section for display
    rationale: str | None = None  # Long text field for detailed explanation

    # Redaction type and status
    type: str = "professional"  # professional, proposed
    status: str = "approved"  # approved, proposed, contested, rejected

    # Creation info
    created_by: str | None = None
    created_by_role: str | None = None  # analyst, legal, reviewer, etc.
    created_at: str | None = None

    # Approval workflow (for proposed redactions)
    proposed_by: str | None = None
    proposed_by_role: str | None = None
    proposed_reason: str | None = None
    approval_status: str | None = None  # pending, approved, rejected
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    review_notes: str | None = None

    # Contest tracking
    is_contested: bool = False
    active_contests: int = 0


class DocumentBase(BaseModel):
    filename: str
    upload_date: datetime


class DocumentCreate(DocumentBase):
    content: bytes  # Store as binary


class DocumentDB(DocumentBase):
    id: str
    file_hash: str
    redactions: list[RedactionBox] = []
