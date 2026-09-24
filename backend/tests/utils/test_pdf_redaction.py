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

    def test_empty_redactions_list_keeps_page_text(self) -> None:
        pdf_bytes = _make_simple_pdf()
        out = apply_redactions_to_pdf(pdf_bytes, [])
        assert isinstance(out, bytes)
        doc = fitz.open(stream=out, filetype="pdf")
        # Text should still be present since no redactions applied
        assert "Hello" in doc[0].get_text()
        doc.close()

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


# ---------------------------------------------------------------------------
# Safety: validation, rotation, sanitisation, verification (DOC-02/04/05/07)
# ---------------------------------------------------------------------------

SECRET = "SECRETSIN123456789"


def _secret_pdf(rotation: int = 0) -> tuple[bytes, fitz.Rect]:
    """One page with SECRET on it. Returns the bytes and SECRET's box in
    displayed (viewer) space, i.e. after /Rotate is applied."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), f"Name: {SECRET} end", fontsize=12)
    page.insert_text((72, 300), "public text here", fontsize=12)
    unrotated = page.search_for(SECRET)[0]
    page.set_rotation(rotation)
    displayed = unrotated * page.rotation_matrix
    data = doc.tobytes()
    doc.close()
    return data, fitz.Rect(displayed)


def _box(rect: fitz.Rect, page: int = 1, **extra) -> dict:
    return {
        "page": page,
        "x": rect.x0,
        "y": rect.y0,
        "width": rect.width,
        "height": rect.height,
        **extra,
    }


def _all_text(pdf: bytes) -> str:
    doc = fitz.open(stream=pdf, filetype="pdf")
    try:
        return "".join(p.get_text() for p in doc)
    finally:
        doc.close()


class TestRedactionValidation:
    @pytest.mark.parametrize(
        "bad",
        [
            {"page": 1},  # no geometry at all (old bulk/AI records)
            {"page": 1, "x": 72, "y": 80, "width": 0, "height": 0},  # zero-area
            {"page": 1, "x": 72, "y": 80, "width": -50, "height": 20},
            {"page": 1, "x": 72, "y": 80, "width": float("nan"), "height": 20},
            {"page": 1, "x": 72, "y": 80, "width": float("inf"), "height": 20},
            {"page": 0, "x": 72, "y": 80, "width": 50, "height": 20},
            {"page": 5, "x": 72, "y": 80, "width": 50, "height": 20},
            {"page": 1, "x": 600, "y": 80, "width": 50, "height": 20},  # off the right edge
            {"page": 1, "x": 72, "y": -30, "width": 50, "height": 20},
            {"page": 1.5, "x": 72, "y": 80, "width": 50, "height": 20},
            {"page": 1, "x": "abc", "y": 80, "width": 50, "height": 20},
        ],
    )
    def test_invalid_redaction_raises_instead_of_skipping(self, bad: dict) -> None:
        from src.utils.redaction_records import RedactionValidationError

        pdf, _ = _secret_pdf()
        with pytest.raises(RedactionValidationError):
            apply_redactions_to_pdf(pdf, [bad])

    def test_nested_coordinates_shape_is_rejected(self) -> None:
        """The AI-suggestion shape keeps geometry under ``coordinates``.
        Passed straight through it must fail, never burn a 0x0 box."""
        from src.utils.redaction_records import RedactionValidationError

        pdf, rect = _secret_pdf()
        nested = {
            "page": 1,
            "coordinates": {"x": rect.x0, "y": rect.y0, "width": rect.width, "height": 14},
        }
        with pytest.raises(RedactionValidationError):
            apply_redactions_to_pdf(pdf, [nested])

    def test_page_limit_enforced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.utils import pdf_limits

        monkeypatch.setattr(pdf_limits, "MAX_PDF_PAGES", 1)
        with pytest.raises(pdf_limits.PdfLimitExceeded):
            apply_redactions_to_pdf(_make_two_page_pdf(), [])


class TestRotatedPages:
    @pytest.mark.parametrize("rotation", [0, 90, 180, 270])
    def test_displayed_space_box_removes_text(self, rotation: int) -> None:
        pdf, displayed = _secret_pdf(rotation)
        box = _box(displayed, coord_space="displayed", page_rotation=rotation)
        out = apply_redactions_to_pdf(pdf, [box])
        text = _all_text(out)
        assert SECRET not in text
        assert "public text here" in text
        doc = fitz.open(stream=out, filetype="pdf")
        assert doc[0].rotation == rotation
        doc.close()

    def test_legacy_record_on_unrotated_page_is_applied_as_is(self) -> None:
        pdf, displayed = _secret_pdf(0)
        assert SECRET not in _all_text(apply_redactions_to_pdf(pdf, [_box(displayed)]))

    @pytest.mark.parametrize("rotation", [90, 180, 270])
    def test_legacy_record_on_rotated_page_is_refused(self, rotation: int) -> None:
        """No marker: the box may be in either space, so it is not burned."""
        from src.utils.redaction_records import RedactionValidationError

        pdf, displayed = _secret_pdf(rotation)
        with pytest.raises(RedactionValidationError, match="older version"):
            apply_redactions_to_pdf(pdf, [_box(displayed)])

    def test_rotation_mismatch_is_refused(self) -> None:
        from src.utils.redaction_records import RedactionValidationError

        pdf, displayed = _secret_pdf(90)
        box = _box(displayed, coord_space="displayed", page_rotation=0)
        with pytest.raises(RedactionValidationError, match="now rotated 90"):
            apply_redactions_to_pdf(pdf, [box])

    def test_unknown_coordinate_space_is_refused(self) -> None:
        from src.utils.redaction_records import RedactionValidationError

        pdf, displayed = _secret_pdf(0)
        with pytest.raises(RedactionValidationError, match="coordinate space"):
            apply_redactions_to_pdf(pdf, [_box(displayed, coord_space="unrotated")])

    @pytest.mark.parametrize("rotation", [90, 270])
    def test_misplaced_text_box_fails_verification(self, rotation: int) -> None:
        """C1 reproduction: an unrotated box treated as displayed space burns
        the wrong area. The character check only looks inside that area, so
        the whole-page text check must catch the surviving string."""
        from src.utils.pdf_redaction import RedactionVerificationError

        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 100), f"Name: {SECRET} end", fontsize=12)
        unrotated = page.search_for(SECRET)[0]
        page.set_rotation(rotation)
        pdf = doc.tobytes()
        doc.close()

        wrong = _box(unrotated, text=SECRET, coord_space="displayed", page_rotation=rotation)
        with pytest.raises(RedactionVerificationError, match="still extractable"):
            apply_redactions_to_pdf(pdf, [wrong])


class TestSanitisation:
    def _rich_pdf(self) -> bytes:
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 100), "visible body", fontsize=12)
        doc.set_metadata(
            {"author": SECRET, "title": "Title " + SECRET, "subject": SECRET, "keywords": SECRET}
        )
        doc.set_xml_metadata(
            f"<x:xmpmeta xmlns:x='adobe:ns:meta/'><dc>{SECRET}-xmp</dc></x:xmpmeta>"
        )
        doc.embfile_add("leak.txt", (SECRET + "-embedded").encode())
        doc.set_toc([[1, "Chapter " + SECRET, 1]])
        page.add_text_annot((300, 100), "note " + SECRET)
        widget = fitz.Widget()
        widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        widget.field_name = "f1"
        widget.field_value = "w " + SECRET
        widget.rect = fitz.Rect(72, 200, 300, 220)
        page.add_widget(widget)
        catalog = doc.pdf_catalog()
        js = doc.get_new_xref()
        doc.update_object(js, f"<</S/JavaScript/JS(app.alert('{SECRET}'))>>")
        doc.xref_set_key(catalog, "OpenAction", f"{js} 0 R")
        data = doc.tobytes()
        doc.close()
        return data

    @pytest.mark.parametrize("with_redaction", [False, True])
    def test_release_output_carries_no_hidden_parts(self, with_redaction: bool) -> None:
        pdf = self._rich_pdf()
        redactions = (
            [{"page": 1, "x": 400, "y": 400, "width": 50, "height": 20}] if with_redaction else []
        )
        out = apply_redactions_to_pdf(pdf, redactions)

        doc = fitz.open(stream=out, filetype="pdf")
        try:
            assert not {k: v for k, v in doc.metadata.items() if v and k != "format"}
            assert not doc.get_xml_metadata()
            assert doc.embfile_count() == 0
            assert doc.get_toc() == []
            assert doc[0].first_annot is None
            assert doc[0].first_widget is None
            catalog = doc.pdf_catalog()
            for key in ("OpenAction", "AcroForm", "Names", "Outlines"):
                assert doc.xref_get_key(catalog, key)[0] == "null"
            assert "visible body" in doc[0].get_text()
        finally:
            doc.close()
        # Nothing left in any object or stream either.
        assert SECRET.encode() not in out
        check = fitz.open(stream=out, filetype="pdf")
        for xref in range(1, check.xref_length()):
            assert SECRET not in check.xref_object(xref)
            if check.xref_is_stream(xref):
                assert SECRET.encode() not in (check.xref_stream(xref) or b"")
        check.close()


class TestVerification:
    def test_apply_redactions_called_with_image_blanking(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[dict] = []
        original = fitz.Page.apply_redactions

        def spy(self, *args, **kwargs):
            calls.append(kwargs)
            return original(self, *args, **kwargs)

        monkeypatch.setattr(fitz.Page, "apply_redactions", spy)
        pdf, rect = _secret_pdf()
        apply_redactions_to_pdf(pdf, [_box(rect)])
        assert calls
        assert calls[0]["images"] == fitz.PDF_REDACT_IMAGE_PIXELS
        assert calls[0]["text"] == fitz.PDF_REDACT_TEXT_REMOVE

    def test_output_that_still_has_text_fails_verification(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If burning silently does nothing, the release must fail."""
        from src.utils.pdf_redaction import RedactionVerificationError

        def fake_apply(self, *args, **kwargs):
            for annot in list(self.annots()):
                self.delete_annot(annot)
            return True

        monkeypatch.setattr(fitz.Page, "apply_redactions", fake_apply)
        pdf, rect = _secret_pdf()
        with pytest.raises(RedactionVerificationError, match="remain under redaction"):
            apply_redactions_to_pdf(pdf, [_box(rect, id="r1")])

    def test_page_scope_text_redaction_must_remove_every_occurrence(self) -> None:
        """Bulk text redactions promise every occurrence on the page. If a
        second occurrence is left, verification fails."""
        from src.utils.pdf_redaction import RedactionVerificationError

        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 100), SECRET, fontsize=12)
        page.insert_text((72, 400), SECRET, fontsize=12)
        first = page.search_for(SECRET)[0]
        pdf = doc.tobytes()
        doc.close()

        with pytest.raises(RedactionVerificationError, match="still extractable"):
            apply_redactions_to_pdf(pdf, [_box(first, text=SECRET, source="bulk_text")])

        # Any text-based redaction is checked against the whole page (C1),
        # so a manual box carrying the text fails the same way.
        with pytest.raises(RedactionVerificationError, match="still extractable"):
            apply_redactions_to_pdf(pdf, [_box(first, text=SECRET, source="manual")])

        # A box without text is only checked inside the box.
        out = apply_redactions_to_pdf(pdf, [_box(first, source="manual")])
        assert _all_text(out).count(SECRET) == 1

    def test_manual_text_check_matches_whole_words(self) -> None:
        """A manual redaction of "Ann" must not fail because "Annual" stays."""
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 100), "Ann", fontsize=12)
        page.insert_text((72, 400), "Annual report", fontsize=12)
        first = page.search_for("Ann")[0]
        pdf = doc.tobytes()
        doc.close()

        out = apply_redactions_to_pdf(pdf, [_box(first, text="Ann", source="manual")])
        assert "Annual report" in _all_text(out)

    def test_image_pixels_under_box_are_blanked(self) -> None:
        doc = fitz.open()
        page = doc.new_page(width=200, height=200)
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200), False)
        pix.set_rect(pix.irect, (255, 0, 0))
        page.insert_image(page.rect, pixmap=pix)
        pdf = doc.tobytes()
        doc.close()

        out = apply_redactions_to_pdf(
            pdf, [{"page": 1, "x": 50, "y": 50, "width": 100, "height": 100}]
        )
        result = fitz.open(stream=out, filetype="pdf")
        xref = result[0].get_images()[0][0]
        image = fitz.Pixmap(result, xref)
        assert image.pixel(100, 100) != (255, 0, 0)  # under the box: gone
        assert image.pixel(10, 10) == (255, 0, 0)  # outside: kept
        result.close()
