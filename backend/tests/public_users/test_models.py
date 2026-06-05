"""Unit tests for `src.public_users.models` Pydantic models (RFC-007).

Phase 2.8 Batch C. Target >=80% line coverage on
`src/public_users/models.py`.

Surface covered:
- `PublicUserStatus` enum (active, suspended).
- `PublicUserBase` email normalization via legacy `@validator` (lowercase
  + strip whitespace). Uses Pydantic V1-compat `@validator` not V2's
  `@field_validator`; `EmailStr` does the format check first, then the
  custom normalizer runs.
- `PublicUserCreate` is a pass-through subclass (no extra fields).
- `PublicUserUpdate` has all-optional fields (no email).
- `PublicUser` full model: id required, email_verified=True default,
  status=ACTIVE default, request_ids=[] default.
- `MagicLinkToken` model: required id/email/token_hash/expires_at;
  used=False default; created_at default_factory utcnow; same email
  normalizer.

Reality pins:
- Email normalizer strips whitespace AND lowercases — happens after
  EmailStr validation, so " Alice@Example.COM " becomes "alice@example.com".
- `email_verified=True` default reflects RFC-007 magic-link verification.
- The normalizer's `if v else v` short-circuit returns the raw value
  unchanged when v is falsy (None or empty string).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from src.public_users.models import (
    MagicLinkToken,
    PublicUser,
    PublicUserBase,
    PublicUserCreate,
    PublicUserStatus,
    PublicUserUpdate,
)

# ---------------------------------------------------------------------------
# PublicUserStatus
# ---------------------------------------------------------------------------


class TestPublicUserStatus:
    def test_enum_values(self) -> None:
        assert PublicUserStatus.ACTIVE.value == "active"
        assert PublicUserStatus.SUSPENDED.value == "suspended"

    def test_str_enum_comparison(self) -> None:
        assert PublicUserStatus.ACTIVE == "active"


# ---------------------------------------------------------------------------
# PublicUserBase email normalization
# ---------------------------------------------------------------------------


class TestPublicUserBaseEmail:
    def test_lowercases_and_strips(self) -> None:
        b = PublicUserBase(email=" Alice@Example.COM ")
        assert b.email == "alice@example.com"

    def test_rejects_non_email(self) -> None:
        with pytest.raises(ValidationError):
            PublicUserBase(email="not-an-email")

    def test_name_optional(self) -> None:
        b = PublicUserBase(email="a@example.com")
        assert b.name is None

    def test_name_explicit(self) -> None:
        b = PublicUserBase(email="a@example.com", name="Alice")
        assert b.name == "Alice"


# ---------------------------------------------------------------------------
# PublicUserCreate
# ---------------------------------------------------------------------------


class TestPublicUserCreate:
    def test_inherits_email_normalization(self) -> None:
        c = PublicUserCreate(email="ALICE@EXAMPLE.COM")
        assert c.email == "alice@example.com"

    def test_email_required(self) -> None:
        with pytest.raises(ValidationError):
            PublicUserCreate(name="Alice")


# ---------------------------------------------------------------------------
# PublicUserUpdate
# ---------------------------------------------------------------------------


class TestPublicUserUpdate:
    def test_empty_payload_valid(self) -> None:
        u = PublicUserUpdate()
        assert u.name is None
        assert u.status is None

    def test_status_only(self) -> None:
        u = PublicUserUpdate(status=PublicUserStatus.SUSPENDED)
        assert u.status == PublicUserStatus.SUSPENDED
        assert u.name is None

    def test_dump_drops_none_when_excluded(self) -> None:
        u = PublicUserUpdate(name="X")
        d = u.model_dump(exclude_unset=True)
        assert d == {"name": "X"}


# ---------------------------------------------------------------------------
# PublicUser
# ---------------------------------------------------------------------------


class TestPublicUserModel:
    def _kwargs(self, **overrides) -> dict:
        base = {
            "id": "u-1",
            "email": "a@example.com",
            "created_at": datetime(2026, 1, 1),
            "updated_at": datetime(2026, 1, 2),
        }
        base.update(overrides)
        return base

    def test_minimal_instance(self) -> None:
        u = PublicUser(**self._kwargs())
        assert u.id == "u-1"
        assert u.email_verified is True  # default
        assert u.status == PublicUserStatus.ACTIVE  # default
        assert u.request_ids == []  # default factory
        assert u.last_login_at is None

    def test_request_ids_explicit(self) -> None:
        u = PublicUser(**self._kwargs(request_ids=["case-1", "case-2"]))
        assert u.request_ids == ["case-1", "case-2"]

    def test_status_suspended(self) -> None:
        u = PublicUser(**self._kwargs(status=PublicUserStatus.SUSPENDED))
        assert u.status == PublicUserStatus.SUSPENDED

    def test_id_required(self) -> None:
        with pytest.raises(ValidationError):
            PublicUser(
                email="a@example.com",
                created_at=datetime(2026, 1, 1),
                updated_at=datetime(2026, 1, 2),
            )

    def test_from_attributes_config(self) -> None:
        class Stub:
            id = "u-1"
            email = "a@example.com"
            name = None
            email_verified = True
            status = PublicUserStatus.ACTIVE
            created_at = datetime(2026, 1, 1)
            updated_at = datetime(2026, 1, 2)
            last_login_at = None
            request_ids: list[str] = []

        u = PublicUser.model_validate(Stub())
        assert u.id == "u-1"


# ---------------------------------------------------------------------------
# MagicLinkToken
# ---------------------------------------------------------------------------


class TestMagicLinkToken:
    def _kwargs(self, **overrides) -> dict:
        base = {
            "id": "t-1",
            "email": "a@example.com",
            "token_hash": "h",
            "expires_at": datetime.utcnow() + timedelta(minutes=15),
        }
        base.update(overrides)
        return base

    def test_minimal_instance(self) -> None:
        t = MagicLinkToken(**self._kwargs())
        assert t.id == "t-1"
        assert t.used is False  # default
        assert t.ip_address is None
        assert t.user_agent is None
        assert isinstance(t.created_at, datetime)  # default_factory

    def test_email_normalized(self) -> None:
        t = MagicLinkToken(**self._kwargs(email=" Alice@Example.COM "))
        assert t.email == "alice@example.com"

    @pytest.mark.parametrize("missing", ["id", "email", "token_hash", "expires_at"])
    def test_required_fields(self, missing: str) -> None:
        kwargs = self._kwargs()
        kwargs.pop(missing)
        with pytest.raises(ValidationError) as exc:
            MagicLinkToken(**kwargs)
        assert missing in str(exc.value)

    def test_used_explicit_true(self) -> None:
        t = MagicLinkToken(**self._kwargs(used=True))
        assert t.used is True

    def test_ip_and_user_agent(self) -> None:
        t = MagicLinkToken(**self._kwargs(ip_address="1.2.3.4", user_agent="Mozilla/5.0"))
        assert t.ip_address == "1.2.3.4"
        assert t.user_agent == "Mozilla/5.0"

    def test_from_attributes_config(self) -> None:
        class Stub:
            id = "t-1"
            email = "a@example.com"
            token_hash = "h"
            expires_at = datetime.utcnow() + timedelta(minutes=15)
            used = False
            created_at = datetime.utcnow()
            ip_address = None
            user_agent = None

        t = MagicLinkToken.model_validate(Stub())
        assert t.id == "t-1"
