"""Regression tests for GitHub issue #70.

"Hashes are on converted PDFs, not original attachments": a normal upload
stored ``content_hash = sha256(original bytes)`` while an email attachment
stored ``content_hash = sha256(converted PDF)``. The same DOCX sent once as
a file and once as an attachment therefore never matched in duplicate
detection. Both paths must hash the original bytes.

Conversion, OCR, AI summary and GridFS are mocked; the MongoDB writes and
the duplicate lookup run against the real test database.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from motor.motor_asyncio import AsyncIOMotorDatabase

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "redaction-samples"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture
def docx_bytes() -> bytes:
    fixture = FIXTURES_DIR / "APA_Student_Paper.docx"
    if not fixture.exists():
        pytest.skip(f"fixture missing: {fixture}")
    return fixture.read_bytes()


@pytest.fixture
def service(db: AsyncIOMotorDatabase):
    from src.documents.processing_service import DocumentProcessingService

    svc = DocumentProcessingService(db)
    yield svc
    shutil.rmtree(svc.temp_dir, ignore_errors=True)


@pytest.fixture
def mocked_pipeline(monkeypatch, tmp_path, docx_bytes):
    """Mock conversion, OCR, summaries and GridFS.

    ``convert_to_pdf`` produces a PDF whose bytes differ from the DOCX (as
    real conversion does). An ``.eml`` input "extracts" one attachment that
    is byte-identical to ``docx_bytes``.
    """
    attachment_path = tmp_path / "attached" / "report.docx"
    attachment_path.parent.mkdir()
    attachment_path.write_bytes(docx_bytes)

    def fake_convert_to_pdf(input_file: str, output_dir: str) -> dict:
        pdf_path = Path(output_dir) / (Path(input_file).stem + ".converted.pdf")
        pdf_path.write_bytes(b"%PDF-1.4 converted from " + Path(input_file).name.encode())
        result: dict = {
            "success": True,
            "pdf_path": str(pdf_path),
            "message_id": None,
            "extracted_text": None,
            "attachments": [],
        }
        if input_file.endswith(".eml"):
            result["attachments"] = [
                {"filename": "report.docx", "path": str(attachment_path), "mime_type": DOCX_MIME}
            ]
        return result

    class FakeGridFS:
        def __init__(self, _db):
            pass

        def put(self, content, filename=None, content_type=None):
            return f"fid-{filename}"

    class FakeClient:
        def __init__(self, _uri):
            pass

        def __getitem__(self, _name):
            return MagicMock()

        def close(self):
            pass

    monkeypatch.setattr("src.documents.processing_service.convert_to_pdf", fake_convert_to_pdf)
    monkeypatch.setattr("src.documents.processing_service.MongoClient", FakeClient)
    monkeypatch.setattr("src.documents.processing_service.gridfs.GridFS", FakeGridFS)
    monkeypatch.setattr(
        "src.documents.routes.extract_text_with_coordinates",
        AsyncMock(return_value={"full_text": "", "pages": []}),
    )
    monkeypatch.setattr("src.documents.routes.get_text_summary", lambda d: "")
    monkeypatch.setattr(
        "src.admin.config_routes.get_system_config",
        AsyncMock(return_value={"auto_generate_ai_suggestions": False}),
    )


async def _upload_docx(service, docx_bytes: bytes, case_id: str):
    from src.documents.processing_service import UploadContext

    return await service.process_upload(
        file_content=docx_bytes,
        filename="report.docx",
        content_type=DOCX_MIME,
        context=UploadContext(case_id=case_id),
    )


async def _upload_email_with_docx(service, case_id: str):
    from src.documents.processing_service import UploadContext

    return await service.process_upload(
        file_content=b"From: a@example.com\r\nSubject: report\r\n\r\nsee attached",
        filename="mail.eml",
        content_type="message/rfc822",
        context=UploadContext(case_id=case_id, process_attachments=True),
    )


@pytest.mark.usefixtures("mocked_pipeline")
class TestAttachmentHashMatchesDirectUpload:
    async def test_same_docx_gets_same_hash_via_upload_and_attachment(
        self, service, db, docx_bytes
    ) -> None:
        from src.documents.processing_service import ProcessingStatus

        expected = hashlib.sha256(docx_bytes).hexdigest()

        direct = await _upload_docx(service, docx_bytes, case_id="case-direct")
        assert direct.status == ProcessingStatus.SUCCESS, direct.error

        email = await _upload_email_with_docx(service, case_id="case-email")
        assert email.status == ProcessingStatus.SUCCESS, email.error
        assert email.attachment_count == 1

        direct_doc = await db.documents.find_one({"id": direct.document_id})
        att_doc = await db.documents.find_one({"id": email.attachment_ids[0]})
        assert direct_doc["content_hash"] == expected
        assert att_doc["content_hash"] == expected
        assert att_doc["content_hash"] == direct_doc["content_hash"]

    async def test_docx_uploaded_after_email_attachment_is_flagged_duplicate(
        self, service, docx_bytes
    ) -> None:
        from src.documents.processing_service import ProcessingStatus

        email = await _upload_email_with_docx(service, case_id="case-1")
        assert email.status == ProcessingStatus.SUCCESS, email.error

        direct = await _upload_docx(service, docx_bytes, case_id="case-1")
        assert direct.status == ProcessingStatus.DUPLICATE
        assert direct.duplicate_of_id == email.attachment_ids[0]


class TestRehashAttachmentMigration:
    async def test_rehashes_from_gridfs_original(self, db, docx_bytes) -> None:
        from bson import ObjectId
        from motor.motor_asyncio import AsyncIOMotorGridFSBucket

        from src.migrations.rehash_attachment_content_hash import (
            rehash_attachment_content_hashes,
        )

        expected = hashlib.sha256(docx_bytes).hexdigest()
        stale = hashlib.sha256(b"%PDF converted").hexdigest()
        file_id = await AsyncIOMotorGridFSBucket(db).upload_from_stream("report.docx", docx_bytes)
        await db.documents.insert_many(
            [
                # Converted attachment with a PDF hash: must be rewritten.
                {
                    "id": "att-stale",
                    "is_attachment": True,
                    "content_hash": stale,
                    "original_file_id": file_id,
                },
                # PDF attachment (no separate original): left untouched.
                {"id": "att-pdf", "is_attachment": True, "content_hash": "pdf-h"},
                # Original missing from GridFS: counted, left untouched.
                {
                    "id": "att-gone",
                    "is_attachment": True,
                    "content_hash": "gone-h",
                    "original_file_id": ObjectId(),
                },
                # Not an attachment: out of scope.
                {"id": "doc", "content_hash": "doc-h", "original_file_id": file_id},
            ]
        )

        stats = await rehash_attachment_content_hashes(db)
        assert stats == {"checked": 2, "updated": 1, "missing_original": 1}

        hashes = {d["id"]: d["content_hash"] async for d in db.documents.find({})}
        assert hashes == {
            "att-stale": expected,
            "att-pdf": "pdf-h",
            "att-gone": "gone-h",
            "doc": "doc-h",
        }

        # Idempotent.
        again = await rehash_attachment_content_hashes(db)
        assert again["updated"] == 0
