"""
PII Detection using Microsoft Presidio
Tier 2 detection for fast, rule-based identification of common PII patterns.

Phase 4 Batch 4.4 (audit B52, Q15): the Presidio integration is
DEACTIVATED for the 0.1.0 OSS release. ``presidio-analyzer`` is not in
the production dependency list, so an unconditional top-level import
would raise ``ImportError`` at module load — breaking any caller that
imports this module (even transitively) in production.

The imports below are guarded with ``try``/``except ImportError`` so
the module loads but its public entry-points raise a clear
``RuntimeError`` if invoked while Presidio is uninstalled. Re-
activation guidance: add ``presidio-analyzer`` and ``presidio-
anonymizer`` to ``pyproject.toml`` and install the matching spaCy
model.
"""

import logging

logger = logging.getLogger(__name__)

try:
    from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
    from presidio_analyzer.nlp_engine import NlpEngineProvider

    _PRESIDIO_AVAILABLE = True
except ImportError as _e:  # pragma: no cover — exercised when presidio is uninstalled
    logger.info(
        "Presidio not installed; PII detection module loaded in inert mode. "
        "Re-enable by installing presidio-analyzer. Underlying error: %s",
        _e,
    )
    AnalyzerEngine = None  # type: ignore[assignment]
    Pattern = None  # type: ignore[assignment]
    PatternRecognizer = None  # type: ignore[assignment]
    NlpEngineProvider = None  # type: ignore[assignment]
    _PRESIDIO_AVAILABLE = False


def _require_presidio() -> None:
    """Guard for public callers: raise a clear error when Presidio is
    not installed instead of returning silently bogus results."""
    if not _PRESIDIO_AVAILABLE:
        raise RuntimeError(
            "PII detection is unavailable: `presidio-analyzer` is not "
            "installed. Add it to pyproject.toml and install the "
            "matching spaCy model to re-enable."
        )


# Initialize Presidio analyzer (singleton)
_analyzer_instance = None


def get_analyzer() -> "AnalyzerEngine":
    """Get or create the Presidio analyzer instance."""
    _require_presidio()
    global _analyzer_instance

    if _analyzer_instance is None:
        logger.info("Initializing Presidio analyzer...")

        # Create NLP engine with spaCy
        configuration = {
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_lg"}],
        }

        try:
            provider = NlpEngineProvider(nlp_configuration=configuration)
            nlp_engine = provider.create_engine()

            # Create analyzer with custom recognizers
            _analyzer_instance = AnalyzerEngine(nlp_engine=nlp_engine)

            # Add BC-specific recognizers
            _add_bc_recognizers(_analyzer_instance)

            logger.info("Presidio analyzer initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Presidio: {e}")
            # Fallback to default analyzer without custom NLP
            _analyzer_instance = AnalyzerEngine()

    return _analyzer_instance


def _add_bc_recognizers(analyzer: "AnalyzerEngine"):
    """Add BC-specific PII recognizers."""

    # BC Personal Health Number (PHN) - 10 digits
    bc_phn_pattern = Pattern(
        name="bc_phn_pattern",
        regex=r"\b\d{10}\b",
        score=0.7,  # Lower score since it's just 10 digits
    )

    bc_phn_recognizer = PatternRecognizer(
        supported_entity="BC_PHN",
        patterns=[bc_phn_pattern],
        context=["PHN", "health number", "personal health", "BC health"],
    )
    analyzer.registry.add_recognizer(bc_phn_recognizer)

    # BC Driver's License - Format: 1234567 (7 digits)
    bc_dl_pattern = Pattern(
        name="bc_dl_pattern",
        regex=r"\b\d{7}\b",
        score=0.6,  # Lower score since it's just 7 digits
    )

    bc_dl_recognizer = PatternRecognizer(
        supported_entity="BC_DRIVERS_LICENSE",
        patterns=[bc_dl_pattern],
        context=["driver", "license", "licence", "DL", "driver's"],
    )
    analyzer.registry.add_recognizer(bc_dl_recognizer)

    # Canadian SIN (Social Insurance Number) - XXX-XXX-XXX
    sin_pattern = Pattern(name="sin_pattern", regex=r"\b\d{3}[-\s]?\d{3}[-\s]?\d{3}\b", score=0.9)

    sin_recognizer = PatternRecognizer(
        supported_entity="CA_SIN",
        patterns=[sin_pattern],
        context=["SIN", "social insurance", "insurance number"],
    )
    analyzer.registry.add_recognizer(sin_recognizer)

    # Canadian Postal Code - A1A 1A1
    postal_pattern = Pattern(
        name="postal_pattern", regex=r"\b[A-Z]\d[A-Z]\s?\d[A-Z]\d\b", score=0.8
    )

    postal_recognizer = PatternRecognizer(
        supported_entity="CA_POSTAL_CODE",
        patterns=[postal_pattern],
        context=["postal", "zip", "address", "mail"],
    )
    analyzer.registry.add_recognizer(postal_recognizer)

    logger.info("Added BC-specific recognizers")


