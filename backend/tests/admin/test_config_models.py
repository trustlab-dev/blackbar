"""Unit tests for `src.admin.config_models` Pydantic V2 models.

Phase 2.7. Target >=80% coverage on `src/admin/config_models.py`.

Reality pins:
- `SystemConfiguration` has typed defaults for every field — instantiating
  with no args succeeds and produces a fully-populated config.
- `primary_color` enforces `^#[0-9A-Fa-f]{6}$`; 3-digit hex and named colors
  are rejected.
- `default_priority` is an enum-style regex: one of `low|normal|high|urgent`.
- `default_due_days` is bounded [1, 365]; `session_timeout_minutes` [15, 480];
  `password_min_length` [8, 32].
- `SystemConfigurationUpdate` has the same constraints but all fields are
  Optional — empty payload validates cleanly.
- `PublicConfiguration` exposes only non-sensitive fields (no
  `session_timeout`/`password_min_length`/`default_due_days`).
- `EmailStr` validation: `contact_email` rejects non-email strings.
- `updated_at` is `datetime` (default_factory `datetime.utcnow`).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from src.admin.config_models import (
    PublicConfiguration,
    SystemConfiguration,
    SystemConfigurationUpdate,
)

# ---------------------------------------------------------------------------
# SystemConfiguration — defaults & happy paths
# ---------------------------------------------------------------------------


class TestSystemConfigurationDefaults:
    def test_empty_init_populates_defaults(self) -> None:
        cfg = SystemConfiguration()
        assert cfg.org_name == "Freedom of Information Office"
        assert cfg.primary_color == "#0366d6"
        assert cfg.contact_email == "foi@example.com"
        assert cfg.default_due_days == 30
        assert cfg.default_priority == "normal"
        assert cfg.session_timeout_minutes == 60
        assert cfg.password_min_length == 12
        assert cfg.enable_public_requests is True
        assert cfg.enable_request_tracking is True
        assert cfg.enable_public_upload is True
        assert cfg.auto_generate_ai_suggestions is False
        assert isinstance(cfg.request_categories, list)
        assert "General Records" in cfg.request_categories
        assert isinstance(cfg.updated_at, datetime)
        assert cfg.updated_by == "system"

    def test_explicit_values_override_defaults(self) -> None:
        cfg = SystemConfiguration(
            org_name="BC Transit FOI Office",
            primary_color="#003366",
            default_due_days=45,
            session_timeout_minutes=120,
            password_min_length=16,
            updated_by="admin-42",
        )
        assert cfg.org_name == "BC Transit FOI Office"
        assert cfg.primary_color == "#003366"
        assert cfg.default_due_days == 45
        assert cfg.session_timeout_minutes == 120
        assert cfg.password_min_length == 16
        assert cfg.updated_by == "admin-42"


# ---------------------------------------------------------------------------
# SystemConfiguration — validation failures
# ---------------------------------------------------------------------------


class TestSystemConfigurationValidation:
    @pytest.mark.parametrize(
        "color",
        [
            "#FFF",  # 3-digit hex
            "0366d6",  # missing leading #
            "red",  # named color
            "#GGGGGG",  # invalid hex chars
            "#0366D",  # only 5 chars after #
            "#0366d6FF",  # 8-char rgba
        ],
    )
    def test_invalid_primary_color_rejected(self, color: str) -> None:
        with pytest.raises(ValidationError):
            SystemConfiguration(primary_color=color)

    @pytest.mark.parametrize("color", ["#000000", "#FFFFFF", "#abcdef", "#0366D6"])
    def test_valid_primary_color_accepted(self, color: str) -> None:
        cfg = SystemConfiguration(primary_color=color)
        assert cfg.primary_color == color

    def test_invalid_contact_email_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SystemConfiguration(contact_email="not-an-email")

    def test_default_due_days_out_of_range_rejected(self) -> None:
        # ge=1, le=365
        with pytest.raises(ValidationError):
            SystemConfiguration(default_due_days=0)
        with pytest.raises(ValidationError):
            SystemConfiguration(default_due_days=366)

    def test_session_timeout_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SystemConfiguration(session_timeout_minutes=14)
        with pytest.raises(ValidationError):
            SystemConfiguration(session_timeout_minutes=481)

    def test_password_min_length_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SystemConfiguration(password_min_length=7)
        with pytest.raises(ValidationError):
            SystemConfiguration(password_min_length=33)

    def test_invalid_priority_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SystemConfiguration(default_priority="critical")

    @pytest.mark.parametrize("priority", ["low", "normal", "high", "urgent"])
    def test_valid_priorities_accepted(self, priority: str) -> None:
        cfg = SystemConfiguration(default_priority=priority)
        assert cfg.default_priority == priority

    def test_org_name_max_length_enforced(self) -> None:
        # max_length=100
        with pytest.raises(ValidationError):
            SystemConfiguration(org_name="A" * 101)

    def test_footer_text_max_length_enforced(self) -> None:
        # max_length=500
        with pytest.raises(ValidationError):
            SystemConfiguration(footer_text="x" * 501)


# ---------------------------------------------------------------------------
# SystemConfigurationUpdate
# ---------------------------------------------------------------------------


class TestSystemConfigurationUpdate:
    def test_empty_update_is_valid(self) -> None:
        """All fields Optional — empty payload validates cleanly."""
        upd = SystemConfigurationUpdate()
        # All fields default to None
        assert upd.org_name is None
        assert upd.default_due_days is None
        assert upd.primary_color is None

    def test_partial_update_only_sets_provided_fields(self) -> None:
        upd = SystemConfigurationUpdate(org_name="New Org", default_due_days=45)
        # Provided fields are set
        assert upd.org_name == "New Org"
        assert upd.default_due_days == 45
        # Others remain None
        assert upd.primary_color is None
        assert upd.session_timeout_minutes is None

    def test_update_validates_same_constraints_as_full_model(self) -> None:
        # invalid primary_color still rejected on update
        with pytest.raises(ValidationError):
            SystemConfigurationUpdate(primary_color="not-a-hex")
        # invalid due_days still rejected
        with pytest.raises(ValidationError):
            SystemConfigurationUpdate(default_due_days=400)
        # invalid email still rejected
        with pytest.raises(ValidationError):
            SystemConfigurationUpdate(contact_email="bad-email")

    def test_update_dict_excludes_none_when_filtered(self) -> None:
        """Mirrors `update_configuration` route which strips None before
        upserting to Mongo."""
        upd = SystemConfigurationUpdate(org_name="Acme", default_due_days=14)
        non_none = {k: v for k, v in upd.dict().items() if v is not None}
        assert non_none == {"org_name": "Acme", "default_due_days": 14}


# ---------------------------------------------------------------------------
# PublicConfiguration
# ---------------------------------------------------------------------------


class TestPublicConfiguration:
    def test_minimal_public_config(self) -> None:
        cfg = PublicConfiguration(
            org_name="Example FOI",
            org_logo_url=None,
            primary_color="#000000",
            contact_email="contact@example.com",
            footer_text=None,
            enable_public_requests=True,
            enable_request_tracking=False,
            enable_public_upload=True,
            request_categories=["General Records"],
        )
        assert cfg.org_name == "Example FOI"
        assert cfg.org_logo_url is None
        assert cfg.footer_text is None
        assert cfg.enable_request_tracking is False

    def test_public_config_omits_sensitive_fields(self) -> None:
        """Reality pin: PublicConfiguration does NOT include
        session_timeout, password_min_length, default_due_days, or any
        admin-only fields. Anonymous portal users get only org branding +
        public-facing toggles."""
        cfg = PublicConfiguration(
            org_name="Example",
            org_logo_url=None,
            primary_color="#000000",
            contact_email="c@example.com",
            footer_text=None,
            enable_public_requests=True,
            enable_request_tracking=True,
            enable_public_upload=True,
            request_categories=[],
        )
        dumped = cfg.model_dump()
        # Sensitive admin keys MUST NOT appear in the public payload
        assert "session_timeout_minutes" not in dumped
        assert "password_min_length" not in dumped
        assert "default_due_days" not in dumped
        assert "default_assignee_id" not in dumped
        assert "auto_generate_ai_suggestions" not in dumped
        assert "updated_by" not in dumped

    def test_public_config_missing_required_field_rejected(self) -> None:
        """Unlike SystemConfiguration, PublicConfiguration has no
        defaults — required fields must be provided."""
        with pytest.raises(ValidationError):
            PublicConfiguration()  # type: ignore[call-arg]
