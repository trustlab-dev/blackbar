"""
Email thread detection and consolidation utilities.
Automatically identifies email threads and marks older messages as superseded.
"""

import hashlib
import logging
import re
from datetime import UTC, datetime, timedelta
from email.utils import getaddresses, parsedate_to_datetime

logger = logging.getLogger(__name__)

EMAIL_MIME_TYPES = ["message/rfc822", "application/vnd.ms-outlook"]

# Leading reply/forward markers (English and common localised forms, with an
# optional "[n]" counter) or a bracketed tag such as "[External]".
_SUBJECT_PREFIX_RE = re.compile(
    r"^\s*(?:(?:re|fwd?|aw|wg|sv|vs|antw|tr|rv)(?:\s*\[\d+\])?\s*:|\[[^\]]*\])\s*",
    flags=re.IGNORECASE,
)

# Fields find_thread_emails needs; never pull content or OCR data.
THREAD_EMAIL_PROJECTION = {
    "_id": 0,
    "id": 1,
    "filename": 1,
    "message_id": 1,
    "thread_metadata": 1,
    "upload_date": 1,
}

# Subject-only matching is a heuristic of last resort: it applies only when the
# two emails share at least one From/To participant AND their Date headers are
# no more than this far apart. Header links (Message-ID / In-Reply-To /
# References) are always preferred.
SUBJECT_HEURISTIC_WINDOW = timedelta(days=30)

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


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

    # Strip stacked reply/forward prefixes and bracketed tags, e.g.
    # "Re: [External] Fwd: RE: Budget" -> "Budget".
    normalized = subject
    while True:
        stripped = _SUBJECT_PREFIX_RE.sub("", normalized, count=1)
        if stripped == normalized:
            break
        normalized = stripped

    # Remove multiple spaces and trim
    normalized = re.sub(r"\s+", " ", normalized).strip()

    return normalized.lower()


def thread_identifiers_from_headers(
    headers: dict | None, message_id: str | None = None
) -> dict[str, any] | None:
    """Thread identifiers from structured headers parsed off the message
    object at conversion time (I7; see ``conversion.read_thread_headers``).

    ``message_id`` (the document's own Message-ID) wins over the header
    copy so the identifiers match the stored document. Returns None when
    there is nothing to thread on.
    """
    headers = headers or {}

    def _text(name: str) -> str | None:
        value = headers.get(name)
        if not isinstance(value, str):
            return None
        value = " ".join(value.split())
        return value or None

    references = headers.get("references") or []
    if isinstance(references, str):
        references = references.split()
    subject = _text("subject")
    identifiers = {
        "subject": subject,
        "normalized_subject": normalize_subject(subject) if subject else None,
        "from": _text("from"),
        "to": _text("to"),
        "date": _text("date"),
        "message_id": message_id or _text("message_id"),
        "in_reply_to": _text("in_reply_to"),
        "references": [r for r in references if isinstance(r, str) and r.strip()],
    }
    if not any(
        identifiers[k] for k in ("message_id", "in_reply_to", "references", "normalized_subject")
    ):
        return None
    return identifiers


