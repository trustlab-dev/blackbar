"""Canonical object-level authorization helpers.

Two role systems exist in BlackBar; this module concerns the **system role**
on the user record (``current_user["role"]``): one of ``owner``, ``admin``,
``analyst``, ``user``, ``guest``. (Case-team roles like ``manager``/``legal``
live on ``case_team`` entries and are handled by ``cases.permissions``.)

Access model (EPIC-001 / ISSUE-018 — "analysts are global reviewers"):

- ``owner`` / ``admin`` / ``analyst``: may access any case or document.
- ``guest``: only documents explicitly shared with them.
- ``user``: only cases/documents for teams they belong to (or that they are
  assigned to / created / are the privacy officer of).

A role gate (``dependencies.check_role``) only checks *which* role the caller
has — it does NOT check that the caller may reach *this* object. Handlers that
take an object id MUST additionally call one of the ``assert_*`` helpers below,
or any same-role user can reach any object (IDOR).
"""

from __future__ import annotations

from fastapi import HTTPException

from src.cases.permissions import is_case_team_member

# System roles granted unrestricted access across all cases/documents.
GLOBAL_ACCESS_ROLES = ("owner", "admin", "analyst")


def has_global_access(current_user: dict) -> bool:
    """True for system roles that may reach any case/document."""
    return current_user.get("role") in GLOBAL_ACCESS_ROLES


def check_document_access(doc: dict, current_user: dict, case: dict | None = None) -> bool:
    """Return True if ``current_user`` may access ``doc``.

    owner/admin/analyst: always. guest: only via an explicit ``shared_with``
    entry. user: only if an active member of the document's case team (``case``
    must be supplied).
    """
    user_id = current_user.get("id")

    if has_global_access(current_user):
        return True

    if current_user.get("role") == "guest":
        return any(share.get("user_id") == user_id for share in doc.get("shared_with", []))

    if case:
        return is_case_team_member(case.get("case_team", []), user_id)

    return False


def can_access_case(case: dict, current_user: dict) -> bool:
    """Return True if ``current_user`` may access ``case``.

    owner/admin/analyst: always. Otherwise: active case-team member, assigned
    user, creator, or privacy officer.
    """
    if has_global_access(current_user):
        return True

    user_id = current_user.get("id")
    if is_case_team_member(case.get("case_team", []), user_id):
        return True
    if user_id in case.get("assigned_user_ids", []):
        return True
    if user_id in (case.get("created_by"), case.get("privacy_officer_id")):
        return True
    return False


def assert_document_access(doc: dict, current_user: dict, case: dict | None = None) -> None:
    """Raise 403 unless ``current_user`` may access ``doc``."""
    if not check_document_access(doc, current_user, case):
        raise HTTPException(status_code=403, detail="You don't have access to this document")


def assert_case_access(case: dict | None, current_user: dict) -> None:
    """Raise 403 unless ``current_user`` may access ``case`` (also 403 if the
    case is missing, so callers can gate before disclosing existence)."""
    if case is None or not can_access_case(case, current_user):
        raise HTTPException(status_code=403, detail="You don't have access to this case")
