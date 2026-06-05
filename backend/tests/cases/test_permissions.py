"""Tests for `src.cases.permissions` — case-team RBAC pure-function module.

The module exposes two distinct concerns:

1. **Case-team role permissions** — `ROLE_PERMISSIONS` maps case-team roles
   (`manager`, `analyst`, `legal`, `sme`, `reviewer`, `approver`, `third_party`)
   to action lists. NOTE these are NOT the 4-tier user roles
   (`admin`/`analyst`/`user`/`guest`) — case-team roles are a separate concept
   tracked per case in `CaseDB.case_team`. The audit's "4 canonical roles"
   refers to user-level roles; this module operates on case-team roles only.
   See finding pinned below.

2. **Case-team membership lookup** — `is_case_team_member`,
   `get_user_role_on_case` walk a `List[Dict]` of team-member docs and filter
   on `status == "active"`.

Pure functions, no DB I/O. Tests are unit-level with inline dict construction;
no fixtures required.
"""

from __future__ import annotations

import pytest

from src.cases import permissions

# All case-team roles defined in ROLE_PERMISSIONS
ALL_CASE_TEAM_ROLES = [
    "manager",
    "analyst",
    "legal",
    "sme",
    "reviewer",
    "approver",
    "third_party",
]


class TestGetPermissionsForRole:
    """`get_permissions_for_role` — dictionary lookup with case-insensitive key
    and unknown-role fallback to empty list."""

    @pytest.mark.parametrize("role", ALL_CASE_TEAM_ROLES)
    def test_known_role_returns_non_empty_list(self, role: str) -> None:
        result = permissions.get_permissions_for_role(role)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_manager_full_permissions(self) -> None:
        perms = permissions.get_permissions_for_role("manager")
        # Manager is the top role: should have every gated action.
        assert "view" in perms
        assert "edit" in perms
        assert "redact" in perms
        assert "upload" in perms
        assert "comment" in perms
        assert "manage_team" in perms
        assert "propose_redactions" in perms
        assert "contest_redactions" in perms
        assert "reject_documents" in perms
        assert "approve_release" in perms

    def test_analyst_permissions(self) -> None:
        perms = permissions.get_permissions_for_role("analyst")
        assert "approve_proposed_redactions" in perms
        # Analyst is NOT a release approver
        assert "approve_release" not in perms

    def test_legal_permissions(self) -> None:
        perms = permissions.get_permissions_for_role("legal")
        assert "view" in perms
        assert "propose_redactions" in perms
        # Legal cannot create black redactions or upload
        assert "redact" not in perms
        assert "upload" not in perms

    def test_sme_permissions(self) -> None:
        perms = permissions.get_permissions_for_role("sme")
        assert perms == ["view", "comment", "upload"]

    def test_reviewer_permissions(self) -> None:
        perms = permissions.get_permissions_for_role("reviewer")
        assert "reject_documents" in perms
        assert "propose_redactions" in perms
        assert "approve_release" not in perms

    def test_approver_permissions(self) -> None:
        perms = permissions.get_permissions_for_role("approver")
        assert "approve_release" in perms
        assert "reject_documents" in perms
        # Approver propose-only, no contest
        assert "contest_redactions" not in perms

    def test_third_party_permissions(self) -> None:
        perms = permissions.get_permissions_for_role("third_party")
        assert "propose_redactions" in perms
        assert "redact" not in perms
        assert "approve_release" not in perms

    def test_unknown_role_returns_empty_list(self) -> None:
        assert permissions.get_permissions_for_role("nonexistent") == []

    def test_empty_string_returns_empty_list(self) -> None:
        assert permissions.get_permissions_for_role("") == []

    @pytest.mark.parametrize(
        "variant",
        ["MANAGER", "Manager", "MaNaGeR", "manager"],
    )
    def test_role_lookup_is_case_insensitive(self, variant: str) -> None:
        # Confirms `.lower()` is applied on lookup.
        assert "approve_release" in permissions.get_permissions_for_role(variant)

    def test_4tier_user_role_not_recognized_as_case_team_role(self) -> None:
        # Pinned reality: passing a user-level role name (e.g. "admin", "user",
        # "guest") returns []. These are not case-team roles. Callers must
        # resolve the user's per-case role via `get_user_role_on_case` first.
        assert permissions.get_permissions_for_role("admin") == []
        assert permissions.get_permissions_for_role("user") == []
        assert permissions.get_permissions_for_role("guest") == []


