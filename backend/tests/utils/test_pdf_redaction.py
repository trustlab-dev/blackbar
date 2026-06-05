"""Tests for ``src.utils.pdf_redaction``.

Applies black-box redactions to PDFs using PyMuPDF. Tests build small
PDFs in-memory and verify both the bytes round-trip and the redacted
output renders without crashing.
"""

from __future__ import annotations

import io

import fitz  # PyMuPDF
import pytest

from src.utils.pdf_redaction import (
    apply_redactions_to_pdf,
    create_redacted_copy,
    validate_redactions,
)


def _make_simple_pdf(text: str = "Hello, world!") -> bytes:
    """Build a tiny one-page PDF with a single string of text."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    page.insert_text((50, 100), text, fontsize=12)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def _make_two_page_pdf() -> bytes:
    doc = fitz.open()
    p1 = doc.new_page(width=400, height=400)
    p1.insert_text((50, 100), "Page one secret data", fontsize=12)
    p2 = doc.new_page(width=400, height=400)
    p2.insert_text((50, 100), "Page two secret data", fontsize=12)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# validate_redactions
# ---------------------------------------------------------------------------


class TestValidateRedactions:
    def test_valid_redactions_return_true(self) -> None:
        ok = validate_redactions([{"page": 1, "x": 10, "y": 20, "width": 30, "height": 40}])
        assert ok is True

    def test_empty_list_returns_true(self) -> None:
        assert validate_redactions([]) is True

    def test_missing_field_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="missing required field: width"):
            validate_redactions([{"page": 1, "x": 10, "y": 20, "height": 40}])

    @pytest.mark.parametrize("field", ["page", "x", "y", "width", "height"])
    def test_each_required_field_raises(self, field: str) -> None:
        red = {"page": 1, "x": 10, "y": 20, "width": 30, "height": 40}
        del red[field]
        with pytest.raises(ValueError, match=f"missing required field: {field}"):
            validate_redactions([red])

    def test_non_numeric_field_raises(self) -> None:
        with pytest.raises(ValueError, match="must be numeric"):
            validate_redactions(
                [{"page": 1, "x": "not-a-number", "y": 20, "width": 30, "height": 40}]
            )

    def test_float_values_accepted(self) -> None:
        ok = validate_redactions([{"page": 1, "x": 10.5, "y": 20.7, "width": 30.0, "height": 40.0}])
        assert ok is True


# ---------------------------------------------------------------------------
# apply_redactions_to_pdf
# ---------------------------------------------------------------------------


class TestApplyRedactionsToPdf:
    def test_redacts_single_box_first_page(self) -> None:
        pdf_bytes = _make_simple_pdf("Original secret text")
        redactions = [{"page": 1, "x": 50, "y": 90, "width": 300, "height": 20}]
        out = apply_redactions_to_pdf(pdf_bytes, redactions)
        assert isinstance(out, bytes)
        # Verify the output is a valid PDF
        doc = fitz.open(stream=out, filetype="pdf")
        # Text under the redaction box should be gone
        page_text = doc[0].get_text()
        assert "secret" not in page_text.lower()
        doc.close()

    def test_handles_multiple_pages(self) -> None:
        pdf_bytes = _make_two_page_pdf()
        redactions = [
            {"page": 1, "x": 50, "y": 90, "width": 300, "height": 20},
            {"page": 2, "x": 50, "y": 90, "width": 300, "height": 20},
        ]
        out = apply_redactions_to_pdf(pdf_bytes, redactions)
        doc = fitz.open(stream=out, filetype="pdf")
        assert len(doc) == 2
        for p in doc:
            assert "secret" not in p.get_text().lower()
        doc.close()

    def test_skips_out_of_range_page(self) -> None:
        """A redaction on a page that doesn't exist is silently skipped
        with a warning, NOT an exception."""
        pdf_bytes = _make_simple_pdf()
        redactions = [
            {"page": 99, "x": 0, "y": 0, "width": 10, "height": 10},
        ]
        out = apply_redactions_to_pdf(pdf_bytes, redactions)
        assert isinstance(out, bytes)
        # PDF still opens cleanly
        doc = fitz.open(stream=out, filetype="pdf")
        assert len(doc) == 1
        doc.close()

    def test_empty_redactions_list_returns_unchanged_bytes(self) -> None:
        pdf_bytes = _make_simple_pdf()
        out = apply_redactions_to_pdf(pdf_bytes, [])
        assert isinstance(out, bytes)
        doc = fitz.open(stream=out, filetype="pdf")
        # Text should still be present since no redactions applied
        assert "Hello" in doc[0].get_text()
        doc.close()

    def test_redaction_uses_defaults_for_missing_dims(self) -> None:
        """The function calls ``.get(field, 0)`` for x/y/width/height so a
        zero-size box doesn't crash — it just does nothing visible."""
        pdf_bytes = _make_simple_pdf()
        out = apply_redactions_to_pdf(pdf_bytes, [{"page": 1}])
        assert isinstance(out, bytes)

    def test_invalid_pdf_raises_wrapped_exception(self) -> None:
        with pytest.raises(Exception, match="Failed to apply redactions"):
            apply_redactions_to_pdf(b"not a pdf at all", [])


# ---------------------------------------------------------------------------
# create_redacted_copy
# ---------------------------------------------------------------------------


class TestCreateRedactedCopy:
    def test_returns_bytes_without_watermark(self) -> None:
        pdf_bytes = _make_simple_pdf()
        out = create_redacted_copy(
            pdf_bytes,
            [{"page": 1, "x": 50, "y": 90, "width": 100, "height": 20}],
        )
        assert isinstance(out, bytes)
        # Still a valid PDF
        doc = fitz.open(stream=out, filetype="pdf")
        assert len(doc) == 1
        doc.close()

    def test_watermark_branch_produces_valid_pdf(self) -> None:
        """Phase 4 Batch 4.4 (audit B50): ``create_redacted_copy`` with a
        non-None watermark used to call PyMuPDF's ``insert_textbox(...,
        rotate=45)``, which raised ``ValueError("rotate must be multiple
        of 90")``. Switched to ``rotate=0`` (horizontal banner). The
        watermark branch now produces a valid PDF.

        Test flipped from ``pytest.raises(ValueError)`` to assert a
        well-formed bytes PDF comes back."""
        pdf_bytes = _make_simple_pdf()
        out = create_redacted_copy(
            pdf_bytes,
            [{"page": 1, "x": 50, "y": 90, "width": 100, "height": 20}],
            watermark="REDACTED COPY",
        )
        assert isinstance(out, bytes)
        doc = fitz.open(stream=out, filetype="pdf")
        assert len(doc) == 1
        doc.close()

    def test_no_watermark_when_none_string(self) -> None:
        """``watermark=None`` skips the watermark branch."""
        pdf_bytes = _make_simple_pdf()
        out = create_redacted_copy(
            pdf_bytes,
            [],
            watermark=None,
        )
        assert isinstance(out, bytes)