def detect_pii(
    text: str, language: str = "en", entities: list[str] | None = None, score_threshold: float = 0.5
) -> list[dict]:
    """
    Detect PII entities in text using Presidio.

    Args:
        text: Text to analyze
        language: Language code (default: "en")
        entities: Specific entity types to detect (None = all)
        score_threshold: Minimum confidence score (0.0-1.0)

    Returns:
        List of detected entities with text, type, position, and score
    """
    analyzer = get_analyzer()

    # Default entity types if none specified
    if entities is None:
        entities = [
            "PHONE_NUMBER",
            "EMAIL_ADDRESS",
            "PERSON",
            "LOCATION",
            "DATE_TIME",
            "CREDIT_CARD",
            "CRYPTO",
            "IBAN_CODE",
            "IP_ADDRESS",
            "NRP",
            "MEDICAL_LICENSE",
            "URL",
            "US_BANK_NUMBER",
            "US_DRIVER_LICENSE",
            "US_ITIN",
            "US_PASSPORT",
            "US_SSN",
            "BC_PHN",
            "BC_DRIVERS_LICENSE",
            "CA_SIN",
            "CA_POSTAL_CODE",
        ]

    try:
        results = analyzer.analyze(
            text=text, language=language, entities=entities, score_threshold=score_threshold
        )

        # Convert to dict format
        detected = []
        for result in results:
            detected.append(
                {
                    "text": text[result.start : result.end],
                    "type": result.entity_type,
                    "start": result.start,
                    "end": result.end,
                    "score": result.score,
                    "recognition_metadata": result.recognition_metadata,
                }
            )

        return detected

    except Exception as e:
        logger.error(f"Error detecting PII: {e}")
        return []


def map_presidio_to_category(presidio_type: str) -> str:
    """
    Map Presidio entity types to BlackBar redaction categories.

    Args:
        presidio_type: Presidio entity type (e.g., "PERSON", "PHONE_NUMBER")

    Returns:
        BlackBar category string
    """
    mapping = {
        # Personal identifiers
        "PERSON": "personal_information",
        "NRP": "personal_information",  # Named entity (person)
        # Contact information
        "PHONE_NUMBER": "contact_information",
        "EMAIL_ADDRESS": "contact_information",
        "URL": "contact_information",
        # Location
        "LOCATION": "address",
        "CA_POSTAL_CODE": "address",
        # Dates and times
        "DATE_TIME": "dates",
        # Financial
        "CREDIT_CARD": "financial_information",
        "IBAN_CODE": "financial_information",
        "CRYPTO": "financial_information",
        "US_BANK_NUMBER": "financial_information",
        # Government IDs
        "US_SSN": "identifiers",
        "CA_SIN": "identifiers",
        "US_DRIVER_LICENSE": "identifiers",
        "BC_DRIVERS_LICENSE": "identifiers",
        "US_PASSPORT": "identifiers",
        "US_ITIN": "identifiers",
        # Medical
        "MEDICAL_LICENSE": "medical_information",
        "BC_PHN": "medical_information",
        # Technical
        "IP_ADDRESS": "technical_information",
    }

    return mapping.get(presidio_type, "personal_information")


def get_category_examples(category: str) -> dict[str, list[str]]:
    """
    Get example text for a given category.
    Used in the reason picker to show users what qualifies.

    Returns:
        Dict with 'positive' and 'negative' example lists
    """
    examples = {
        "personal_information": {
            "positive": ["John Doe applied for the position", "Contact Sarah Smith at the office"],
            "negative": ["The applicant has relevant experience"],
        },
        "contact_information": {
            "positive": ["Call 604-555-1234 for details", "Email info@example.com"],
            "negative": ["Contact the department"],
        },
        "address": {
            "positive": ["123 Main Street, Vancouver, BC V6B 2W9", "Located at 456 Oak Avenue"],
            "negative": ["The building is downtown"],
        },
        "identifiers": {
            "positive": ["SIN: 123-456-789", "Driver's license #1234567"],
            "negative": ["The ID number is on file"],
        },
        "medical_information": {
            "positive": ["PHN 1234567890", "Medical history shows..."],
            "negative": ["Health services are available"],
        },
        "financial_information": {
            "positive": ["Credit card ending in 1234", "Account balance is $5,000"],
            "negative": ["Financial assistance available"],
        },
    }

    return examples.get(category, {"positive": [], "negative": []})


def batch_detect_pii(texts: list[str], **kwargs) -> list[list[dict]]:
    """
    Detect PII in multiple text strings.
    More efficient than calling detect_pii multiple times.

    Args:
        texts: List of text strings to analyze
        **kwargs: Arguments to pass to detect_pii

    Returns:
        List of detection results, one per input text
    """
    results = []
    for text in texts:
        results.append(detect_pii(text, **kwargs))
    return results
