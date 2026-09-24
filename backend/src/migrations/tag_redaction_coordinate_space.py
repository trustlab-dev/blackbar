"""
Migration: record the coordinate space of legacy redactions and text boxes (C1)

Older builds stored boxes in two spaces. Boxes drawn in the viewer were in
displayed space (after the page's /Rotate), while AI suggestion boxes and the
native-text word boxes in ``text_data`` were in unrotated PyMuPDF space. The
burn step now converts every record from displayed space, so a legacy box on a
rotated page could land in the wrong place.

What this does, per document with a readable PDF:

- Caches ``page_dims`` as ``[[width, height, rotation], ...]``.
- Redactions without ``coord_space`` on a page with rotation 0: both spaces
  are the same there, so they are tagged ``coord_space: "displayed"``,
  ``page_rotation: 0``.
- Redactions without ``coord_space`` on a rotated page: their space cannot be
  known, so they are left untagged. The release rule holds them back as
  ``legacy_rotated_coordinates`` until a reviewer checks them in the viewer
  and approves them (which stamps the marker) or deletes and re-adds them.
  They are listed in the output.
- ``text_data``: native-text boxes on rotated pages are rebuilt in displayed
  space from the PDF (OCR boxes already were), and ``text_data`` is tagged
  ``coord_space: "displayed"``.
- Cached AI suggestions need nothing: entries without the marker are
  re-located on the next view.

Idempotent. Writes are conditional on the redactions being unchanged since
they were read, so a concurrent edit is never overwritten (it is reported).

Run: ``python -m src.migrations.tag_redaction_coordinate_space``
"""

from __future__ import annotations

import asyncio
import copy
from typing import Any

import fitz  # PyMuPDF
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from src.config import MONGODB_URI
from src.documents.redaction_store import load_document_pdf
from src.utils.ocr import native_page_data
from src.utils.redaction_records import (
    RedactionValidationError,
    coordinate_space_fields,
    has_legacy_coordinates,
    normalise_rotation,
    parse_redaction_geometry,
)

DISPLAYED = "displayed"


def _pdf_facts(pdf: bytes) -> tuple[list[list[float]], dict[int, dict | None]]:
    """Page geometry and, for rotated pages, rebuilt native text data."""
    doc = fitz.open(stream=pdf, filetype="pdf")
    try:
        dims = [
            [float(p.rect.width), float(p.rect.height), normalise_rotation(p.rotation)] for p in doc
        ]
        rebuilt = {p.number + 1: native_page_data(p) for p in doc if p.rotation % 360}
        return dims, rebuilt
    finally:
        doc.close()


def _tag_redactions(redactions: list[dict], dims: list[list[float]]) -> tuple[int, list[dict]]:
    tagged = 0
    needs_review: list[dict] = []
    for redaction in redactions:
        if not has_legacy_coordinates(redaction):
            continue
        try:
            geometry = parse_redaction_geometry(redaction)
        except RedactionValidationError:
            continue  # no geometry: blocked as "no_geometry" by the release rule
        if not 1 <= geometry.page <= len(dims):
            continue
        rotation = normalise_rotation(dims[geometry.page - 1][2])
        if rotation == 0:
            redaction.update(coordinate_space_fields(0))
            tagged += 1
        elif str(redaction.get("status") or "").lower() != "rejected":
            needs_review.append(
                {"id": redaction.get("id"), "page": geometry.page, "rotation": rotation}
            )
    return tagged, needs_review


def _fix_text_data(text_data: Any, rebuilt: dict[int, dict | None]) -> bool:
    if not isinstance(text_data, dict) or text_data.get("coord_space") == DISPLAYED:
        return False
    for index, page in enumerate(text_data.get("pages") or []):
        fresh = rebuilt.get(page.get("page_num"))
        if fresh is not None:
            # Keep the stored text (it may have been truncated); replace boxes.
            fresh["text"] = page.get("text", fresh["text"])
            text_data["pages"][index] = fresh
    text_data["coord_space"] = DISPLAYED
    return True


async def tag_coordinate_space(db: AsyncIOMotorDatabase) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "documents": 0,
        "unreadable": 0,
        "redactions_tagged": 0,
        "text_data_fixed": 0,
        "concurrent_skipped": 0,
        "needs_review": [],
    }
    cursor = db.documents.find(
        {"conversion_failed": {"$ne": True}},
        {"id": 1, "content_file_id": 1, "content": 1, "redactions": 1, "text_data": 1},
    )
    async for doc in cursor:
        stats["documents"] += 1
        pdf = await load_document_pdf(doc, db)
        if not pdf:
            stats["unreadable"] += 1
            continue
        try:
            dims, rebuilt = await asyncio.to_thread(_pdf_facts, pdf)
        except Exception:
            stats["unreadable"] += 1
            continue

        original = doc.get("redactions") or []
        redactions = copy.deepcopy(original)
        tagged, review = _tag_redactions(redactions, dims)
        text_data = doc.get("text_data")
        text_fixed = _fix_text_data(text_data, rebuilt)

        update: dict[str, Any] = {"page_dims": dims}
        if tagged:
            update["redactions"] = redactions
        if text_fixed:
            update["text_data"] = text_data
        result = await db.documents.update_one(
            {"_id": doc["_id"], "redactions": original} if tagged else {"_id": doc["_id"]},
            {"$set": update},
        )
        if tagged and not result.matched_count:
            stats["concurrent_skipped"] += 1
            continue
        stats["redactions_tagged"] += tagged
        stats["text_data_fixed"] += int(text_fixed)
        for item in review:
            stats["needs_review"].append({"document_id": doc.get("id"), **item})
    return stats


async def main() -> None:
    client: AsyncIOMotorClient = AsyncIOMotorClient(MONGODB_URI)
    try:
        db = client.get_default_database(default="blackbar")
        print(f"Tagging redaction coordinate space in database '{db.name}'...")
        stats = await tag_coordinate_space(db)
        print(f"   Documents checked: {stats['documents']}")
        print(f"   Unreadable or missing PDFs: {stats['unreadable']}")
        print(f"   Redactions tagged (unrotated pages): {stats['redactions_tagged']}")
        print(f"   text_data rebuilt in displayed space: {stats['text_data_fixed']}")
        print(f"   Skipped (changed during migration, re-run): {stats['concurrent_skipped']}")
        review = stats["needs_review"]
        print(f"   Legacy redactions on rotated pages needing review: {len(review)}")
        for item in review:
            print(
                f"     document {item['document_id']} redaction {item['id']} "
                f"page {item['page']} (rotated {item['rotation']})"
            )
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
