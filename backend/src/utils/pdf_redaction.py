"""
PDF Redaction Application
Permanently applies redactions to PDFs for release packages
"""

import io
import logging

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


def apply_redactions_to_pdf(pdf_content: bytes, redactions: list[dict]) -> bytes:
    """
    Apply redactions permanently to a PDF.

    Args:
        pdf_content: Binary PDF content
        redactions: List of redaction boxes with coordinates

    Returns:
        Binary content of redacted PDF
    """
    try:
        # Open PDF from bytes
        doc = fitz.open(stream=pdf_content, filetype="pdf")

        # Group redactions by page
        redactions_by_page = {}
        for redaction in redactions:
            page_num = redaction.get("page", 1) - 1  # Convert to 0-indexed
            if page_num not in redactions_by_page:
                redactions_by_page[page_num] = []
            redactions_by_page[page_num].append(redaction)

        # Apply redactions to each page
        for page_num, page_redactions in redactions_by_page.items():
            if page_num >= len(doc):
                logger.warning(f"Page {page_num + 1} not found in PDF, skipping redactions")
                continue

            page = doc[page_num]

            for redaction in page_redactions:
                # Create rectangle for redaction
                x = redaction.get("x", 0)
                y = redaction.get("y", 0)
                width = redaction.get("width", 0)
                height = redaction.get("height", 0)

                # PyMuPDF uses (x0, y0, x1, y1) format
                rect = fitz.Rect(x, y, x + width, y + height)

                # Add redaction annotation (black box)
                page.add_redact_annot(rect, fill=(0, 0, 0))

            # Apply all redactions on this page
            page.apply_redactions()

        # Save to bytes
        output = io.BytesIO()
        doc.save(output)
        doc.close()

        redacted_pdf = output.getvalue()
        output.close()

        logger.info(f"Applied {len(redactions)} redactions to PDF")
        return redacted_pdf

    except Exception as e:
        logger.error(f"Error applying redactions to PDF: {str(e)}")
        raise Exception(f"Failed to apply redactions: {str(e)}")


def create_redacted_copy(
    pdf_content: bytes, redactions: list[dict], watermark: str = None
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
        doc.save(output)
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
