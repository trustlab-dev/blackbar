"""Test data factories.

Use these in tests to avoid hard-coding entire User/Case/Document dicts
into every test. Each factory returns a dict ready to insert into Mongo
(matching the Pydantic DB-model shape so a subsequent `Model(**doc)`
roundtrip succeeds). Keep factories minimal — only override fields the
test cares about; defaults are sane.

Pattern: `make_<entity>(**overrides)` returns `dict[str, Any]`.
Field shapes mirror the live Pydantic models:
- `src.users.models.User`
- `src.cases.models.CaseDB`
- `src.documents.models.DocumentDB`

If a test needs a fully validated Pydantic instance, wrap the dict:
    user = User(**make_user(role="admin"))
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any


def _utcnow() -> datetime:
    """Naive UTC timestamp matching what `datetime.utcnow()` produces.

    The codebase uses naive UTC across all DB writes today (`datetime.utcnow()`
    in models' default_factory). Factories match that shape so equality
    comparisons in tests work cleanly. Migration to timezone-aware datetimes
    is tracked outside Phase 2 infrastructure.
    """
    return datetime.utcnow()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def make_user(**overrides: Any) -> dict[str, Any]:
    """Build a `users` collection document.

    Matches `src.users.models.User`. The repository's `create()` method
    assigns `id` and `password_hash` itself; this factory mimics the
    post-insert shape so tests can write directly to `db.users` and then
    read back via `UsersRepository.get_by_id`.
    """
    base: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "email": f"u-{secrets.token_hex(4)}@example.test",
        "name": "Test User",
        "status": "active",
        "password_hash": "$2b$12$KIXxPfn0jKkDdjBYwCi3kuPLAS2VnPb2/Y3iN6JuPVjFvGsM8m/Vy",
        "external_id": None,
        "role": "user",
        "activation_token": None,
        "activation_token_expires_at": None,
        "created_at": _utcnow(),
        "updated_at": _utcnow(),
    }
    return {**base, **overrides}


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


def make_case(**overrides: Any) -> dict[str, Any]:
    """Build a `cases` collection document.

    Matches `src.cases.models.CaseDB`. `requester`, `assignee`,
    `work_team_id`, etc. default to None; tests override per their scope.
    Tracking number format mirrors what `cases.utils.generate_tracking_number`
    emits (FOI-YYYY-NNN-XXX).
    """
    now = _utcnow()
    base: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "tracking_number": f"FOI-{now.year}-{secrets.randbelow(9999):04d}-{secrets.token_hex(2).upper()}",
        "title": "Test FOI Request",
        "description": "Synthetic case for tests.",
        "status": "new",
        "priority": "medium",
        "due_date": now + timedelta(days=30),
        "tags": [],
        "metadata": {},
        # Requester (None for internal cases — see public_routes for the
        # populated shape)
        "requester": None,
        # Assignment
        "assigned_user_ids": [],
        "privacy_officer_id": None,
        "assignee": None,
        "team": None,
        "work_team_id": None,
        "case_team": [],
        # Tracking
        "received_date": now,
        "extended_due_date": None,
        "workflow_stage": None,
        "estimated_completion": None,
        "created_at": now,
        "updated_at": now,
        # Statutory clock
        "clock_status": "running",
        "clock_paused_at": None,
        "clock_pause_reason": None,
        "total_paused_days": 0,
        "adjusted_due_date": None,
        # Records confirmation
        "all_records_uploaded": False,
        "all_records_confirmed_by": None,
        "all_records_confirmed_by_name": None,
        "all_records_confirmed_at": None,
        "all_records_confirmation_notes": None,
        # Priority override
        "priority_override": None,
        # Comments / audit
        "comments": [],
        "audit_log": [],
        # Documents
        "document_ids": [],
        # Creator
        "created_by": "test-user",
    }
    return {**base, **overrides}


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


def make_document(**overrides: Any) -> dict[str, Any]:
    """Build a `documents` collection document.

    Matches the minimum `src.documents.models.DocumentDB` shape (id,
    filename, upload_date, file_hash, redactions). The real document
    pipeline writes many more fields (status, case_id, page_count, etc.)
    via `src.documents.processing_service`; tests that exercise the
    pipeline directly should override those fields explicitly to make
    intent obvious. Defaults here cover the bare-minimum invariants the
    Pydantic model enforces.
    """
    base: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "filename": f"doc-{secrets.token_hex(4)}.pdf",
        "upload_date": _utcnow(),
        "file_hash": secrets.token_hex(32),
        "redactions": [],
    }
    return {**base, **overrides}
