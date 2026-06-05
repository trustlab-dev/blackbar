"""
Pack Validator - Validates jurisdiction pack schema
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Required top-level fields
REQUIRED_FIELDS = [
    "pack_id",
    "name",
    "version",
    "jurisdiction",
    "terminology",
    "timelines",
    "statuses",
    "redaction_categories",
]

# Required jurisdiction fields
REQUIRED_JURISDICTION_FIELDS = ["country", "region", "legislation"]

# Required category fields
REQUIRED_CATEGORY_FIELDS = ["id", "code", "name", "description", "color"]

# Required status fields
REQUIRED_STATUS_FIELDS = ["value", "label", "color"]


class PackValidator:
    """Validates jurisdiction pack structure and content"""

    @staticmethod
    def validate(pack_data: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
        """
        Validate a pack

        Args:
            pack_data: Pack data dictionary

        Returns:
            Tuple of (is_valid, errors, warnings)
        """
        errors = []
        warnings = []

        # Check required top-level fields
        for field in REQUIRED_FIELDS:
            if field not in pack_data:
                errors.append(f"Missing required field: {field}")

        if errors:
            return False, errors, warnings

        # Validate jurisdiction
        jurisdiction = pack_data.get("jurisdiction", {})
        for field in REQUIRED_JURISDICTION_FIELDS:
            if field not in jurisdiction:
                errors.append(f"Missing required jurisdiction field: {field}")

        # Validate redaction categories
        categories = pack_data.get("redaction_categories", [])
        if not categories:
            errors.append("Pack must have at least one redaction category")
        else:
            for i, category in enumerate(categories):
                for field in REQUIRED_CATEGORY_FIELDS:
                    if field not in category:
                        errors.append(f"Category {i}: Missing required field '{field}'")

                # Validate color format
                if "color" in category and not category["color"].startswith("#"):
                    warnings.append(
                        f"Category {i} ({category.get('code', 'unknown')}): Color should be hex format (e.g., #0066cc)"
                    )

        # Validate statuses
        statuses = pack_data.get("statuses", [])
        if not statuses:
            errors.append("Pack must have at least one status")
        else:
            for i, status in enumerate(statuses):
                for field in REQUIRED_STATUS_FIELDS:
                    if field not in status:
                        errors.append(f"Status {i}: Missing required field '{field}'")

        # Validate timelines
        timelines = pack_data.get("timelines", {})
        if "default_response_days" not in timelines:
            errors.append("Timelines must specify 'default_response_days'")
        elif not isinstance(timelines["default_response_days"], (int, float)):
            errors.append("'default_response_days' must be a number")

        # Validate terminology
        terminology = pack_data.get("terminology", {})
        recommended_terminology = ["request_type", "requester", "case"]
        for term in recommended_terminology:
            if term not in terminology:
                warnings.append(f"Recommended terminology field missing: {term}")

        # Validate templates (optional but recommended)
        templates = pack_data.get("templates", {})
        if not templates:
            warnings.append(
                "No templates defined - consider adding acknowledgment_letter and response_letter"
            )

        # Validate AI prompts (optional)
        ai_prompts = pack_data.get("ai_prompts", {})
        if not ai_prompts:
            warnings.append("No AI prompts defined - AI features will be limited")

        # Check version format
        version = pack_data.get("version", "")
        if not version or "." not in version:
            warnings.append("Version should follow semantic versioning (e.g., 1.0.0)")

        is_valid = len(errors) == 0

        return is_valid, errors, warnings

    @staticmethod
    def validate_category(category: dict[str, Any]) -> tuple[bool, list[str]]:
        """
        Validate a single redaction category

        Args:
            category: Category data dictionary

        Returns:
            Tuple of (is_valid, errors)
        """
        errors = []

        for field in REQUIRED_CATEGORY_FIELDS:
            if field not in category:
                errors.append(f"Missing required field: {field}")

        # Validate color format
        if "color" in category:
            color = category["color"]
            if not color.startswith("#") or len(color) not in [4, 7]:
                errors.append(f"Invalid color format: {color} (should be #RGB or #RRGGBB)")

        return len(errors) == 0, errors

    @staticmethod
    def validate_status(status: dict[str, Any]) -> tuple[bool, list[str]]:
        """
        Validate a single status

        Args:
            status: Status data dictionary

        Returns:
            Tuple of (is_valid, errors)
        """
        errors = []

        for field in REQUIRED_STATUS_FIELDS:
            if field not in status:
                errors.append(f"Missing required field: {field}")

        return len(errors) == 0, errors


def validate_pack(pack_data: dict[str, Any]) -> dict[str, Any]:
    """
    Validate a pack and return results

    Args:
        pack_data: Pack data dictionary

    Returns:
        Validation results dictionary
    """
    is_valid, errors, warnings = PackValidator.validate(pack_data)

    return {
        "valid": is_valid,
        "errors": errors,
        "warnings": warnings,
        "pack_id": pack_data.get("pack_id", "unknown"),
        "pack_name": pack_data.get("name", "unknown"),
    }
