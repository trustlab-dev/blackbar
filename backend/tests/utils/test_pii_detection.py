"""Tests for ``src.utils.pii_detection``.

Per audit Q15: **Presidio is deactivated** in the BlackBar production
deployment — the spaCy + Presidio dependency was dropped during Phase
1.x because the BC FOIPPA pipeline relies on the rule-based regex
detector in ``src.utils.ai_redaction.get_quick_pii_suggestions``
instead.

Phase 4 Batch 4.4 (audit B52): the module's Presidio imports are now
guarded with ``try``/``except ImportError`` so the module loads in
inert mode when ``presidio_analyzer`` is uninstalled. Public entry
points raise a clear ``RuntimeError`` if invoked. The Presidio-
dependent test cases below are skipped when the optional dependency
is absent.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys

import pytest

_PRESIDIO_AVAILABLE = importlib.util.find_spec("presidio_analyzer") is not None


# ---------------------------------------------------------------------------
# Always-runnable test: pin the deactivated-Presidio import behavior.
# ---------------------------------------------------------------------------


def test_pii_detection_module_imports_in_inert_mode_without_presidio() -> None:
    """Phase 4 Batch 4.4 (audit B52): the module imports cleanly even
    when ``presidio_analyzer`` is absent — the top-level imports are
    guarded. Public entry points raise ``RuntimeError`` if called.

    Test flipped from the prior ``pytest.raises(ModuleNotFoundError)``
    characterization that pinned the bare ``ImportError`` blow-up at
    module load."""
    sys.modules.pop("src.utils.pii_detection", None)
    mod = importlib.import_module("src.utils.pii_detection")
    assert hasattr(mod, "detect_pii")
    assert hasattr(mod, "get_analyzer")
    assert hasattr(mod, "_PRESIDIO_AVAILABLE")
    # The boolean MUST match the runtime environment: True iff the
    # optional dependency is importable here.
    assert mod._PRESIDIO_AVAILABLE is _PRESIDIO_AVAILABLE

    if not _PRESIDIO_AVAILABLE:
        # Calling get_analyzer in the deactivated environment raises a
        # clear RuntimeError (not the prior bare ImportError at module
        # load).
        with pytest.raises(RuntimeError, match="presidio-analyzer"):
            mod.get_analyzer()


# ---------------------------------------------------------------------------
# Presidio-dependent tests (skipped when Presidio is uninstalled, which is
# the documented production state — audit Q15).
# ---------------------------------------------------------------------------


pytestmark_when_presidio = pytest.mark.skipif(
    not _PRESIDIO_AVAILABLE,
    reason="Presidio is deactivated in production (audit Q15) — "
    "skipping detector-dependent tests when the optional dependency is absent.",
)


@pytestmark_when_presidio
class TestMapPresidioToCategory:
    """Pure dict-lookup helper — testable when Presidio is installed."""

    @pytest.mark.parametrize(
        "presidio_type,category",
        [
            ("PERSON", "personal_information"),
            ("NRP", "personal_information"),
            ("PHONE_NUMBER", "contact_information"),
            ("EMAIL_ADDRESS", "contact_information"),
            ("URL", "contact_information"),
            ("LOCATION", "address"),
            ("CA_POSTAL_CODE", "address"),
            ("DATE_TIME", "dates"),
            ("CREDIT_CARD", "financial_information"),
            ("IBAN_CODE", "financial_information"),
            ("CRYPTO", "financial_information"),
            ("US_BANK_NUMBER", "financial_information"),
            ("US_SSN", "identifiers"),
            ("CA_SIN", "identifiers"),
            ("US_DRIVER_LICENSE", "identifiers"),
            ("BC_DRIVERS_LICENSE", "identifiers"),
            ("US_PASSPORT", "identifiers"),
            ("US_ITIN", "identifiers"),
            ("MEDICAL_LICENSE", "medical_information"),
            ("BC_PHN", "medical_information"),
            ("IP_ADDRESS", "technical_information"),
        ],
    )
    def test_known_mappings(self, presidio_type: str, category: str) -> None:
        from src.utils.pii_detection import map_presidio_to_category

        assert map_presidio_to_category(presidio_type) == category

    def test_unknown_defaults_to_personal_information(self) -> None:
        from src.utils.pii_detection import map_presidio_to_category

        assert map_presidio_to_category("NON_EXISTENT") == "personal_information"


@pytestmark_when_presidio
class TestGetCategoryExamples:
    def test_known_category_has_positive_and_negative(self) -> None:
        from src.utils.pii_detection import get_category_examples

        ex = get_category_examples("personal_information")
        assert "positive" in ex
        assert "negative" in ex
        assert len(ex["positive"]) > 0

    @pytest.mark.parametrize(
        "category",
        [
            "personal_information",
            "contact_information",
            "address",
            "identifiers",
            "medical_information",
            "financial_information",
        ],
    )
    def test_each_documented_category_returns_examples(self, category: str) -> None:
        from src.utils.pii_detection import get_category_examples

        ex = get_category_examples(category)
        assert isinstance(ex["positive"], list)
        assert isinstance(ex["negative"], list)

    def test_unknown_category_returns_empty_examples(self) -> None:
        from src.utils.pii_detection import get_category_examples

        ex = get_category_examples("not-a-category")
        assert ex == {"positive": [], "negative": []}
