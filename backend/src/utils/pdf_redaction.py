"""
PDF Redaction Application
Permanently applies redactions to PDFs for export and release packages.

Pipeline (``apply_redactions_to_pdf``):

1. Validate every redaction against the real document (DOC-02, DOC-07): a
   page that exists, a finite positive-area box inside the page. Any bad
   record raises; nothing is skipped.
2. Convert each box from displayed (viewer) space to PyMuPDF's unrotated
   page space with ``page.derotation_matrix`` (DOC-04).
3. Burn the boxes with ``page.apply_redactions`` removing text and blanking
   image pixels under each box.
4. Sanitise the whole document (DOC-05): metadata, XMP, embedded files,
   outline, annotations, form fields, links, JavaScript and open actions.
   This also runs when there are no redactions.
5. Save with garbage collection so replaced objects are not carried over.
6. Re-open the output and verify it (DOC-07): no characters left under any
   box, text-based redaction strings gone, and the sanitised parts empty.
   A failed check raises RedactionVerificationError.
"""

from __future__ import annotations

import io
import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import fitz  # PyMuPDF

from src.utils.pdf_limits import PdfLimitExceeded, check_page_count
from src.utils.redaction_records import (
    RedactionValidationError,
    validate_redaction,
)

logger = logging.getLogger(__name__)

# Redactions created from a text search mark every occurrence on the page,
# so after burning the string must not appear anywhere on that page.
PAGE_SCOPE_SOURCES = frozenset({"bulk_text", "ai_bulk_apply"})

# Image handling for apply_redactions: blank the pixels under the box.
# PDF_REDACT_IMAGE_REMOVE would delete a whole scanned page image for a
# one-word box; PIXELS removes exactly the covered image content.
REDACT_IMAGES_MODE = fitz.PDF_REDACT_IMAGE_PIXELS
REDACT_TEXT_MODE = fitz.PDF_REDACT_TEXT_REMOVE

# Catalog and page keys that can carry actions or hidden content.
_CATALOG_KEYS_TO_DROP = ("OpenAction", "AA", "AcroForm", "Names", "Outlines", "Metadata")
_PAGE_KEYS_TO_DROP = ("AA", "Metadata", "PieceInfo", "Thumb")


class RedactionError(Exception):
    """Redactions could not be applied safely; the document must not ship."""


class RedactionVerificationError(RedactionError):
    """The redacted output still contains content that should be gone."""


@dataclass(frozen=True)
class _Box:
    page_index: int
    rect: fitz.Rect  # unrotated PyMuPDF page space
    label: str
    text: str | None
    page_scope: bool


def _normalise_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _prepare_boxes(doc: fitz.Document, redactions: list[dict[str, Any]]) -> list[_Box]:
    page_sizes = [(page.rect.width, page.rect.height) for page in doc]
    boxes: list[_Box] = []
    for index, redaction in enumerate(redactions):
        label = str(redaction.get("id") or f"#{index}")
        try:
            geometry = validate_redaction(redaction, page_sizes)
        except RedactionValidationError as exc:
            raise RedactionValidationError(f"redaction {label}: {exc}") from exc

        page = doc[geometry.page - 1]
        displayed = fitz.Rect(
            geometry.x,
            geometry.y,
            geometry.x + geometry.width,
            geometry.y + geometry.height,
        ) & fitz.Rect(page.rect)
        if displayed.is_empty:
            raise RedactionValidationError(f"redaction {label}: box has no area on the page")
        unrotated = fitz.Rect(displayed * page.derotation_matrix)
        unrotated.normalize()

        text = redaction.get("text")
        text = text if isinstance(text, str) and text.strip() else None
        boxes.append(
            _Box(
                page_index=geometry.page - 1,
                rect=unrotated,
                label=label,
                text=text,
                page_scope=redaction.get("source") in PAGE_SCOPE_SOURCES,
            )
        )
    return boxes