class TestCanUserPerformAction:
    """`can_user_perform_action(role, action)` — composition of
    `get_permissions_for_role` + `in` check."""

    @pytest.mark.parametrize(
        "role,action,expected",
        [
            # Manager can do everything
            ("manager", "view", True),
            ("manager", "approve_release", True),
            ("manager", "manage_team", True),
            # Analyst gated out of approve_release
            ("analyst", "approve_release", False),
            ("analyst", "approve_proposed_redactions", True),
            # Legal: view/comment/propose/contest only
            ("legal", "view", True),
            ("legal", "redact", False),
            ("legal", "upload", False),
            # SME: minimal
            ("sme", "view", True),
            ("sme", "redact", False),
            ("sme", "propose_redactions", False),
            # Reviewer: can reject docs
            ("reviewer", "reject_documents", True),
            ("reviewer", "approve_release", False),
            # Approver: release gatekeeper
            ("approver", "approve_release", True),
            ("approver", "contest_redactions", False),
            # Third party: limited proposer
            ("third_party", "propose_redactions", True),
            ("third_party", "redact", False),
            # Unknown role denied for any action
            ("unknown_role", "view", False),
            ("admin", "view", False),  # user-tier role, not case-team role
            ("", "view", False),
        ],
    )
    def test_role_action_matrix(self, role: str, action: str, expected: bool) -> None:
        assert permissions.can_user_perform_action(role, action) is expected

    def test_unknown_action_always_false(self) -> None:
        # Even manager can't do a made-up action.
        assert permissions.can_user_perform_action("manager", "delete_universe") is False

    def test_case_insensitive_role(self) -> None:
        assert permissions.can_user_perform_action("MANAGER", "approve_release") is True


# ---------------------------------------------------------------------------
# Convenience predicate functions — `can_<verb>` helpers
# ---------------------------------------------------------------------------


class TestCanManageTeam:
    @pytest.mark.parametrize(
        "role,expected",
        [
            ("manager", True),
            ("analyst", True),
            ("legal", False),
            ("sme", False),
            ("reviewer", False),
            ("approver", False),
            ("third_party", False),
            ("unknown", False),
            ("", False),
            ("MANAGER", True),  # case-insensitive
            ("Analyst", True),
        ],
    )
    def test_can_manage_team(self, role: str, expected: bool) -> None:
        assert permissions.can_manage_team(role) is expected


class TestCanCreateRedactions:
    @pytest.mark.parametrize(
        "role,expected",
        [
            ("manager", True),
            ("analyst", True),
            ("legal", False),
            ("sme", False),
            ("reviewer", False),
            ("approver", False),
            ("third_party", False),
            ("unknown", False),
            ("MANAGER", True),
        ],
    )
    def test_can_create_redactions(self, role: str, expected: bool) -> None:
        assert permissions.can_create_redactions(role) is expected


class TestCanProposeRedactions:
    @pytest.mark.parametrize(
        "role,expected",
        [
            ("manager", True),
            ("analyst", True),
            ("legal", True),
            ("reviewer", True),
            ("approver", True),
            ("third_party", True),
            # SME is the only case-team role that can't propose
            ("sme", False),
            ("unknown", False),
            ("", False),
            ("LEGAL", True),  # case-insensitive
        ],
    )
    def test_can_propose_redactions(self, role: str, expected: bool) -> None:
        assert permissions.can_propose_redactions(role) is expected


class TestCanApproveProposedRedactions:
    @pytest.mark.parametrize(
        "role,expected",
        [
            ("manager", True),
            ("analyst", True),
            ("legal", False),
            ("sme", False),
            ("reviewer", False),
            ("approver", False),
            ("third_party", False),
            ("unknown", False),
            ("Analyst", True),
        ],
    )
    def test_can_approve_proposed_redactions(self, role: str, expected: bool) -> None:
        assert permissions.can_approve_proposed_redactions(role) is expected


class TestCanContestRedactions:
    @pytest.mark.parametrize(
        "role,expected",
        [
            ("manager", True),
            ("analyst", True),
            ("legal", True),
            ("reviewer", True),
            ("third_party", True),
            # Approver and SME cannot contest
            ("approver", False),
            ("sme", False),
            ("unknown", False),
            ("Third_Party", True),
        ],
    )
    def test_can_contest_redactions(self, role: str, expected: bool) -> None:
        assert permissions.can_contest_redactions(role) is expected


class TestCanRejectDocuments:
    @pytest.mark.parametrize(
        "role,expected",
        [
            ("manager", True),
            ("analyst", True),
            ("reviewer", True),
            ("approver", True),
            ("legal", False),
            ("sme", False),
            ("third_party", False),
            ("unknown", False),
            ("REVIEWER", True),
        ],
    )
    def test_can_reject_documents(self, role: str, expected: bool) -> None:
        assert permissions.can_reject_documents(role) is expected


