"""Tests for `src.core.authz` object-level checks when the principal has no id.

`get_current_user` always returns a principal with an id, so these cases are
not reachable through the normal dependencies today. They pin that the
helpers fail closed anyway: a missing id used to compare equal to missing
`user_id` / `created_by` / `privacy_officer_id` fields and grant access.
"""

from __future__ import annotations

import pytest

from src.core.authz import can_access_case, check_document_access

NO_ID_PRINCIPALS = [
    pytest.param({"role": "user"}, id="missing"),
    pytest.param({"role": "user", "id": None}, id="none"),
    pytest.param({"role": "user", "id": ""}, id="empty"),
]


@pytest.mark.parametrize("principal", NO_ID_PRINCIPALS)
def test_can_access_case_denies_principal_without_id(principal: dict) -> None:
    # No created_by / privacy_officer_id on the case: both read as None.
    assert can_access_case({"id": "case-1"}, principal) is False


@pytest.mark.parametrize("principal", NO_ID_PRINCIPALS)
def test_can_access_case_denies_id_less_team_entry_match(principal: dict) -> None:
    case = {"id": "case-1", "created_by": "u-1", "case_team": [{"status": "active"}]}
    assert can_access_case(case, principal) is False


@pytest.mark.parametrize("principal", NO_ID_PRINCIPALS)
def test_check_document_access_denies_team_principal_without_id(principal: dict) -> None:
    case = {"id": "case-1", "case_team": [{"status": "active", "role": "legal"}]}
    assert check_document_access({"case_id": "case-1"}, principal, case) is False


def test_check_document_access_denies_guest_without_id() -> None:
    doc = {"shared_with": [{"permission": "view"}]}
    assert check_document_access(doc, {"role": "guest"}) is False


def test_global_roles_still_allowed_without_id() -> None:
    # Global access does not depend on the id; unchanged by the guard.
    assert can_access_case({"id": "case-1"}, {"role": "admin"}) is True
    assert check_document_access({}, {"role": "analyst"}) is True


def test_principal_with_id_unchanged() -> None:
    case = {"id": "case-1", "case_team": [{"user_id": "u-1", "status": "active"}]}
    assert can_access_case(case, {"role": "user", "id": "u-1"}) is True
    assert check_document_access({}, {"role": "user", "id": "u-1"}, case) is True
    assert can_access_case(case, {"role": "user", "id": "u-2"}) is False
    doc = {"shared_with": [{"user_id": "g-1"}]}
    assert check_document_access(doc, {"role": "guest", "id": "g-1"}) is True
    assert check_document_access(doc, {"role": "guest", "id": "g-2"}) is False