def extract_thread_identifiers(extracted_text: str, message_id: str | None) -> dict[str, any]:
    """
    Legacy: parse thread identifiers from the header block at the top of an
    email's extracted text. New uploads use ``thread_identifiers_from_headers``
    with headers read from the message itself; this remains for records
    that only have text.

    Only the header block is read: it ends at the first blank or non-header
    line, folded continuation lines are joined to their header, and the
    first occurrence of a header wins, so a quoted reply cannot overwrite it.
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

    headers: dict[str, str] = {}
    current: str | None = None
    for line in extracted_text.split("\n"):
        if not line.strip():
            break
        if line[:1] in (" ", "\t") and current:
            headers[current] += " " + line.strip()
            continue
        name, sep, value = line.partition(":")
        name = name.strip().lower()
        if not sep or not name or " " in name:
            break  # not a header line: the header block is over
        current = name
        if current not in headers:
            headers[current] = value.strip()
        else:
            current = None  # repeated header: keep the first

    subject = headers.get("subject")
    if subject:
        identifiers["subject"] = subject
        identifiers["normalized_subject"] = normalize_subject(subject)
    identifiers["from"] = headers.get("from") or None
    identifiers["to"] = headers.get("to") or None
    identifiers["date"] = headers.get("date") or None
    identifiers["in_reply_to"] = headers.get("in-reply-to") or None
    refs = headers.get("references")
    if refs:
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


def _as_utc(value: object) -> datetime | None:
    """Return an aware UTC datetime; naive values are taken to be UTC."""
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_email_date(date_str: str | None) -> datetime | None:
    """
    Parse email date string into a timezone-aware UTC datetime.

    RFC 2822 dates go through ``email.utils.parsedate_to_datetime``; ISO
    strings (as produced by extract_msg) are also accepted. A date without
    a zone is treated as UTC so every result is comparable.

    Args:
        date_str: Date string from email header

    Returns:
        aware UTC datetime, or None if parsing fails
    """
    if not date_str or not isinstance(date_str, str):
        return None
    value = date_str.strip()

    parsed: datetime | None = None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        parsed = None

    if parsed is None:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            parsed = None

    if parsed is None:
        for fmt in ("%d %b %Y %H:%M:%S %z", "%d %b %Y %H:%M:%S"):
            try:
                parsed = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue

    if parsed is None:
        if value.lower() != "unknown":
            logger.warning(f"Could not parse email date: {date_str}")
        return None
    return _as_utc(parsed)


def _linked_ids(in_reply_to: object, references: object) -> set[str]:
    ids: set[str] = set()
    if isinstance(in_reply_to, str) and in_reply_to:
        ids.add(in_reply_to)
    if isinstance(references, list):
        ids.update(r for r in references if isinstance(r, str) and r)
    return ids


def _participants(metadata: dict) -> set[str]:
    fields = [v for v in (metadata.get("from"), metadata.get("to")) if isinstance(v, str)]
    return {addr.strip().lower() for _, addr in getaddresses(fields) if addr and "@" in addr}


def _is_header_linked(email: dict, message_id: str | None, linked: set[str]) -> bool:
    metadata = email.get("thread_metadata") or {}
    email_msg_id = email.get("message_id")
    email_linked = _linked_ids(metadata.get("in_reply_to"), metadata.get("references"))
    if message_id and email_msg_id == message_id:
        return True
    if email_msg_id and email_msg_id in linked:
        return True
    if message_id and message_id in email_linked:
        return True
    return bool(linked & email_linked)


def _matches_subject_heuristic(email: dict, identifiers: dict) -> bool:
    """Same normalised subject, shared participant, dates within the window."""
    metadata = email.get("thread_metadata") or {}
    subject = identifiers.get("normalized_subject")
    if not subject or metadata.get("normalized_subject") != subject:
        return False
    if not _participants(identifiers) & _participants(metadata):
        return False
    new_date = parse_email_date(identifiers.get("date"))
    other_date = parse_email_date(metadata.get("date"))
    if new_date is None or other_date is None:
        return False
    return abs(new_date - other_date) <= SUBJECT_HEURISTIC_WINDOW


async def find_thread_emails(
    db, thread_identifiers: dict, case_id: str | None, exclude_id: str | None = None
) -> list[dict]:
    """
    Find the emails in the same case that belong to the same thread.

    Emails are linked by Message-ID / In-Reply-To / References. The
    normalised subject is used only as a scoped heuristic: same subject, at
    least one shared From/To participant and Date headers within
    ``SUBJECT_HEURISTIC_WINDOW``. Matching never spans cases, so an email
    without a case is never threaded.

    Args:
        db: Database connection
        thread_identifiers: Thread identifiers from thread_identifiers_from_headers
        case_id: Case ID to search within (required)
        exclude_id: Document ID to leave out (the new email's own record)

    Returns:
        List of document records (projected) in the same thread
    """
    if not case_id:
        logger.info("Skipping thread matching for an email with no case_id")
        return []

    normalized_subject = thread_identifiers.get("normalized_subject")
    message_id = thread_identifiers.get("message_id")
    linked = _linked_ids(
        thread_identifiers.get("in_reply_to"), thread_identifiers.get("references")
    )

    clauses: list[dict] = []
    if normalized_subject:
        clauses.append({"thread_metadata.normalized_subject": normalized_subject})
    if linked:
        linked_list = sorted(linked)
        clauses.append({"message_id": {"$in": linked_list}})
        clauses.append({"thread_metadata.in_reply_to": {"$in": linked_list}})
        clauses.append({"thread_metadata.references": {"$in": linked_list}})
    if message_id:
        clauses.append({"message_id": message_id})
        clauses.append({"thread_metadata.in_reply_to": message_id})
        clauses.append({"thread_metadata.references": message_id})
    if not clauses:
        return []

    query: dict = {
        "case_id": case_id,
        "mime_type": {"$in": EMAIL_MIME_TYPES},
        "$or": clauses,
    }
    if exclude_id:
        query["id"] = {"$ne": exclude_id}

    # Iterate the whole cursor: every candidate must be considered (a capped
    # to_list silently dropped the rest of a large thread).
    thread_emails = []
    async for email in db.documents.find(query, THREAD_EMAIL_PROJECTION):
        if exclude_id and email.get("id") == exclude_id:
            continue
        if _is_header_linked(email, message_id, linked) or _matches_subject_heuristic(
            email, thread_identifiers
        ):
            thread_emails.append(email)

    return thread_emails


def _thread_sort_key(doc: dict) -> tuple[int, datetime]:
    """Order emails by their own Date header; undated emails sort below
    every dated one and fall back to upload_date among themselves."""
    header_date = parse_email_date((doc.get("thread_metadata") or {}).get("date"))
    if header_date is not None:
        return (1, header_date)
    return (0, _as_utc(doc.get("upload_date")) or _EPOCH)


async def consolidate_email_thread(db, new_email_doc: dict, thread_emails: list[dict]) -> dict:
    """
    Consolidate email thread by marking older emails as superseded.

    Args:
        db: Database connection
        new_email_doc: The newly uploaded email document (with thread_metadata)
        thread_emails: List of existing emails in the same thread

    Returns:
        Dictionary with consolidation results
    """
    new_id = new_email_doc["id"]
    # The new email's own record must never take part in its own thread.
    thread_emails = [e for e in thread_emails if e.get("id") != new_id]

    if not thread_emails:
        return {
            "action": "none",
            "message": "No existing thread emails found",
            "canonical_id": new_id,
            "superseded_ids": [],
        }

    new_key = _thread_sort_key(new_email_doc)

    # Find the latest email in the thread
    latest_email = None
    latest_key = new_key
    for email in thread_emails:
        key = _thread_sort_key(email)
        if key > latest_key:
            latest_key = key
            latest_email = email

    # Determine consolidation action
    if latest_email is not None:
        # New email is older than existing email
        await db.documents.update_one(
            {"id": new_id},
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
            "superseded_ids": [new_id],
        }

    # New email is the latest - mark older ones as superseded
    superseded_ids: list[str] = []
    for email in thread_emails:
        if _thread_sort_key(email) < new_key:
            await db.documents.update_one(
                {"id": email["id"]},
                {
                    "$set": {
                        "thread_status": "superseded",
                        "superseded_by": new_id,
                        "superseded_by_filename": new_email_doc["filename"],
                    }
                },
            )
            superseded_ids.append(email["id"])

    # Mark new email as active in thread
    await db.documents.update_one({"id": new_id}, {"$set": {"thread_status": "active"}})

    return {
        "action": "mark_older_as_superseded",
        "message": f"Marked {len(superseded_ids)} older emails as superseded",
        "superseded_count": len(superseded_ids),
        "canonical_id": new_id,
        "superseded_ids": superseded_ids,
    }
