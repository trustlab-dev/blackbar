"""C1 migration: tag the coordinate space of legacy redactions and rebuild
legacy native-text boxes on rotated pages in displayed space."""

from __future__ import annotations

import fitz  # PyMuPDF
from motor.motor_asyncio import AsyncIOMotorGridFSBucket

from src.migrations.tag_redaction_coordinate_space import tag_coordinate_space
from tests.factories import make_document

BOX = {"page": 1, "x": 72.0, "y": 90.0, "width": 60.0, "height": 16.0}


def _pdf(rotation: int) -> tuple[bytes, fitz.Rect, fitz.Rect]:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "Zebediah", fontsize=12)
    unrotated = page.search_for("Zebediah")[0]
    page.set_rotation(rotation)
    displayed = fitz.Rect(unrotated * page.rotation_matrix)
    data = doc.tobytes()
    doc.close()
    return data, unrotated, displayed


def _legacy_text_data(unrotated: fitz.Rect, rotation: int) -> dict:
    """text_data as older builds stored it: unrotated native boxes."""
    width, height = (792.0, 612.0) if rotation in (90, 270) else (612.0, 792.0)
    bbox = [unrotated.x0, unrotated.y0, unrotated.x1, unrotated.y1]
    word = {"text": "Zebediah", "bbox": bbox, "confidence": 1.0, "line_num": 1, "word_num": 1}
    return {
        "full_text": "Zebediah\n",
        "pages": [
            {
                "page_num": 1,
                "text": "Zebediah ",
                "width": width,
                "height": height,
                "blocks": [{"text": "Zebediah", "bbox": bbox, "confidence": 1.0}],
                "words": [word],
                "lines": [{"text": "Zebediah", "bbox": bbox, "line_num": 1, "words": [word]}],
            }
        ],
    }


async def _seed(db, pdf: bytes, **fields) -> str:
    file_id = await AsyncIOMotorGridFSBucket(db).upload_from_stream("d.pdf", pdf)
    doc = make_document(content_file_id=file_id, **fields)
    await db.documents.insert_one(doc)
    return doc["id"]


async def test_unrotated_page_records_are_tagged(db) -> None:
    pdf, _, _ = _pdf(0)
    doc_id = await _seed(db, pdf, redactions=[{"id": "a", "status": "approved", **BOX}])
    stats = await tag_coordinate_space(db)
    assert stats["redactions_tagged"] == 1
    assert stats["needs_review"] == []
    doc = await db.documents.find_one({"id": doc_id})
    (red,) = doc["redactions"]
    assert (red["coord_space"], red["page_rotation"]) == ("displayed", 0)
    assert doc["page_dims"] == [[612.0, 792.0, 0]]


async def test_rotated_page_records_are_left_for_review(db) -> None:
    pdf, _, displayed = _pdf(90)
    box = {"page": 1, "x": displayed.x0, "y": displayed.y0}
    box.update(width=displayed.width, height=displayed.height)
    doc_id = await _seed(
        db,
        pdf,
        redactions=[
            {"id": "r", "status": "approved", **box},
            {"id": "gone", "status": "rejected", **box},
        ],
    )
    stats = await tag_coordinate_space(db)
    assert stats["redactions_tagged"] == 0
    assert stats["needs_review"] == [{"document_id": doc_id, "id": "r", "page": 1, "rotation": 90}]
    doc = await db.documents.find_one({"id": doc_id})
    assert all("coord_space" not in r for r in doc["redactions"])
    assert doc["page_dims"] == [[792.0, 612.0, 90]]


async def test_native_text_boxes_on_rotated_page_are_rebuilt(db) -> None:
    pdf, unrotated, displayed = _pdf(270)
    doc_id = await _seed(db, pdf, text_data=_legacy_text_data(unrotated, 270))
    stats = await tag_coordinate_space(db)
    assert stats["text_data_fixed"] == 1
    text_data = (await db.documents.find_one({"id": doc_id}))["text_data"]
    assert text_data["coord_space"] == "displayed"
    (word,) = text_data["pages"][0]["words"]
    x0, y0, x1, y1 = word["bbox"]
    assert abs(x0 - displayed.x0) < 1 and abs(y0 - displayed.y0) < 1
    assert abs(x1 - displayed.x1) < 1 and abs(y1 - displayed.y1) < 1


async def test_migration_is_idempotent(db) -> None:
    pdf, unrotated, _ = _pdf(0)
    doc_id = await _seed(
        db,
        pdf,
        redactions=[{"id": "a", "status": "approved", **BOX}],
        text_data=_legacy_text_data(unrotated, 0),
    )
    first = await tag_coordinate_space(db)
    before = await db.documents.find_one({"id": doc_id})
    second = await tag_coordinate_space(db)
    after = await db.documents.find_one({"id": doc_id})
    assert (first["redactions_tagged"], first["text_data_fixed"]) == (1, 1)
    assert (second["redactions_tagged"], second["text_data_fixed"]) == (0, 0)
    assert before["redactions"] == after["redactions"]
    assert before["text_data"] == after["text_data"]


async def test_document_without_pdf_is_counted_not_fatal(db) -> None:
    await db.documents.insert_one(make_document(redactions=[{"id": "x", **BOX}]))
    stats = await tag_coordinate_space(db)
    assert stats["unreadable"] == 1
