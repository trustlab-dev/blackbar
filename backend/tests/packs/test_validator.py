"""Unit tests for `src.packs.validator` (jurisdiction pack schema validation).

Phase 2.8 Batch A. Target >=80% line coverage on `src/packs/validator.py`.

Surface covered:
- `PackValidator.validate(pack_data)` returns `(is_valid, errors, warnings)`.
- Early-return: missing any of the 8 REQUIRED_FIELDS short-circuits with
  errors-only (warnings stay empty).
- After top-level fields are present, validator inspects jurisdiction
  sub-fields, redaction_categories list, statuses list, timelines shape,
  optional terminology / templates / ai_prompts, and version format.
- `PackValidator.validate_category(category)` validates a standalone
  category dict (used for incremental edits in the admin UI).
- `PackValidator.validate_status(status)` validates a standalone status.
- Module convenience `validate_pack(data)` wraps the class and adds
  `pack_id` + `pack_name` to the result dict.

Reality pins:
- Missing required fields prevent any further checks (errors-only fast path).
- Empty redaction_categories list is a hard error: "must have at least one".
- Empty statuses list is a hard error.
- `timelines.default_response_days` must be present AND numeric (int or
  float). A string value triggers the "must be a number" error.
- Category color must start with `#` to avoid a warning (no hard error on
  bad format inside the full-validate path).
- `validate_category` is stricter on color: it requires `#` prefix AND
  length in {4, 7} (#RGB or #RRGGBB). Length-8 or length-3 fail.
- Version must contain a `.` (semver heuristic) to avoid a warning.
- Recommended terminology fields (`request_type`, `requester`, `case`)
  emit warnings when missing — never errors.
- Missing templates / ai_prompts produce warnings, not errors.
"""

from __future__ import annotations

import pytest

from src.packs.validator import (
    PackValidator,
    validate_pack,
)


