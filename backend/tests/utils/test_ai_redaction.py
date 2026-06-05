"""Tests for ``src.utils.ai_redaction``.

Covers:
- ``load_global_prompts`` (caching + IO failure)
- ``build_enhanced_system_prompt`` pure string composition
- ``get_redaction_suggestions`` async with stubbed LLM client + pack loader
- ``get_quick_pii_suggestions`` regex-based detection
- ``find_text_coordinates_in_pdf`` with in-memory PyMuPDF docs
- ``enrich_suggestions_with_coordinates`` happy paths
- ``find_text_in_ocr_data`` word + block search
"""

from __future__ import annotations

import io
import json
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import fitz  # PyMuPDF
import pytest

from src.utils import ai_redaction
from src.utils.ai_redaction import (
    build_enhanced_system_prompt,
    enrich_suggestions_with_coordinates,
    find_text_coordinates_in_pdf,
    find_text_in_ocr_data,
    get_quick_pii_suggestions,
    get_redaction_suggestions,
    load_global_prompts,
)


@pytest.fixture(autouse=True)
def _reset_prompt_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test gets a fresh global-prompts cache."""
    monkeypatch.setattr(ai_redaction, "_global_prompts_cache", None)


# ---------------------------------------------------------------------------
# load_global_prompts
# ---------------------------------------------------------------------------


class TestLoadGlobalPrompts:
    def test_returns_prompts_dict_on_success(self) -> None:
        fake_data = '{"core_principles": {"a": "be careful"}}'
        with patch("builtins.open", mock_open(read_data=fake_data)):
            data = load_global_prompts()
        assert data == {"core_principles": {"a": "be careful"}}

    def test_caches_result(self) -> None:
        fake_data = '{"x": 1}'
        with patch("builtins.open", mock_open(read_data=fake_data)) as mo:
            load_global_prompts()
            load_global_prompts()
        # File only opened once
        assert mo.call_count == 1

    def test_io_failure_returns_empty(self) -> None:
        with patch("builtins.open", side_effect=FileNotFoundError("nope")):
            assert load_global_prompts() == {}


# ---------------------------------------------------------------------------
# build_enhanced_system_prompt
# ---------------------------------------------------------------------------


class TestBuildEnhancedSystemPrompt:
    def test_combines_jurisdiction_and_global_principles(self) -> None:
        prompt = build_enhanced_system_prompt(
            "JURISDICTION_PROMPT_BODY",
            {
                "core_principles": {"a": "principle-a"},
                "behavior_rules": {"r": "rule-r"},
            },
        )
        assert "JURISDICTION_PROMPT_BODY" in prompt
        assert "principle-a" in prompt
        assert "rule-r" in prompt
        assert "UNIVERSAL PRINCIPLES" in prompt
        assert "BEHAVIOR REQUIREMENTS" in prompt

    def test_empty_globals_still_works(self) -> None:
        prompt = build_enhanced_system_prompt("X", {})
        assert "X" in prompt


# ---------------------------------------------------------------------------
# get_redaction_suggestions
# ---------------------------------------------------------------------------


class TestGetRedactionSuggestions:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_llm_client(self) -> None:
        with patch(
            "src.utils.ai_redaction.get_llm_client",
            new=AsyncMock(return_value=None),
        ):
            result = await get_redaction_suggestions("some text")
        assert result["suggestions"] == []
        # Copy was tightened in 6ef0929 to point operators at the actual
        # fix (set a default in Admin -> LLM Configuration).
        assert "no default llm" in result["summary"].lower()
        assert "error" in result

    @pytest.mark.asyncio
    async def test_parses_object_shaped_response(self) -> None:
        client = MagicMock()
        client.provider = "openai"
        client.model = "gpt-4o"
        client.chat_completion = AsyncMock(
            return_value=json.dumps(
                {
                    "suggestions": [
                        {
                            "text": "John Doe",
                            "category": "personal_info",
                            "reason": "name",
                            "confidence": "high",
                        }
                    ],
                    "summary": "1 finding",
                }
            )
        )
        with (
            patch(
                "src.utils.ai_redaction.get_llm_client",
                new=AsyncMock(return_value=client),
            ),
            patch(
                "src.packs.loader.get_pack_ai_prompts",
                return_value={"redaction_analysis": {}},
            ),
        ):
            result = await get_redaction_suggestions("doc text")
        assert len(result["suggestions"]) == 1
        # Section code attached
        assert result["suggestions"][0]["section"] == "S22"
        assert result["suggestions"][0]["category_label"]

    @pytest.mark.asyncio
    async def test_parses_array_shaped_response(self) -> None:
        client = MagicMock()
        client.provider = "openai"
        client.model = "gpt-4o"
        client.chat_completion = AsyncMock(
            return_value=json.dumps(
                [
                    {"text": "alice", "category": "personal_info", "reason": "n"},
                ]
            )
        )
        with (
            patch(
                "src.utils.ai_redaction.get_llm_client",
                new=AsyncMock(return_value=client),
            ),
            patch(
                "src.packs.loader.get_pack_ai_prompts",
                return_value={"redaction_analysis": {}},
            ),
        ):
            result = await get_redaction_suggestions("doc text")
        assert len(result["suggestions"]) == 1
        # The array form is wrapped into the object structure
        assert "AI identified" in result["summary"]

    @pytest.mark.asyncio
    async def test_parses_single_suggestion_response(self) -> None:
        """LLM returns a single suggestion object (not wrapped in
        suggestions list) — the function wraps it."""
        client = MagicMock()
        client.provider = "openai"
        client.model = "gpt-4o"
        client.chat_completion = AsyncMock(
            return_value=json.dumps({"text": "alice", "category": "personal_info", "reason": "n"})
        )
        with (
            patch(
                "src.utils.ai_redaction.get_llm_client",
                new=AsyncMock(return_value=client),
            ),
            patch(
                "src.packs.loader.get_pack_ai_prompts",
                return_value={"redaction_analysis": {}},
            ),
        ):
            result = await get_redaction_suggestions("doc text")
        assert len(result["suggestions"]) == 1

    @pytest.mark.asyncio
    async def test_extracts_json_from_markdown_code_block(self) -> None:
        client = MagicMock()
        client.provider = "openai"
        client.model = "gpt-4o"
        client.chat_completion = AsyncMock(
            return_value=(
                "Here is my analysis:\n```json\n"
                + json.dumps({"suggestions": [], "summary": "none"})
                + "\n```\nThat's all."
            )
        )
        with (
            patch(
                "src.utils.ai_redaction.get_llm_client",
                new=AsyncMock(return_value=client),
            ),
            patch(
                "src.packs.loader.get_pack_ai_prompts",
                return_value={"redaction_analysis": {}},
            ),
        ):
            result = await get_redaction_suggestions("doc text")
        assert result["summary"] == "none"

    @pytest.mark.asyncio
    async def test_extracts_json_from_generic_code_block(self) -> None:
        client = MagicMock()
        client.provider = "openai"
        client.model = "gpt-4o"
        client.chat_completion = AsyncMock(
            return_value='```\n[{"text":"a","category":"personal_info"}]\n```'
        )
        with (
            patch(
                "src.utils.ai_redaction.get_llm_client",
                new=AsyncMock(return_value=client),
            ),
            patch(
                "src.packs.loader.get_pack_ai_prompts",
                return_value={"redaction_analysis": {}},
            ),
        ):
            result = await get_redaction_suggestions("doc text")
        assert len(result["suggestions"]) == 1

    @pytest.mark.asyncio
    async def test_extracts_json_when_prefixed_with_text(self) -> None:
        client = MagicMock()
        client.provider = "openai"
        client.model = "gpt-4o"
        client.chat_completion = AsyncMock(return_value='Prefix: {"suggestions":[],"summary":"x"}')
        with (
            patch(
                "src.utils.ai_redaction.get_llm_client",
                new=AsyncMock(return_value=client),
            ),
            patch(
                "src.packs.loader.get_pack_ai_prompts",
                return_value={"redaction_analysis": {}},
            ),
        ):
            result = await get_redaction_suggestions("doc text")
        assert result["summary"] == "x"

    @pytest.mark.asyncio
    async def test_with_context_appends_to_user_prompt(self) -> None:
        client = MagicMock()
        client.provider = "openai"
        client.model = "gpt-4o"
        client.chat_completion = AsyncMock(
            return_value=json.dumps({"suggestions": [], "summary": "ok"})
        )
        with (
            patch(
                "src.utils.ai_redaction.get_llm_client",
                new=AsyncMock(return_value=client),
            ),
            patch(
                "src.packs.loader.get_pack_ai_prompts",
                return_value={"redaction_analysis": {}},
            ),
        ):
            await get_redaction_suggestions("doc text", context="extra context here")
        # Check that the user prompt includes the context
        prompts = client.chat_completion.call_args.kwargs["messages"]
        user_msg = prompts[1]["content"]
        assert "extra context here" in user_msg

    @pytest.mark.asyncio
    async def test_exception_caught(self) -> None:
        client = MagicMock()
        client.provider = "openai"
        client.model = "gpt-4o"
        client.chat_completion = AsyncMock(side_effect=RuntimeError("boom"))
        with (
            patch(
                "src.utils.ai_redaction.get_llm_client",
                new=AsyncMock(return_value=client),
            ),
            patch(
                "src.packs.loader.get_pack_ai_prompts",
                return_value={"redaction_analysis": {}},
            ),
        ):
            result = await get_redaction_suggestions("doc text")
        assert result["suggestions"] == []
        assert "boom" in result["summary"]
        assert "error" in result


# ---------------------------------------------------------------------------
# get_quick_pii_suggestions
# ---------------------------------------------------------------------------


class TestGetQuickPiiSuggestions:
    def test_detects_email(self) -> None:
        s = get_quick_pii_suggestions("Contact alice@example.com for details.")
        emails = [x for x in s if x["reason"] == "Email address"]
        assert len(emails) == 1
        assert emails[0]["text"] == "alice@example.com"
        assert emails[0]["section"] == "S22"

    def test_detects_phone(self) -> None:
        s = get_quick_pii_suggestions("Call 604-555-1234 today.")
        phones = [x for x in s if x["reason"] == "Phone number"]
        assert len(phones) == 1

    def test_detects_canadian_postal_code(self) -> None:
        s = get_quick_pii_suggestions("Mail to V6B 2W9 please.")
        postals = [x for x in s if x["reason"] == "Postal code"]
        assert len(postals) == 1
        assert "V6B" in postals[0]["text"]

    def test_detects_zip_code(self) -> None:
        s = get_quick_pii_suggestions("ZIP 90210 nice place.")
        zips = [x for x in s if x["reason"] == "ZIP code"]
        assert len(zips) >= 1

    def test_detects_street_address(self) -> None:
        s = get_quick_pii_suggestions("Located at 123 Main Street.")
        addrs = [x for x in s if x["reason"] == "Street address"]
        assert len(addrs) == 1

    def test_detects_sin(self) -> None:
        s = get_quick_pii_suggestions("SIN: 123-456-789 on file.")
        sins = [x for x in s if x["reason"] == "Possible SIN"]
        assert len(sins) == 1

    def test_detects_credit_card(self) -> None:
        s = get_quick_pii_suggestions("Card: 4111 1111 1111 1111 charged.")
        cards = [x for x in s if x["reason"] == "Possible credit card number"]
        assert len(cards) == 1
        assert cards[0]["category"] == "financial"

    def test_detects_vat_id(self) -> None:
        s = get_quick_pii_suggestions("VAT GB123456789 paid.")
        vats = [x for x in s if x["reason"] == "Possible VAT/Tax ID"]
        assert len(vats) >= 1

    def test_detects_invoice_id(self) -> None:
        s = get_quick_pii_suggestions("Invoice INV2024-ABCD0001 issued.")
        invs = [x for x in s if x["reason"] == "Invoice/Receipt number"]
        assert len(invs) >= 1

    def test_detects_person_with_title(self) -> None:
        s = get_quick_pii_suggestions("Mr. John Smith attended.")
        names = [x for x in s if x["reason"] == "Person name" and "Smith" in x["text"]]
        assert len(names) >= 1

    def test_detects_person_with_context_label(self) -> None:
        s = get_quick_pii_suggestions("Bill to: Jane Doe.")
        # The context-name regex should pick up "Jane Doe"
        names = [x for x in s if x["reason"] == "Person name"]
        assert any("Jane" in x["text"] for x in names)

    def test_no_duplicates(self) -> None:
        s = get_quick_pii_suggestions("alice@example.com and alice@example.com again")
        emails = [x for x in s if x["reason"] == "Email address"]
        assert len(emails) == 1

    def test_empty_text_returns_no_suggestions(self) -> None:
        assert get_quick_pii_suggestions("") == []


# ---------------------------------------------------------------------------
# find_text_coordinates_in_pdf
# ---------------------------------------------------------------------------


def _build_pdf_with_text(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((50, 100), text, fontsize=12)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


class TestFindTextCoordinatesInPdf:
    def test_finds_exact_match(self) -> None:
        pdf = _build_pdf_with_text("Hello world")
        coords = find_text_coordinates_in_pdf(pdf, "Hello")
        assert len(coords) == 1
        assert coords[0]["page"] == 1
        assert coords[0]["x"] > 0
        assert coords[0]["width"] > 0

    def test_text_not_found_returns_empty(self) -> None:
        pdf = _build_pdf_with_text("Hello world")
        coords = find_text_coordinates_in_pdf(pdf, "nowhere")
        assert coords == []

    def test_invalid_pdf_returns_empty(self) -> None:
        coords = find_text_coordinates_in_pdf(b"not a pdf", "x")
        assert coords == []


# ---------------------------------------------------------------------------
# enrich_suggestions_with_coordinates
# ---------------------------------------------------------------------------


class TestEnrichSuggestionsWithCoordinates:
    def test_enriches_with_pdf_coords(self) -> None:
        pdf = _build_pdf_with_text("Find Hello here")
        suggestions = [{"text": "Hello"}]
        enriched = enrich_suggestions_with_coordinates(suggestions, pdf)
        assert len(enriched) == 1
        assert enriched[0]["has_coordinates"] is True
        assert "coordinates" in enriched[0]
        assert enriched[0]["page"] == 1

    def test_falls_back_to_ocr_data(self) -> None:
        # Build an empty PDF so PDF search returns nothing
        empty = _build_pdf_with_text("nothing")
        text_data = {
            "pages": [
                {
                    "page_num": 1,
                    "text": "alice was here",
                    "words": [
                        {"text": "alice", "bbox": [10, 20, 50, 30]},
                        {"text": "was", "bbox": [55, 20, 85, 30]},
                    ],
                }
            ]
        }
        enriched = enrich_suggestions_with_coordinates(
            [{"text": "alice"}], empty, text_data=text_data
        )
        assert len(enriched) == 1
        assert enriched[0]["has_coordinates"] is True

    def test_no_match_marks_no_coordinates(self) -> None:
        empty = _build_pdf_with_text("nothing")
        suggestions = [{"text": "missing"}]
        enriched = enrich_suggestions_with_coordinates(suggestions, empty)
        assert enriched[0]["has_coordinates"] is False
        assert enriched[0]["page"] == 1  # default


# ---------------------------------------------------------------------------
# find_text_in_ocr_data
# ---------------------------------------------------------------------------


class TestFindTextInOcrData:
    def test_finds_in_words(self) -> None:
        text_data = {
            "pages": [
                {
                    "page_num": 1,
                    "text": "alice was here",
                    "words": [
                        {"text": "alice", "bbox": [10, 20, 50, 30]},
                        {"text": "was", "bbox": [55, 20, 85, 30]},
                    ],
                }
            ]
        }
        result = find_text_in_ocr_data("alice", text_data)
        assert len(result) == 1
        assert result[0]["page"] == 1

    def test_multi_word_match(self) -> None:
        text_data = {
            "pages": [
                {
                    "page_num": 1,
                    "text": "alice was here",
                    "words": [
                        {"text": "alice", "bbox": [10, 20, 50, 30]},
                        {"text": "was", "bbox": [55, 20, 85, 30]},
                        {"text": "here", "bbox": [90, 20, 130, 30]},
                    ],
                }
            ]
        }
        result = find_text_in_ocr_data("alice was", text_data)
        assert len(result) == 1
        # Bounding box spans both words
        assert result[0]["x"] == 10
        assert result[0]["width"] > 40

    def test_text_not_on_page_returns_empty(self) -> None:
        text_data = {
            "pages": [
                {"page_num": 1, "text": "bob", "words": [{"text": "bob", "bbox": [0, 0, 10, 10]}]}
            ]
        }
        result = find_text_in_ocr_data("alice", text_data)
        assert result == []

    def test_falls_back_to_blocks_when_no_words(self) -> None:
        text_data = {
            "pages": [
                {
                    "page_num": 1,
                    "text": "alice was here",
                    "words": [],
                    "blocks": [
                        {"text": "alice was here", "bbox": [10, 20, 100, 30]},
                    ],
                }
            ]
        }
        result = find_text_in_ocr_data("alice", text_data)
        assert len(result) == 1
        assert result[0]["page"] == 1
