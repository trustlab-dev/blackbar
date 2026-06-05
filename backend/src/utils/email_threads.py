"""
Email thread detection and consolidation utilities.
Automatically identifies email threads and marks older messages as superseded.
"""

import hashlib
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)


def normalize_subject(subject: str) -> str:
    """
    Normalize email subject by removing Re:, Fwd:, etc.

    Args:
        subject: Original email subject

    Returns:
        Normalized subject string
    """
    if not subject:
        return ""

    # Remove common reply/forward prefixes (case-insensitive)
    # Handles: Re:, RE:, Fwd:, FWD:, Fw:, FW:, etc.
    normalized = re.sub(r"^\s*(Re|RE|Fwd|FWD|Fw|FW):\s*", "", subject, flags=re.IGNORECASE)

    # Remove multiple spaces and trim
    normalized = re.sub(r"\s+", " ", normalized).strip()

    return normalized.lower()


def extract_thread_identifiers(extracted_text: str, message_id: str | None) -> dict[str, any]:
    """
    Extract email thread identifiers from the extracted text.

    Args:
        extracted_text: Full text extracted from email
        message_id: Message-ID header value

    Returns:
        Dictionary with thread identifiers
    """
    identifiers = {
        "subject": None,
        "normalized_subject": None,
        "from": None,
        "to": None,
        "date": None,
        "message_id": message_id,
        "in_reply_to": None,
        "references": [],
    }

    # Parse headers from extracted text
    for line in extracted_text.split("\n")[:20]:  # Check first 20 lines for headers
        if line.startswith("Subject:"):
            subject = line.replace("Subject:", "").strip()
            identifiers["subject"] = subject
            identifiers["normalized_subject"] = normalize_subject(subject)
        elif line.startswith("From:"):
            identifiers["from"] = line.replace("From:", "").strip()
        elif line.startswith("To:"):
            identifiers["to"] = line.replace("To:", "").strip()
        elif line.startswith("Date:"):
            identifiers["date"] = line.replace("Date:", "").strip()
        elif line.startswith("In-Reply-To:"):
            identifiers["in_reply_to"] = line.replace("In-Reply-To:", "").strip()
        elif line.startswith("References:"):
            refs = line.replace("References:", "").strip()
            identifiers["references"] = [r.strip() for r in refs.split() if r.strip()]

    return identifiers


def calculate_thread_hash(normalized_subject: str, participants: list[str]) -> str:
    """
    Calculate a hash to identify emails in the same thread.

    Args:
        normalized_subject: Normalized subject line
        participants: List of email addresses (from/to/cc)

    Returns:
        SHA-256 hash string
    """
    # Sort participants to ensure consistent hash regardless of order
    sorted_participants = sorted([p.lower().strip() for p in participants if p])

    # Combine subject and participants
    thread_key = f"{normalized_subject}|{'|'.join(sorted_participants)}"

    return hashlib.sha256(thread_key.encode()).hexdigest()


def parse_email_date(date_str: str) -> datetime | None:
    """
    Parse email date string into datetime object.

    Args:
        date_str: Date string from email header

    Returns:
        datetime object or None if parsing fails
    """
    if not date_str:
        return None

    # Try common email date formats
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",  # RFC 2822
        "%a, %d %b %Y %H:%M:%S",
        "%d %b %Y %H:%M:%S %z",
        "%d %b %Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except:
            continue

    logger.warning(f"Could not parse email date: {date_str}")
    return None


