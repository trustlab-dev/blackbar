"""
Document Collection Links
Allows external users to upload documents to a case via a secure link
"""

import secrets
import string
from datetime import UTC, datetime

from pydantic import BaseModel, EmailStr


def generate_collection_token(length: int = 32) -> str:
    """Generate a secure random token for collection links"""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class CollectionLinkCreate(BaseModel):
    """Create a new collection link"""

    case_id: str
    expires_at: datetime | None = None
    max_uploads: int | None = None  # Optional limit on number of uploads
    notes: str | None = None  # Internal notes about this link


class CollectionLinkDB(BaseModel):
    """Collection link stored in database"""

    id: str
    case_id: str
    token: str  # Secure token used in URL
    created_by: str
    created_at: datetime
    expires_at: datetime | None = None
    max_uploads: int | None = None
    upload_count: int = 0
    is_active: bool = True
    notes: str | None = None


class DocumentSubmission(BaseModel):
    """Information about who is submitting documents"""

    submitter_name: str
    submitter_email: EmailStr
    notes: str | None = None  # Optional notes from submitter


def is_link_valid(link: dict) -> tuple[bool, str]:
    """
    Check if a collection link is valid
    Returns: (is_valid, error_message)
    """
    if not link.get("is_active"):
        return False, "This collection link has been deactivated"

    # Check expiration.
    # Both sides of the comparison must agree on tz-awareness. Parsing a
    # JSON-serialized 'Z'-suffixed ISO string produces a tz-aware datetime,
    # so we compute "now" as tz-aware UTC to match (B11). Naive expires_at
    # values (e.g. read directly from MongoDB) are normalized to UTC-aware
    # before comparison.
    if link.get("expires_at"):
        expires_at = link["expires_at"]
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if datetime.now(UTC) > expires_at:
            return False, "This collection link has expired"

    # Check upload limit
    if link.get("max_uploads"):
        if link.get("upload_count", 0) >= link["max_uploads"]:
            return False, "This collection link has reached its upload limit"

    return True, ""
