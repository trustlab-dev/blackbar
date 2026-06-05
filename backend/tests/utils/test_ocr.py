"""Tests for ``src.utils.ocr``.

``extract_text_with_coordinates`` is the primary entry point used by the
document-processing pipeline. The native-text path is exercised directly
with PyMuPDF-built fixtures (fast, deterministic); the OCR fallback path
is exercised by stubbing ``pytesseract.image_to_data`` so we don't depend
on Tesseract being installed in CI.
"""

from __future__ import annotations

import io
from unittest.mock import patch

import fitz  # PyMuPDF
import pytest

from src.utils.ocr import extract_text_with_coordinates, get_text_summary


def _make_text_pdf(text: str = "Hello world") -> bytes:
    """One-page PDF with embedded native text."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((50, 100), text, fontsize=12)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def _make_image_only_pdf() -> bytes:
    """One-page PDF that contains no native text — only an embedded
    raster image. PyMuPDF treats this as needing OCR.
    """
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    # Use a tiny solid-color rectangle as a "drawing" — no text => no
    # native-text blocks for the page-text dict. This triggers the OCR
    # fallback in extract_text_with_coordinates.
    rect = fitz.Rect(0, 0, 100, 100)
    page.draw_rect(rect, color=(0.5, 0.5, 0.5), fill=(0.5, 0.5, 0.5))
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# extract_text_with_coordinates — native-text path
# ---------------------------------------------------------------------------


class TestExtractTextNative:
    @pytest.mark.asyncio
    async def test_returns_structured_pages_for_text_pdf(self) -> None:
        pdf = _make_text_pdf("Hello world")
        result = await extract_text_with_coordinates(pdf)
        assert "pages" in result
        assert "full_text" in result
        assert len(result["pages"]) == 1
        page = result["pages"][0]
        assert page["page_num"] == 1
        assert page["width"] == 612.0
        assert page["height"] == 792.0
        assert "Hello" in page["text"]
        # Native text path populates blocks AND words AND lines
        assert len(page["blocks"]) > 0
        assert len(page["words"]) > 0
        assert len(page["lines"]) > 0

    @pytest.mark.asyncio
    async def test_words_have_bbox_and_confidence(self) -> None:
        pdf = _make_text_pdf("Hello")
        result = await extract_text_with_coordinates(pdf)
        page = result["pages"][0]
        word = page["words"][0]
        assert "text" in word
        assert "bbox" in word
        assert len(word["bbox"]) == 4
        # Native text confidence is 1.0
        assert word["confidence"] == 1.0
        assert word["line_num"] >= 1
        assert word["word_num"] >= 1

    @pytest.mark.asyncio
    async def test_lines_aggregate_words(self) -> None:
        pdf = _make_text_pdf("Hello world from PDF")
        result = await extract_text_with_coordinates(pdf)
        page = result["pages"][0]
        assert len(page["lines"]) >= 1
        line = page["lines"][0]
        assert "text" in line
        assert "bbox" in line
        assert "line_num" in line
        assert "words" in line

    @pytest.mark.asyncio
    async def test_full_text_aggregates_pages(self) -> None:
        pdf = _make_text_pdf("Hello world")
        result = await extract_text_with_coordinates(pdf)
        assert "Hello" in result["full_text"]


# ---------------------------------------------------------------------------
# extract_text_with_coordinates — OCR fallback path (stubbed)
# ---------------------------------------------------------------------------


class TestExtractTextOcrFallback:
    @pytest.mark.asyncio
    async def test_ocr_fallback_uses_pytesseract(self) -> None:
        """When the page has no native text blocks, the function falls
        back to pytesseract.image_to_data. We stub that to verify the
        OCR branch produces the expected page structure."""
        pdf = _make_image_only_pdf()

        # pytesseract.image_to_data returns a dict of lists, one entry
        # per detected word. We synthesize two words at line 1.
        fake_ocr_data = {
            "text": ["", "Hello", "World"],
            "conf": [-1, "95", "90"],
            "left": [0, 50, 150],
            "top": [0, 100, 100],
            "width": [0, 80, 80],
            "height": [0, 20, 20],
            "line_num": [0, 1, 1],
        }

        with patch(
            "src.utils.ocr.pytesseract.image_to_data",
            return_value=fake_ocr_data,
        ):
            result = await extract_text_with_coordinates(pdf)

        page = result["pages"][0]
        # OCR populated words, lines, blocks
        assert len(page["words"]) == 2
        word_texts = [w["text"] for w in page["words"]]
        assert word_texts == ["Hello", "World"]
        # Confidence comes through scaled to 0..1
        assert all(0 < w["confidence"] <= 1 for w in page["words"])
        # Line aggregation
        assert len(page["lines"]) == 1
        assert "Hello" in page["lines"][0]["text"]
        assert "World" in page["lines"][0]["text"]

    @pytest.mark.asyncio
    async def test_ocr_filters_low_confidence_words(self) -> None:
        """Words with confidence <= 0.5 are dropped."""
        pdf = _make_image_only_pdf()
        fake_ocr_data = {
            "text": ["Confident", "Unsure"],
            "conf": ["90", "30"],  # 0.3 < 0.5 threshold
            "left": [10, 100],
            "top": [10, 10],
            "width": [50, 50],
            "height": [20, 20],
            "line_num": [1, 1],
        }
        with patch(
            "src.utils.ocr.pytesseract.image_to_data",
            return_value=fake_ocr_data,
        ):
            result = await extract_text_with_coordinates(pdf)

        word_texts = [w["text"] for w in result["pages"][0]["words"]]
        assert "Confident" in word_texts
        assert "Unsure" not in word_texts

    @pytest.mark.asyncio
    async def test_ocr_with_multiple_lines(self) -> None:
        pdf = _make_image_only_pdf()
        fake_ocr_data = {
            "text": ["Line", "one", "Line", "two"],
            "conf": ["95", "95", "95", "95"],
            "left": [10, 60, 10, 60],
            "top": [10, 10, 30, 30],
            "width": [40, 40, 40, 40],
            "height": [15, 15, 15, 15],
            "line_num": [1, 1, 2, 2],
        }
        with patch(
            "src.utils.ocr.pytesseract.image_to_data",
            return_value=fake_ocr_data,
        ):
            result = await extract_text_with_coordinates(pdf)
        lines = result["pages"][0]["lines"]
        assert len(lines) == 2

    @pytest.mark.asyncio
    async def test_ocr_skips_empty_text_entries(self) -> None:
        """Tesseract often returns empty strings between words; the OCR
        branch skips ``if text.strip()``."""
        pdf = _make_image_only_pdf()
        fake_ocr_data = {
            "text": ["", "  ", "Word"],
            "conf": ["-1", "-1", "90"],
            "left": [0, 0, 10],
            "top": [0, 0, 10],
            "width": [0, 0, 40],
            "height": [0, 0, 15],
            "line_num": [0, 0, 1],
        }
        with patch(
            "src.utils.ocr.pytesseract.image_to_data",
            return_value=fake_ocr_data,
        ):
            result = await extract_text_with_coordinates(pdf)
        words = result["pages"][0]["words"]
        assert len(words) == 1
        assert words[0]["text"] == "Word"


# ---------------------------------------------------------------------------
# get_text_summary
# ---------------------------------------------------------------------------


class TestGetTextSummary:
    def test_no_text(self) -> None:
        assert get_text_summary({"full_text": "", "pages": []}) == "No text extracted from document"

    def test_short_doc(self) -> None:
        text = "Just a few words here"
        summary = get_text_summary({"full_text": text, "pages": [{}]})
        assert "Short document" in summary
        assert "5 words" in summary
        assert "1 page" in summary

    def test_long_doc_preview(self) -> None:
        text = " ".join(["word"] * 100)
        summary = get_text_summary({"full_text": text, "pages": [{}, {}]})
        assert "100 words" in summary
        assert "2 pages" in summary
        # Preview present (first chunk of text)
        assert "word" in summary