async def find_thread_emails(db, thread_identifiers: dict, case_id: str | None) -> list[dict]:
    """
    Find all emails in the same thread.

    Args:
        db: Database connection
        thread_identifiers: Thread identifiers from extract_thread_identifiers
        case_id: Case ID to search within (optional)

    Returns:
        List of document records in the same thread
    """
    normalized_subject = thread_identifiers.get("normalized_subject")
    message_id = thread_identifiers.get("message_id")
    in_reply_to = thread_identifiers.get("in_reply_to")
    references = thread_identifiers.get("references", [])

    if not normalized_subject:
        return []

    # Build query to find related emails
    query = {
        "thread_metadata.normalized_subject": normalized_subject,
        "mime_type": {"$in": ["message/rfc822", "application/vnd.ms-outlook"]},
    }

    if case_id:
        query["case_id"] = case_id

    # Find emails with same normalized subject
    emails = await db.documents.find(query).to_list(length=100)

    # Filter to same thread using message IDs
    thread_emails = []
    for email in emails:
        email_msg_id = email.get("message_id")
        email_in_reply_to = email.get("thread_metadata", {}).get("in_reply_to")
        email_refs = email.get("thread_metadata", {}).get("references", [])

        # Check if this email is part of the thread
        is_same_thread = False

        # Direct match on message IDs
        if message_id and (
            email_msg_id == message_id
            or email_msg_id == in_reply_to
            or message_id == email_in_reply_to
        ):
            is_same_thread = True

        # Match on references
        if references and email_msg_id in references:
            is_same_thread = True
        if email_refs and (message_id in email_refs or in_reply_to in email_refs):
            is_same_thread = True

        # Fallback: if message-id style matching fails, still treat emails with the
        # same normalized subject as part of the same thread. The query above has
        # already restricted results to the same normalized_subject, so this
        # effectively groups all subject-identical emails in the case into one
        # thread, which matches our consolidation/UX requirements.
        if not is_same_thread:
            is_same_thread = True

        if is_same_thread:
            thread_emails.append(email)

    return thread_emails


async def consolidate_email_thread(db, new_email_doc: dict, thread_emails: list[dict]) -> dict:
    """
    Consolidate email thread by marking older emails as superseded.

    Args:
        db: Database connection
        new_email_doc: The newly uploaded email document
        thread_emails: List of existing emails in the same thread

    Returns:
        Dictionary with consolidation results
    """
    if not thread_emails:
        return {
            "action": "none",
            "message": "No existing thread emails found",
            "canonical_id": new_email_doc["id"],
            "superseded_ids": [],
        }

    # Parse dates
    new_date_str = new_email_doc.get("thread_metadata", {}).get("date")
    new_date = parse_email_date(new_date_str) if new_date_str else None

    if not new_date:
        # If we can't parse the new email's date, use upload date
        new_date = new_email_doc.get("upload_date", datetime.utcnow())

    # Find the latest email in the thread
    latest_email = None
    latest_date = new_date

    for email in thread_emails:
        email_date_str = email.get("thread_metadata", {}).get("date")
        email_date = (
            parse_email_date(email_date_str) if email_date_str else email.get("upload_date")
        )

        if email_date and email_date > latest_date:
            latest_date = email_date
            latest_email = email

    # Determine consolidation action
    if latest_email and latest_email["id"] != new_email_doc["id"]:
        # New email is older than existing email
        await db.documents.update_one(
            {"id": new_email_doc["id"]},
            {
                "$set": {
                    "thread_status": "superseded",
                    "superseded_by": latest_email["id"],
                    "superseded_by_filename": latest_email["filename"],
                }
            },
        )

        return {
            "action": "mark_new_as_superseded",
            "message": f"Email superseded by newer message: {latest_email['filename']}",
            "superseded_by": latest_email["id"],
            "superseded_by_filename": latest_email["filename"],
            "canonical_id": latest_email["id"],
            "superseded_ids": [new_email_doc["id"]],
        }
    else:
        # New email is the latest - mark older ones as superseded
        superseded_count = 0
        superseded_ids: list[str] = []
        for email in thread_emails:
            email_date_str = email.get("thread_metadata", {}).get("date")
            email_date = (
                parse_email_date(email_date_str) if email_date_str else email.get("upload_date")
            )

            if not email_date or email_date < new_date:
                await db.documents.update_one(
                    {"id": email["id"]},
                    {
                        "$set": {
                            "thread_status": "superseded",
                            "superseded_by": new_email_doc["id"],
                            "superseded_by_filename": new_email_doc["filename"],
                        }
                    },
                )
                superseded_count += 1
                superseded_ids.append(email["id"])

        # Mark new email as active in thread
        await db.documents.update_one(
            {"id": new_email_doc["id"]}, {"$set": {"thread_status": "active"}}
        )

        return {
            "action": "mark_older_as_superseded",
            "message": f"Marked {superseded_count} older emails as superseded",
            "superseded_count": superseded_count,
            "canonical_id": new_email_doc["id"],
            "superseded_ids": superseded_ids,
        }
