"""
Document-side helpers for placing redactions: load a document's PDF and
check redaction boxes against its real pages before they are stored
(DOC-02, DOC-07).

Page sizes are cached on the document as ``page_dims`` (``[[w, h], ...]`` in
displayed-space points) the first time they are needed. The stored PDF does
not change after upload, and the release path re-validates against the PDF
itself, so a stale cache can only cause a refusal, never a leak.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import fitz  # PyMuPDF
from bson import ObjectId
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorGridFSBucket

from src.utils.pdf_limits import PdfLimitExceeded, check_page_count
from src.utils.redaction_records import (
    RedactionGeometry,
    RedactionValidationError,
    validate_redaction,
)

logger = logging.getLogger(__name__)


def _gridfs_id(value: Any) -> Any:
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    return value


async def load_document_pdf(doc: dict[str, Any], db: Any) -> bytes | None:
    """Return the document's PDF bytes (GridFS first, legacy ``content`` second)."""
    file_id = doc.get("content_file_id")
    if file_id:
        try:
            bucket = AsyncIOMotorGridFSBucket(db)
            stream = await bucket.open_download_stream(_gridfs_id(file_id))
            return await stream.read()
        except Exception as exc:
            logger.warning("GridFS read failed for document %s: %s", doc.get("id"), exc)
    content = doc.get("content")
    return bytes(content) if content else None


def page_sizes_from_pdf(pdf_content: bytes) -> list[list[float]]:
    """``[[width, height], ...]`` of every page in displayed space."""
    doc = fitz.open(stream=pdf_content, filetype="pdf")
    try:
        check_page_count(doc.page_count)
        return [[float(p.rect.width), float(p.rect.height)] for p in doc]
    finally:
        doc.close()


def _valid_cached_sizes(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) > 0
        and all(
            isinstance(s, list | tuple)
            and len(s) >= 2
            and all(isinstance(v, int | float) and v > 0 for v in s[:2])
            for s in value
        )
    )


def assert_not_conversion_failed(doc: dict[str, Any]) -> None:
    if doc.get("conversion_failed") or doc.get("status") == "conversion_failed":
        raise HTTPException(
            status_code=409,
            detail="Document failed conversion to PDF; it cannot be redacted or released.",
        )


async def get_page_sizes(doc: dict[str, Any], db: Any) -> list[list[float]]:
    """Page sizes for ``doc``; raises 409/413 when they cannot be known."""
    assert_not_conversion_failed(doc)
    cached = doc.get("page_dims")
    if cached is not None and _valid_cached_sizes(cached):
        return [[float(s[0]), float(s[1])] for s in cached]

    pdf = await load_document_pdf(doc, db)
    if not pdf:
        raise HTTPException(
            status_code=409,
            detail="Document content is not available, so redactions cannot be placed on it.",
        )
    try:
        sizes = await asyncio.to_thread(page_sizes_from_pdf, pdf)
    except PdfLimitExceeded as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=409, detail="Document content is not a readable PDF."
        ) from exc

    await db.documents.update_one({"id": doc["id"]}, {"$set": {"page_dims": sizes}})
    return sizes


def validate_or_422(data: dict[str, Any], page_sizes: list[list[float]]) -> RedactionGeometry:
    """Validate one redaction box; HTTP 422 with the reason when invalid."""
    try:
        return validate_redaction(data, page_sizes)
    except RedactionValidationError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid redaction: {exc}") from exc
