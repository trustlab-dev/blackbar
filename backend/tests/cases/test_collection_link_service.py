"""Tests for `src.cases.collection_link_service` -- secure-token generation
and validation for the document-collection-link feature.

This module is a pure-function helper layer (no I/O); the corresponding
routes in `src/cases/collection_link_routes.py` are exercised in Batch
2.2.C. The audit's coverage bar here is >=80%; reserved 100% for the
critical-path modules (permissions, release_package_service).

Phase 1.5.3 renamed the source from `collection_links.py` to
`collection_link_service.py`. There was no pre-existing test file for
this module, so no absorb step.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.cases.collection_link_service import (
    CollectionLinkCreate,
    CollectionLinkDB,
    DocumentSubmission,
    generate_collection_token,
    is_link_valid,
)

# ---------------------------------------------------------------------------
# generate_collection_token
# ---------------------------------------------------------------------------


class TestGenerateCollectionToken:
    def test_default_length_is_32(self) -> None:
        token = generate_collection_token()
        assert len(token) == 32

    def test_respects_custom_length(self) -> None:
        token = generate_collection_token(length=16)
        assert len(token) == 16

    def test_uses_alphanumeric_alphabet(self) -> None:
        token = generate_collection_token(length=128)
        # secrets.choice over string.ascii_letters + digits -> no symbols,
        # no whitespace. Pin that contract.
        assert all(c.isalnum() and c.isascii() for c in token)

    def test_tokens_are_unique(self) -> None:
        # secrets.choice is cryptographically random; collisions across
        # 100 32-char draws are astronomically unlikely. This guards
        # against accidental replacement with a deterministic generator.
        tokens = {generate_collection_token() for _ in range(100)}
        assert len(tokens) == 100


# ---------------------------------------------------------------------------
# is_link_valid
# ---------------------------------------------------------------------------


class TestIsLinkValid:
    def test_active_unexpired_link_is_valid(self) -> None:
        link = {
            "is_active": True,
            "expires_at": datetime.utcnow() + timedelta(days=7),
            "max_uploads": 10,
            "upload_count": 0,
        }
        ok, msg = is_link_valid(link)
        assert ok is True
        assert msg == ""

    def test_inactive_link_is_invalid(self) -> None:
        link = {
            "is_active": False,
            "expires_at": datetime.utcnow() + timedelta(days=7),
        }
        ok, msg = is_link_valid(link)
        assert ok is False
        assert "deactivated" in msg

    def test_expired_link_is_invalid(self) -> None:
        link = {
            "is_active": True,
            "expires_at": datetime.utcnow() - timedelta(days=1),
        }
        ok, msg = is_link_valid(link)
        assert ok is False
        assert "expired" in msg

    def test_expiration_as_naive_iso_string_is_parsed(self) -> None:
        # Naive ISO strings (no trailing Z / offset) round-trip cleanly
        # because `datetime.fromisoformat(s.replace('Z', '+00:00'))` is a
        # no-op when there's no Z, leaving the result naive -- comparable
        # with `datetime.utcnow()`.
        future_iso = (datetime.utcnow() + timedelta(days=7)).isoformat()
        link = {
            "is_active": True,
            "expires_at": future_iso,
        }
        ok, msg = is_link_valid(link)
        assert ok is True
        assert msg == ""

    def test_expiration_as_iso_string_with_z_compares_cleanly(self) -> None:
        """Regression for audit Section 11 B11 (fixed 2026-05-12).

        ``is_link_valid`` used to compare a tz-aware parsed expires_at
        against the naive ``datetime.utcnow()``, crashing with TypeError
        on JSON-deserialized ``...Z``-suffixed values. Source now uses
        ``datetime.now(timezone.utc)`` so both sides are tz-aware.
        """
        future_iso_z = (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z"
        link = {
            "is_active": True,
            "expires_at": future_iso_z,
        }
        ok, msg = is_link_valid(link)
        assert ok is True
        assert msg == ""

    def test_expiration_as_iso_string_with_z_in_past_is_invalid(self) -> None:
        """A past Z-suffixed ISO expiration reports invalid (not TypeError)."""
        past_iso_z = (datetime.utcnow() - timedelta(days=1)).isoformat() + "Z"
        link = {
            "is_active": True,
            "expires_at": past_iso_z,
        }
        ok, msg = is_link_valid(link)
        assert ok is False
        assert "expired" in msg

    def test_no_expiration_is_treated_as_unlimited(self) -> None:
        link = {
            "is_active": True,
            "expires_at": None,
        }
        ok, _ = is_link_valid(link)
        assert ok is True

    def test_upload_limit_reached_is_invalid(self) -> None:
        link = {
            "is_active": True,
            "expires_at": None,
            "max_uploads": 5,
            "upload_count": 5,
        }
        ok, msg = is_link_valid(link)
        assert ok is False
        assert "upload limit" in msg

    def test_upload_count_below_limit_is_valid(self) -> None:
        link = {
            "is_active": True,
            "expires_at": None,
            "max_uploads": 5,
            "upload_count": 4,
        }
        ok, _ = is_link_valid(link)
        assert ok is True

    def test_no_max_uploads_is_treated_as_unlimited(self) -> None:
        link = {
            "is_active": True,
            "expires_at": None,
            "max_uploads": None,
            "upload_count": 9999,
        }
        ok, _ = is_link_valid(link)
        assert ok is True

    def test_missing_is_active_treated_as_falsy(self) -> None:
        # Pin reality: `link.get("is_active")` returns None when missing,
        # which is falsy -> the link is considered deactivated. This
        # protects against partially-constructed records leaking through.
        link = {"expires_at": None}
        ok, msg = is_link_valid(link)
        assert ok is False
        assert "deactivated" in msg


# ---------------------------------------------------------------------------
# Pydantic models -- ensure shape contract is enforced
# ---------------------------------------------------------------------------


class TestCollectionLinkCreate:
    def test_minimal_payload(self) -> None:
        model = CollectionLinkCreate(case_id="case-123")
        assert model.case_id == "case-123"
        assert model.expires_at is None
        assert model.max_uploads is None
        assert model.notes is None

    def test_full_payload(self) -> None:
        expires = datetime(2026, 1, 1, tzinfo=UTC)
        model = CollectionLinkCreate(
            case_id="case-123",
            expires_at=expires,
            max_uploads=10,
            notes="testing",
        )
        assert model.expires_at == expires
        assert model.max_uploads == 10
        assert model.notes == "testing"


class TestCollectionLinkDB:
    def test_required_fields(self) -> None:
        now = datetime.utcnow()
        model = CollectionLinkDB(
            id="link-1",
            case_id="case-123",
            token=generate_collection_token(),
            created_by="user-1",
            created_at=now,
        )
        # Defaults: is_active True, upload_count 0
        assert model.is_active is True
        assert model.upload_count == 0
        assert model.expires_at is None
        assert model.max_uploads is None


class TestDocumentSubmission:
    def test_valid_submission(self) -> None:
        sub = DocumentSubmission(
            submitter_name="Alice",
            submitter_email="alice@example.com",
            notes="batch of records",
        )
        assert sub.submitter_email == "alice@example.com"

    def test_invalid_email_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            DocumentSubmission(
                submitter_name="Alice",
                submitter_email="not-an-email",
            )
