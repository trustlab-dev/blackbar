"""Unit tests for `src.users.models` Pydantic models.

Phase 2.8 Batch C. Target >=80% line coverage on `src/users/models.py`.

Surface covered:
- `UserStatus` enum values (active, disabled, pending_activation).
- `UserBase` email validator: lowercase normalization + custom regex
  that allows both standard TLDs and `.local` development domains.
- `UserCreate` adds `password` (required).
- `UserUpdate` validator: identical email regex but None passes through
  for optional updates.
- `User` model: full server-side shape with role default "user",
  optional external_id / activation_token fields.
- `UserPublic`: id/email/name/status only.

Reality pins:
- `UserBase.validate_email` rejects strings without `@`, but ALSO rejects
  email-shaped strings whose TLD is shorter than 2 chars and is not
  `.local`.
- `User.role` is plain `str` with default `"user"` — no Literal/Enum guard.
- `User.id` is required.
- `UserStatus` is a `str` enum — comparison with raw strings works.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from src.users.models import (
    User,
    UserCreate,
    UserPublic,
    UserStatus,
    UserUpdate,
)

# ---------------------------------------------------------------------------
# UserStatus enum
# ---------------------------------------------------------------------------


class TestUserStatus:
    def test_enum_values(self) -> None:
        assert UserStatus.ACTIVE.value == "active"
        assert UserStatus.DISABLED.value == "disabled"
        assert UserStatus.PENDING_ACTIVATION.value == "pending_activation"

    def test_str_enum_comparison(self) -> None:
        assert UserStatus.ACTIVE == "active"


# ---------------------------------------------------------------------------
# UserCreate email validation
# ---------------------------------------------------------------------------


class TestUserCreateEmail:
    def test_normalizes_lowercase(self) -> None:
        u = UserCreate(email="Alice@Example.COM", name="A", password="p")
        assert u.email == "alice@example.com"

    def test_allows_local_domain(self) -> None:
        u = UserCreate(email="dev@host.local", name="A", password="p")
        assert u.email == "dev@host.local"

    def test_allows_plus_addressing(self) -> None:
        u = UserCreate(email="alice+tag@example.com", name="A", password="p")
        assert u.email == "alice+tag@example.com"

    def test_rejects_no_at_sign(self) -> None:
        with pytest.raises(ValidationError) as exc:
            UserCreate(email="notanemail", name="A", password="p")
        assert "Invalid email format" in str(exc.value)

    def test_rejects_no_domain(self) -> None:
        with pytest.raises(ValidationError) as exc:
            UserCreate(email="alice@", name="A", password="p")
        assert "Invalid email format" in str(exc.value)

    def test_rejects_short_tld(self) -> None:
        with pytest.raises(ValidationError):
            UserCreate(email="alice@x.a", name="A", password="p")

    def test_password_required(self) -> None:
        with pytest.raises(ValidationError):
            UserCreate(email="a@example.com", name="A")

    def test_name_required(self) -> None:
        with pytest.raises(ValidationError):
            UserCreate(email="a@example.com", password="p")

    def test_default_status_active(self) -> None:
        u = UserCreate(email="a@example.com", name="A", password="p")
        assert u.status == UserStatus.ACTIVE


# ---------------------------------------------------------------------------
# UserUpdate email validation
# ---------------------------------------------------------------------------


class TestUserUpdateEmail:
    def test_none_email_passes_through(self) -> None:
        u = UserUpdate()
        assert u.email is None

    def test_explicit_none_email_short_circuits_validator(self) -> None:
        """`field_validator` runs even when caller passes email=None
        explicitly; the early `if v is None: return v` branch is the
        target."""
        u = UserUpdate(email=None)
        assert u.email is None

    def test_explicit_email_normalized(self) -> None:
        u = UserUpdate(email="Bob@Example.COM")
        assert u.email == "bob@example.com"

    def test_invalid_email_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc:
            UserUpdate(email="nope")
        assert "Invalid email format" in str(exc.value)

    def test_partial_update_with_status_only(self) -> None:
        u = UserUpdate(status=UserStatus.DISABLED)
        assert u.status == UserStatus.DISABLED
        assert u.name is None
        assert u.email is None
        assert u.password is None

    def test_all_fields_optional(self) -> None:
        """Empty payload validates cleanly."""
        u = UserUpdate()
        assert u.model_dump(exclude_unset=True) == {}


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------


class TestUserModel:
    def _kwargs(self, **overrides) -> dict:
        base = {
            "id": "u-1",
            "email": "a@example.com",
            "name": "Alice",
        }
        base.update(overrides)
        return base

    def test_minimal_instance(self) -> None:
        u = User(**self._kwargs())
        assert u.id == "u-1"
        assert u.role == "user"  # default
        assert u.password_hash is None
        assert u.external_id is None
        assert u.activation_token is None
        assert u.activation_token_expires_at is None
        assert u.created_at is None
        assert u.updated_at is None
        assert u.status == UserStatus.ACTIVE  # default from UserBase

    def test_role_override(self) -> None:
        u = User(**self._kwargs(role="admin"))
        assert u.role == "admin"

    def test_id_required(self) -> None:
        with pytest.raises(ValidationError):
            User(email="a@example.com", name="A")

    def test_full_instance(self) -> None:
        u = User(
            **self._kwargs(
                password_hash="h",
                external_id="ext",
                role="analyst",
                activation_token="tok",
                activation_token_expires_at=datetime(2026, 1, 1),
                created_at=datetime(2026, 1, 1),
                updated_at=datetime(2026, 1, 2),
            )
        )
        assert u.password_hash == "h"
        assert u.external_id == "ext"
        assert u.role == "analyst"
        assert u.activation_token == "tok"

    def test_email_validator_applies(self) -> None:
        u = User(**self._kwargs(email="Alice@Example.COM"))
        assert u.email == "alice@example.com"

    def test_email_validator_rejects(self) -> None:
        with pytest.raises(ValidationError):
            User(**self._kwargs(email="bad"))

    def test_from_attributes_config(self) -> None:
        class Stub:
            id = "u-1"
            email = "a@example.com"
            name = "Alice"
            status = UserStatus.ACTIVE
            password_hash = None
            external_id = None
            role = "user"
            activation_token = None
            activation_token_expires_at = None
            created_at = None
            updated_at = None

        u = User.model_validate(Stub())
        assert u.id == "u-1"


# ---------------------------------------------------------------------------
# UserPublic
# ---------------------------------------------------------------------------


class TestUserPublic:
    def test_minimal_instance(self) -> None:
        u = UserPublic(
            id="u-1",
            email="a@example.com",
            name="Alice",
            status=UserStatus.ACTIVE,
        )
        assert u.id == "u-1"
        assert u.status == UserStatus.ACTIVE

    @pytest.mark.parametrize("missing", ["id", "email", "name", "status"])
    def test_required_fields(self, missing: str) -> None:
        kwargs = {
            "id": "u-1",
            "email": "a@example.com",
            "name": "Alice",
            "status": UserStatus.ACTIVE,
        }
        kwargs.pop(missing)
        with pytest.raises(ValidationError) as exc:
            UserPublic(**kwargs)
        assert missing in str(exc.value)

    def test_no_password_hash_field(self) -> None:
        """UserPublic deliberately omits credential fields."""
        u = UserPublic(
            id="u-1",
            email="a@example.com",
            name="Alice",
            status=UserStatus.ACTIVE,
        )
        assert not hasattr(u, "password_hash")
        assert not hasattr(u, "activation_token")