def sanitize_pdf_document(doc: fitz.Document) -> None:
    """Strip everything a released PDF must not carry besides page content."""
    for page in doc:
        annot = page.first_annot
        while annot:
            annot = page.delete_annot(annot)
        widget = page.first_widget
        while widget:
            widget = page.delete_widget(widget)
        for link in page.get_links():
            page.delete_link(link)

    doc.scrub(
        attached_files=True,
        clean_pages=True,
        embedded_files=True,
        hidden_text=False,  # keep OCR text layers of visible content
        javascript=True,
        metadata=True,
        redactions=False,  # already applied
        redact_images=0,
        remove_links=True,
        reset_fields=True,
        reset_responses=True,
        thumbnails=True,
        xml_metadata=True,
    )

    for name in list(doc.embfile_names()):
        doc.embfile_del(name)
    doc.set_toc([])
    doc.set_metadata({})
    doc.del_xml_metadata()

    catalog = doc.pdf_catalog()
    for key in _CATALOG_KEYS_TO_DROP:
        if doc.xref_get_key(catalog, key)[0] != "null":
            doc.xref_set_key(catalog, key, "null")
    for page in doc:
        for key in _PAGE_KEYS_TO_DROP:
            if doc.xref_get_key(page.xref, key)[0] != "null":
                doc.xref_set_key(page.xref, key, "null")

    info = doc.xref_get_key(-1, "Info")
    if info[0] == "xref":
        doc.xref_set_key(-1, "Info", "null")


def _burn(doc: fitz.Document, boxes: list[_Box]) -> None:
    by_page: dict[int, list[_Box]] = defaultdict(list)
    for box in boxes:
        by_page[box.page_index].append(box)

    for page_index, page_boxes in sorted(by_page.items()):
        page = doc[page_index]
        for box in page_boxes:
            page.add_redact_annot(box.rect, fill=(0, 0, 0))
        applied = page.apply_redactions(images=REDACT_IMAGES_MODE, text=REDACT_TEXT_MODE)
        if not applied:
            raise RedactionError(f"PyMuPDF applied no redactions on page {page_index + 1}")


def _verify_sanitised(doc: fitz.Document) -> list[str]:
    problems = []
    meta = {
        k: v for k, v in (doc.metadata or {}).items() if v and k not in ("format", "encryption")
    }
    if meta:
        problems.append(f"metadata not cleared: {sorted(meta)}")
    if doc.get_xml_metadata():
        problems.append("XMP metadata not cleared")
    if doc.embfile_count():
        problems.append("embedded files remain")
    if doc.get_toc():
        problems.append("outline/bookmarks remain")
    for page in doc:
        if page.first_annot or page.first_widget:
            problems.append(f"annotations or form fields remain on page {page.number + 1}")
    return problems


def verify_redacted_pdf(pdf_content: bytes, boxes: list[_Box]) -> None:
    """Re-open burned output and fail if any redacted content survives."""
    doc = fitz.open(stream=pdf_content, filetype="pdf")
    try:
        problems = _verify_sanitised(doc)

        by_page: dict[int, list[_Box]] = defaultdict(list)
        for box in boxes:
            by_page[box.page_index].append(box)

        for page_index, page_boxes in sorted(by_page.items()):
            page = doc[page_index]
            raw = page.get_text("rawdict")
            leftover: dict[str, int] = defaultdict(int)
            for block in raw.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        for char in span.get("chars", []):
                            if not char.get("c", "").strip():
                                continue
                            x0, y0, x1, y1 = char["bbox"]
                            centre = fitz.Point((x0 + x1) / 2, (y0 + y1) / 2)
                            for box in page_boxes:
                                if centre in box.rect:
                                    leftover[box.label] += 1
            for label, count in leftover.items():
                problems.append(
                    f"page {page_index + 1}: {count} characters remain under redaction {label}"
                )

            page_text = _normalise_text(page.get_text())
            for box in page_boxes:
                if not box.text:
                    continue
                needle = _normalise_text(box.text)
                if box.page_scope:
                    haystack = page_text
                else:
                    haystack = _normalise_text(page.get_text(clip=box.rect))
                if needle and needle in haystack:
                    problems.append(
                        f"page {page_index + 1}: redacted text of {box.label} is still extractable"
                    )
    finally:
        doc.close()

    if problems:
        raise RedactionVerificationError("; ".join(problems))