def _full_pack(**overrides) -> dict:
    """A fully-valid pack, suitable for negative-mutation tests."""
    base = {
        "pack_id": "test-v1",
        "name": "Test Pack",
        "version": "1.0.0",
        "jurisdiction": {
            "country": "CA",
            "region": "BC",
            "legislation": "FIPPA",
        },
        "terminology": {
            "request_type": "FOI Request",
            "requester": "Applicant",
            "case": "File",
        },
        "timelines": {"default_response_days": 30},
        "statuses": [
            {"value": "open", "label": "Open", "color": "#00ff00"},
        ],
        "redaction_categories": [
            {
                "id": "s22",
                "code": "S.22",
                "name": "Personal privacy",
                "description": "x",
                "color": "#0066cc",
            }
        ],
        "templates": {"ack": "Hello"},
        "ai_prompts": {"summarize": "Sum"},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# PackValidator.validate — happy path
# ---------------------------------------------------------------------------


class TestValidateHappyPath:
    def test_full_valid_pack_passes(self) -> None:
        is_valid, errors, warnings = PackValidator.validate(_full_pack())
        assert is_valid is True
        assert errors == []
        assert warnings == []


# ---------------------------------------------------------------------------
# PackValidator.validate — missing top-level fields short-circuit
# ---------------------------------------------------------------------------


class TestMissingTopLevelFields:
    @pytest.mark.parametrize(
        "missing_field",
        [
            "pack_id",
            "name",
            "version",
            "jurisdiction",
            "terminology",
            "timelines",
            "statuses",
            "redaction_categories",
        ],
    )
    def test_missing_required_field_short_circuits(self, missing_field: str) -> None:
        pack = _full_pack()
        pack.pop(missing_field)
        is_valid, errors, warnings = PackValidator.validate(pack)
        assert is_valid is False
        assert any(missing_field in e for e in errors)
        # Short-circuit: no further errors / no warnings collected
        assert warnings == []

    def test_empty_dict_lists_all_required_fields(self) -> None:
        is_valid, errors, _ = PackValidator.validate({})
        assert is_valid is False
        # All 8 required fields show up as missing
        assert len(errors) == 8


# ---------------------------------------------------------------------------
# PackValidator.validate — jurisdiction sub-fields
# ---------------------------------------------------------------------------


class TestJurisdictionFields:
    @pytest.mark.parametrize("field", ["country", "region", "legislation"])
    def test_missing_jurisdiction_field_errors(self, field: str) -> None:
        pack = _full_pack()
        pack["jurisdiction"].pop(field)
        is_valid, errors, _ = PackValidator.validate(pack)
        assert is_valid is False
        assert any(field in e for e in errors)

    def test_empty_jurisdiction_dict_lists_all(self) -> None:
        pack = _full_pack(jurisdiction={})
        is_valid, errors, _ = PackValidator.validate(pack)
        assert is_valid is False
        assert sum("jurisdiction field" in e for e in errors) == 3


# ---------------------------------------------------------------------------
# PackValidator.validate — redaction_categories
# ---------------------------------------------------------------------------


class TestRedactionCategories:
    def test_empty_categories_list_errors(self) -> None:
        pack = _full_pack(redaction_categories=[])
        is_valid, errors, _ = PackValidator.validate(pack)
        assert is_valid is False
        assert any("at least one redaction category" in e for e in errors)

    def test_category_missing_required_field(self) -> None:
        pack = _full_pack()
        pack["redaction_categories"][0].pop("name")
        is_valid, errors, _ = PackValidator.validate(pack)
        assert is_valid is False
        assert any("Category 0" in e and "name" in e for e in errors)

    def test_category_color_without_hash_warns(self) -> None:
        pack = _full_pack()
        pack["redaction_categories"][0]["color"] = "blue"
        is_valid, _errors, warnings = PackValidator.validate(pack)
        # Color isn't a hard error in the full-validate path — just a warning
        assert any("hex format" in w for w in warnings)


# ---------------------------------------------------------------------------
# PackValidator.validate — statuses
# ---------------------------------------------------------------------------


class TestStatuses:
    def test_empty_statuses_errors(self) -> None:
        pack = _full_pack(statuses=[])
        is_valid, errors, _ = PackValidator.validate(pack)
        assert is_valid is False
        assert any("at least one status" in e for e in errors)

    def test_status_missing_required_field(self) -> None:
        pack = _full_pack()
        pack["statuses"][0].pop("color")
        is_valid, errors, _ = PackValidator.validate(pack)
        assert is_valid is False
        assert any("Status 0" in e and "color" in e for e in errors)


# ---------------------------------------------------------------------------
# PackValidator.validate — timelines
# ---------------------------------------------------------------------------


class TestTimelines:
    def test_missing_default_response_days(self) -> None:
        pack = _full_pack(timelines={"other_field": 5})
        is_valid, errors, _ = PackValidator.validate(pack)
        assert is_valid is False
        assert any("default_response_days" in e for e in errors)

    def test_string_default_response_days_rejected(self) -> None:
        pack = _full_pack(timelines={"default_response_days": "thirty"})
        is_valid, errors, _ = PackValidator.validate(pack)
        assert is_valid is False
        assert any("must be a number" in e for e in errors)

    def test_int_default_response_days_accepted(self) -> None:
        pack = _full_pack(timelines={"default_response_days": 45})
        is_valid, _, _ = PackValidator.validate(pack)
        assert is_valid is True

    def test_float_default_response_days_accepted(self) -> None:
        pack = _full_pack(timelines={"default_response_days": 30.5})
        is_valid, _, _ = PackValidator.validate(pack)
        assert is_valid is True


# ---------------------------------------------------------------------------
# PackValidator.validate — terminology warnings
# ---------------------------------------------------------------------------


class TestTerminology:
    def test_missing_recommended_terminology_warns(self) -> None:
        pack = _full_pack(terminology={})
        is_valid, errors, warnings = PackValidator.validate(pack)
        assert is_valid is True
        # 3 recommended fields missing => 3 warnings
        terminology_warnings = [w for w in warnings if "terminology" in w]
        assert len(terminology_warnings) == 3


# ---------------------------------------------------------------------------
# PackValidator.validate — templates / ai_prompts / version
# ---------------------------------------------------------------------------


class TestOptionalSections:
    def test_no_templates_warns(self) -> None:
        pack = _full_pack(templates={})
        is_valid, _, warnings = PackValidator.validate(pack)
        assert is_valid is True
        assert any("No templates" in w for w in warnings)

    def test_no_ai_prompts_warns(self) -> None:
        pack = _full_pack(ai_prompts={})
        is_valid, _, warnings = PackValidator.validate(pack)
        assert is_valid is True
        assert any("AI prompts" in w for w in warnings)

    def test_version_without_dot_warns(self) -> None:
        pack = _full_pack(version="v1")
        is_valid, _, warnings = PackValidator.validate(pack)
        assert is_valid is True
        assert any("semantic versioning" in w for w in warnings)

    def test_empty_version_warns(self) -> None:
        # "" is still present (REQUIRED_FIELDS check uses `in`, not truthy),
        # so the validator moves on to the format check and warns.
        pack = _full_pack(version="")
        is_valid, _, warnings = PackValidator.validate(pack)
        assert is_valid is True
        assert any("semantic versioning" in w for w in warnings)


# ---------------------------------------------------------------------------
# PackValidator.validate_category (standalone)
# ---------------------------------------------------------------------------


class TestValidateCategory:
    def test_full_category_passes(self) -> None:
        cat = {
            "id": "s22",
            "code": "S.22",
            "name": "Privacy",
            "description": "x",
            "color": "#0066cc",
        }
        is_valid, errors = PackValidator.validate_category(cat)
        assert is_valid is True
        assert errors == []

    def test_missing_field_fails(self) -> None:
        cat = {"id": "s22", "code": "S.22", "name": "Privacy", "description": "x"}
        is_valid, errors = PackValidator.validate_category(cat)
        assert is_valid is False
        assert any("color" in e for e in errors)

    def test_invalid_color_format_fails(self) -> None:
        cat = {
            "id": "s22",
            "code": "S.22",
            "name": "Privacy",
            "description": "x",
            "color": "blue",
        }
        is_valid, errors = PackValidator.validate_category(cat)
        assert is_valid is False
        assert any("Invalid color format" in e for e in errors)

    def test_short_hex_color_passes(self) -> None:
        cat = {
            "id": "s22",
            "code": "S.22",
            "name": "Privacy",
            "description": "x",
            "color": "#fff",
        }
        is_valid, _ = PackValidator.validate_category(cat)
        assert is_valid is True

    def test_wrong_length_hex_fails(self) -> None:
        cat = {
            "id": "s22",
            "code": "S.22",
            "name": "Privacy",
            "description": "x",
            "color": "#0066cc99",  # 9 chars
        }
        is_valid, errors = PackValidator.validate_category(cat)
        assert is_valid is False
        assert any("Invalid color format" in e for e in errors)


# ---------------------------------------------------------------------------
# PackValidator.validate_status (standalone)
# ---------------------------------------------------------------------------


class TestValidateStatus:
    def test_full_status_passes(self) -> None:
        status = {"value": "open", "label": "Open", "color": "#00ff00"}
        is_valid, errors = PackValidator.validate_status(status)
        assert is_valid is True
        assert errors == []

    def test_missing_field_fails(self) -> None:
        status = {"value": "open", "label": "Open"}
        is_valid, errors = PackValidator.validate_status(status)
        assert is_valid is False
        assert any("color" in e for e in errors)


# ---------------------------------------------------------------------------
# Module-level validate_pack convenience
# ---------------------------------------------------------------------------


class TestValidatePackConvenience:
    def test_returns_dict_with_metadata(self) -> None:
        result = validate_pack(_full_pack())
        assert result["valid"] is True
        assert result["errors"] == []
        assert result["warnings"] == []
        assert result["pack_id"] == "test-v1"
        assert result["pack_name"] == "Test Pack"

    def test_unknown_pack_id_and_name_when_missing(self) -> None:
        # Validator returns errors-only fast-path, but the wrapper still
        # populates pack_id/pack_name from the input dict (or 'unknown')
        result = validate_pack({})
        assert result["valid"] is False
        assert result["pack_id"] == "unknown"
        assert result["pack_name"] == "unknown"