class TestCanApproveRelease:
    @pytest.mark.parametrize(
        "role,expected",
        [
            ("manager", True),
            ("approver", True),
            ("analyst", False),
            ("legal", False),
            ("sme", False),
            ("reviewer", False),
            ("third_party", False),
            ("unknown", False),
            ("Approver", True),
        ],
    )
    def test_can_approve_release(self, role: str, expected: bool) -> None:
        assert permissions.can_approve_release(role) is expected


# ---------------------------------------------------------------------------
# Case-team membership lookup
# ---------------------------------------------------------------------------


class TestIsCaseTeamMember:
    def test_empty_team_returns_false(self) -> None:
        assert permissions.is_case_team_member([], "user-1") is False

    def test_active_member_returns_true(self) -> None:
        team = [{"user_id": "user-1", "role": "manager", "status": "active"}]
        assert permissions.is_case_team_member(team, "user-1") is True

    def test_inactive_member_returns_false(self) -> None:
        # Pinned reality: a removed/inactive team member is NOT considered a
        # member. Status must be exactly "active".
        team = [{"user_id": "user-1", "role": "manager", "status": "removed"}]
        assert permissions.is_case_team_member(team, "user-1") is False

    def test_pending_status_returns_false(self) -> None:
        team = [{"user_id": "user-1", "role": "manager", "status": "pending"}]
        assert permissions.is_case_team_member(team, "user-1") is False

    def test_missing_status_field_returns_false(self) -> None:
        team = [{"user_id": "user-1", "role": "manager"}]
        assert permissions.is_case_team_member(team, "user-1") is False

    def test_user_id_not_in_team_returns_false(self) -> None:
        team = [{"user_id": "user-1", "role": "manager", "status": "active"}]
        assert permissions.is_case_team_member(team, "user-other") is False

    def test_multi_member_team_finds_match(self) -> None:
        team = [
            {"user_id": "user-1", "role": "manager", "status": "active"},
            {"user_id": "user-2", "role": "legal", "status": "active"},
            {"user_id": "user-3", "role": "sme", "status": "removed"},
        ]
        assert permissions.is_case_team_member(team, "user-2") is True
        assert permissions.is_case_team_member(team, "user-3") is False
        assert permissions.is_case_team_member(team, "user-1") is True

    def test_missing_user_id_field_treated_as_no_match(self) -> None:
        # Defensive: `.get("user_id")` returns None; None != "user-1".
        team = [{"role": "manager", "status": "active"}]
        assert permissions.is_case_team_member(team, "user-1") is False


class TestGetUserRoleOnCase:
    def test_empty_team_returns_none(self) -> None:
        assert permissions.get_user_role_on_case([], "user-1") is None

    def test_active_member_returns_role(self) -> None:
        team = [{"user_id": "user-1", "role": "legal", "status": "active"}]
        assert permissions.get_user_role_on_case(team, "user-1") == "legal"

    def test_inactive_member_returns_none(self) -> None:
        team = [{"user_id": "user-1", "role": "legal", "status": "removed"}]
        assert permissions.get_user_role_on_case(team, "user-1") is None

    def test_user_not_in_team_returns_none(self) -> None:
        team = [{"user_id": "user-1", "role": "manager", "status": "active"}]
        assert permissions.get_user_role_on_case(team, "user-other") is None

    def test_returns_first_matching_active_role(self) -> None:
        # Defensive: if a user somehow appears twice (data corruption), the
        # iteration order picks the first match.
        team = [
            {"user_id": "user-1", "role": "manager", "status": "active"},
            {"user_id": "user-1", "role": "legal", "status": "active"},
        ]
        assert permissions.get_user_role_on_case(team, "user-1") == "manager"

    def test_skips_inactive_then_finds_active(self) -> None:
        team = [
            {"user_id": "user-1", "role": "manager", "status": "removed"},
            {"user_id": "user-1", "role": "legal", "status": "active"},
        ]
        # Pinned reality: an inactive earlier record is skipped; the loop
        # continues until an active match (or end of list).
        assert permissions.get_user_role_on_case(team, "user-1") == "legal"

    def test_missing_role_field_returns_none_value(self) -> None:
        # `.get("role")` returns None on missing key, which the function
        # returns unchanged.
        team = [{"user_id": "user-1", "status": "active"}]
        assert permissions.get_user_role_on_case(team, "user-1") is None