def apply_redactions_to_pdf(pdf_content: bytes, redactions: list[dict]) -> bytes:
    """
    Burn ``redactions`` into ``pdf_content``, sanitise, save and verify.

    Callers decide which redactions to pass (see
    ``src.utils.redaction_records.partition_redactions``). An empty list
    still sanitises the document.

    Raises:
        RedactionValidationError: a redaction is malformed or off the page.
        PdfLimitExceeded: the document has too many pages.
        RedactionVerificationError: the output failed verification.
        RedactionError: the PDF could not be opened or processed.
    """
    try:
        doc = fitz.open(stream=pdf_content, filetype="pdf")
    except Exception as exc:
        raise RedactionError(f"Failed to apply redactions: not a readable PDF ({exc})") from exc

    try:
        if doc.needs_pass:
            raise RedactionError("Failed to apply redactions: PDF is password protected")
        check_page_count(doc.page_count)
        boxes = _prepare_boxes(doc, list(redactions or []))
        _burn(doc, boxes)
        sanitize_pdf_document(doc)

        output = io.BytesIO()
        doc.save(output, garbage=4, deflate=True, clean=True)
        redacted_pdf = output.getvalue()
    except (RedactionError, RedactionValidationError, PdfLimitExceeded):
        raise
    except Exception as exc:
        logger.error("Error applying redactions to PDF: %s", exc)
        raise RedactionError(f"Failed to apply redactions: {exc}") from exc
    finally:
        doc.close()

    verify_redacted_pdf(redacted_pdf, boxes)
    logger.info("Applied and verified %d redactions", len(boxes))
    return redacted_pdf


def sanitize_pdf(pdf_content: bytes) -> bytes:
    """Sanitise a PDF that has no redactions (same pipeline, empty list)."""
    return apply_redactions_to_pdf(pdf_content, [])


def create_redacted_copy(
    pdf_content: bytes, redactions: list[dict], watermark: str | None = None
) -> bytes:
    """
    Create a redacted copy of a PDF with optional watermark.

    Args:
        pdf_content: Original PDF content
        redactions: List of redactions to apply
        watermark: Optional watermark text (e.g., "REDACTED COPY")

    Returns:
        Redacted PDF with watermark
    """
    # Apply redactions
    redacted_pdf = apply_redactions_to_pdf(pdf_content, redactions)

    # Add watermark if specified
    if watermark:
        doc = fitz.open(stream=redacted_pdf, filetype="pdf")

        for page in doc:
            # Add watermark to each page
            text_rect = page.rect
            # Phase 4 Batch 4.4 (audit B50): PyMuPDF's `insert_textbox`
            # rejects rotations that are not multiples of 90. The prior
            # `rotate=45` raised `ValueError("rotate must be multiple of
            # 90")` — the watermark code path was broken on first use.
            # `rotate=0` gives a horizontal banner; switching to 90 is
            # a one-character change if a diagonal look is required.
            page.insert_textbox(
                text_rect,
                watermark,
                fontsize=40,
                color=(0.7, 0.7, 0.7),
                align=fitz.TEXT_ALIGN_CENTER,
                rotate=0,
                overlay=True,
            )

        output = io.BytesIO()
        doc.save(output, garbage=4, deflate=True, clean=True)
        doc.close()

        redacted_pdf = output.getvalue()
        output.close()

    return redacted_pdf


def validate_redactions(redactions: list[dict]) -> bool:
    """
    Validate that redactions have required fields.

    Args:
        redactions: List of redaction dictionaries

    Returns:
        True if valid, raises exception if invalid
    """
    required_fields = ["page", "x", "y", "width", "height"]

    for i, redaction in enumerate(redactions):
        for field in required_fields:
            if field not in redaction:
                raise ValueError(f"Redaction {i} missing required field: {field}")

        # Validate numeric values
        for field in required_fields:
            if not isinstance(redaction[field], (int, float)):
                raise ValueError(f"Redaction {i} field '{field}' must be numeric")

    return True
