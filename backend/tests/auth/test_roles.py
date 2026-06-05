"""Unit tests for src.auth.roles.

Pure-unit tests (no I/O). Pin the canonical 4-tier role hierarchy
(admin > analyst > user > guest) and the permission helpers used across
the auth stack. Phase 2.1.A per
docs/superpowers/plans/2026-05-11-phase-2-1-auth-tests.md.

NOTE: An earlier plan draft mentioned an `owner` role. The current source
defines only admin/analyst/user/guest — these tests pin that 4-tier
shape; if `owner` ever returns, add it here.
"""

from __future__ import annotations

import pytest

from src.auth.roles import (
    AVAILABLE_ROLES,
    ROLE_HIERARCHY,
    get_available_roles,
    get_role_ids,
    get_role_level,
    has_permission,
    is_valid_role,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# get_available_roles / get_role_ids
# ---------------------------------------------------------------------------


def test_get_available_roles_returns_expected_list() -> None:
    roles = get_available_roles()
    # Same object reference is fine — pin the canonical 4-tier shape.
    assert roles is AVAILABLE_ROLES
    assert isinstance(roles, list)
    assert len(roles) == 4

    # Each entry has id/name/description.
    for r in roles:
        assert set(r.keys()) == {"id", "name", "description"}
        assert isinstance(r["id"], str)
        assert isinstance(r["name"], str)
        assert isinstance(r["description"], str)


def test_get_role_ids_returns_ordered_ids() -> None:
    """Order matches AVAILABLE_ROLES (admin, analyst, user, guest)."""
    assert get_role_ids() == ["admin", "analyst", "user", "guest"]


# ---------------------------------------------------------------------------
# is_valid_role
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["admin", "analyst", "user", "guest"])
def test_is_valid_role_for_each_canonical_role(role: str) -> None:
    assert is_valid_role(role) is True


@pytest.mark.parametrize(
    "role",
    [
        "owner",  # not in current 4-tier model
        "superadmin",
        "ADMIN",  # case-sensitive
        "Admin",  # case-sensitive
        "admin ",  # trailing whitespace not trimmed
        " admin",  # leading whitespace not trimmed
        "unknown",
    ],
)
def test_is_valid_role_rejects_unknown(role: str) -> None:
    """Pins reality: is_valid_role is case-sensitive and does NOT strip
    whitespace. If we ever want case-insensitive / trimmed matching we'll
    update both source and tests together."""
    assert is_valid_role(role) is False


def test_is_valid_role_rejects_empty_and_none() -> None:
    assert is_valid_role("") is False
    # `None in [...]` evaluates to False without raising, which is what the
    # production callers rely on.
    assert is_valid_role(None) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# get_role_level
# ---------------------------------------------------------------------------


def test_get_role_level_hierarchy_order() -> None:
    """admin > analyst > user > guest, with exact numeric levels pinned."""
    assert get_role_level("admin") == 4
    assert get_role_level("analyst") == 3
    assert get_role_level("user") == 2
    assert get_role_level("guest") == 1

    # Strictly decreasing.
    levels = [get_role_level(r) for r in ["admin", "analyst", "user", "guest"]]
    assert levels == sorted(levels, reverse=True)
    assert ROLE_HIERARCHY == {"admin": 4, "analyst": 3, "user": 2, "guest": 1}


@pytest.mark.parametrize("role", ["owner", "unknown", "", "ADMIN"])
def test_get_role_level_unknown_role_returns_default(role: str) -> None:
    """Unknown roles fall through to the .get() default (0). Documented
    behavior — relied upon by has_permission below."""
    assert get_role_level(role) == 0


# ---------------------------------------------------------------------------
# has_permission
# ---------------------------------------------------------------------------


def test_has_permission_admin_can_act_as_analyst() -> None:
    assert has_permission("admin", "analyst") is True
    assert has_permission("admin", "user") is True
    assert has_permission("admin", "guest") is True


def test_has_permission_user_cannot_act_as_admin() -> None:
    assert has_permission("user", "admin") is False
    assert has_permission("user", "analyst") is False
    assert has_permission("guest", "user") is False


@pytest.mark.parametrize("role", ["admin", "analyst", "user", "guest"])
def test_has_permission_same_role_passes(role: str) -> None:
    """A role always satisfies its own requirement (>= is reflexive)."""
    assert has_permission(role, role) is True


def test_has_permission_unknown_role_denied() -> None:
    """Unknown user_role gets level 0, so it cannot satisfy any real
    required_role. Pins the safe-default behavior."""
    assert has_permission("nope", "guest") is False
    # But two unknown roles both at level 0 -> True (0 >= 0). Documented.
    assert has_permission("nope", "alsonope") is True
