"""
Resource limits for PDF parsing, rendering and OCR (DOC-09).

Every PyMuPDF/Tesseract entry point that handles uploaded documents checks
these before doing expensive work, so a single hostile or oversized file
cannot exhaust memory or hold a worker for minutes.

Values are read from the environment once at import time:

- ``BLACKBAR_MAX_PDF_PAGES`` (default 2000): documents with more pages are
  refused.
- ``BLACKBAR_MAX_RENDER_PIXELS`` (default 50,000,000): the largest raster
  (width x height) OCR may render for one page. The render DPI is lowered to
  fit; a page that does not fit even at the minimum DPI is refused.
- ``BLACKBAR_OCR_PAGE_TIMEOUT`` (default 120 seconds): Tesseract time budget
  per page.
"""

from __future__ import annotations

import math
import os

from PIL import Image


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


MAX_PDF_PAGES = _env_int("BLACKBAR_MAX_PDF_PAGES", 2000)
MAX_RENDER_PIXELS = _env_int("BLACKBAR_MAX_RENDER_PIXELS", 50_000_000)
OCR_PAGE_TIMEOUT_SECONDS = _env_int("BLACKBAR_OCR_PAGE_TIMEOUT", 120)

OCR_DPI = 300
MIN_OCR_DPI = 72

# Pillow refuses (DecompressionBombError) any image above twice this value
# and warns above it. Set it explicitly instead of relying on the library
# default, and tie it to the render budget so both limits agree.
Image.MAX_IMAGE_PIXELS = MAX_RENDER_PIXELS


class PdfLimitExceeded(ValueError):
    """A document exceeds a configured processing limit."""


def check_page_count(page_count: int, max_pages: int | None = None) -> None:
    """Raise PdfLimitExceeded when ``page_count`` is above the page limit."""
    limit = MAX_PDF_PAGES if max_pages is None else max_pages
    if page_count > limit:
        raise PdfLimitExceeded(
            f"Document has {page_count} pages; the limit is {limit} pages per document."
        )


def render_dpi_for_page(
    width_pt: float,
    height_pt: float,
    target_dpi: int = OCR_DPI,
    max_pixels: int | None = None,
) -> int:
    """DPI to render a page at so the raster stays within the pixel budget.

    Returns ``target_dpi`` when it fits, otherwise the largest DPI that does.
    Raises PdfLimitExceeded when the page does not fit even at MIN_OCR_DPI.
    """
    budget = MAX_RENDER_PIXELS if max_pixels is None else max_pixels
    area_sq_in = (max(width_pt, 0.0) / 72.0) * (max(height_pt, 0.0) / 72.0)
    if area_sq_in <= 0:
        return target_dpi
    if area_sq_in * target_dpi * target_dpi <= budget:
        return target_dpi
    dpi = int(math.floor(math.sqrt(budget / area_sq_in)))
    if dpi < MIN_OCR_DPI:
        raise PdfLimitExceeded(
            f"Page of {width_pt:.0f}x{height_pt:.0f} pt is too large to render for OCR."
        )
    return dpi
