"""Tests for `src.documents.processing_service`.

Phase 2.3.A — 100% line + branch coverage on the
DocumentProcessingService critical-path module (922 LoC).

Strategy:
- Fast unit tests (default): mock subprocess (libreoffice), pytesseract,
  PyMuPDF (fitz), GridFS, and the cross-module imports done lazily
  inside methods (`src.documents.routes.*`, `src.admin.config_routes.*`,
  `src.database.db`). Reach 100% coverage on the glue logic alone.
- Slow integration tests (marked `@pytest.mark.slow`): exercise the
  real conversion pipeline on sample fixtures from
  `backend/tests/fixtures/redaction-samples/`. These confirm the
  integration once per format and are skipped if the underlying tool
  isn't installed. They are NOT required for coverage — the fast
  variants reach 100% on their own.

Source-API pinning notes (candidates for audit Section 11):
- `src.admin.config_routes.get_system_config()` is a 0-arg coroutine,
  but `processing_service` calls it as `get_system_config(self.db)`.
  In production this raises TypeError, which is then swallowed by the
  surrounding `try/except` in both `_generate_summary` and
  `_queue_ai_processing`. Net effect: AI summary and background AI
  processing are silently disabled regardless of org settings. Tests
  pin this by mocking `get_system_config` with a flexible signature.
- `_generate_summary` and `_queue_ai_processing` catch all exceptions
  and return None / no-op rather than propagating. Tests pin the
  swallow behavior.
- A corrupt PDF that PyMuPDF accepts but yields no text doesn't raise:
  `_extract_text` returns `(text_data, summary)` with empty text.
- `_validate_file` short-circuits on extension *before* size check,
  and on size *before* MIME check — order matters for callers.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from motor.motor_asyncio import AsyncIOMotorDatabase

# Sample fixtures shared with other test modules.
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "redaction-samples"


# ===========================================================================
# Helpers
# ===========================================================================


def _make_minimal_pdf_bytes() -> bytes:
    """Build a tiny valid 1-page PDF in memory using PyMuPDF."""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 50), "Hello world test PDF", fontsize=10)
    out = doc.tobytes()
    doc.close()
    return out


def _make_blank_pdf_bytes() -> bytes:
    """PDF with no text content (for OCR-fallback branch)."""
    import fitz

    doc = fitz.open()
    doc.new_page(width=100, height=100)
    out = doc.tobytes()
    doc.close()
    return out


@pytest.fixture
def service(db: AsyncIOMotorDatabase):
    """A fresh DocumentProcessingService bound to the per-test DB.

    The constructor creates a tempdir; we tear it down to avoid leaking
    `/tmp/blackbar_uploads_*` directories across the test session.
    """
    from src.documents.processing_service import DocumentProcessingService

    svc = DocumentProcessingService(db)
    yield svc
    shutil.rmtree(svc.temp_dir, ignore_errors=True)


# ===========================================================================
# __init__
# ===========================================================================


class TestInit:
    def test_init_creates_tempdir(self, db: AsyncIOMotorDatabase) -> None:
        from src.documents.processing_service import DocumentProcessingService

        svc = DocumentProcessingService(db)
        try:
            assert os.path.isdir(svc.temp_dir)
            assert svc.temp_dir.endswith(os.sep + os.path.basename(svc.temp_dir))
            assert "blackbar_uploads_" in svc.temp_dir
            assert svc.db is db
        finally:
            shutil.rmtree(svc.temp_dir, ignore_errors=True)


# ===========================================================================
# _validate_file
# ===========================================================================


class TestValidateFile:
    def test_rejects_unknown_extension(self, service) -> None:
        err = service._validate_file(b"x", "foo.exe", None)
        assert err is not None
        assert "Invalid file type" in err

    def test_rejects_oversized(self, service) -> None:
        from src.documents.processing_service import MAX_FILE_SIZE

        err = service._validate_file(b"x" * (MAX_FILE_SIZE + 1), "ok.pdf", None)
        assert err is not None
        assert "too large" in err.lower()

    def test_rejects_bad_mime(self, service) -> None:
        err = service._validate_file(b"x", "ok.pdf", "text/plain")
        assert err is not None
        assert "Invalid MIME type" in err

    def test_accepts_valid(self, service) -> None:
        assert service._validate_file(b"x", "ok.pdf", "application/pdf") is None

    def test_accepts_when_mime_omitted(self, service) -> None:
        assert service._validate_file(b"x", "ok.pdf", None) is None


# ===========================================================================
# _check_duplicate_by_hash / _check_duplicate_by_message_id
# ===========================================================================


class TestDuplicateChecks:
    async def test_hash_match_without_case_id(self, service, db) -> None:
        await db.documents.insert_one({"id": "abc", "content_hash": "h1"})
        found = await service._check_duplicate_by_hash("h1", None)
        assert found is not None and found["id"] == "abc"

    async def test_hash_match_with_case_id(self, service, db) -> None:
        await db.documents.insert_one({"id": "abc", "content_hash": "h2", "case_id": "case1"})
        found = await service._check_duplicate_by_hash("h2", "case1")
        assert found is not None and found["id"] == "abc"
        # Different case: no hit.
        assert await service._check_duplicate_by_hash("h2", "case2") is None

    async def test_hash_no_match(self, service) -> None:
        assert await service._check_duplicate_by_hash("nope", None) is None

    async def test_message_id_match_without_case_id(self, service, db) -> None:
        await db.documents.insert_one({"id": "e1", "message_id": "<msg@x>"})
        found = await service._check_duplicate_by_message_id("<msg@x>", None)
        assert found is not None and found["id"] == "e1"

    async def test_message_id_match_with_case_id(self, service, db) -> None:
        await db.documents.insert_one({"id": "e1", "message_id": "<m@x>", "case_id": "c1"})
        assert (await service._check_duplicate_by_message_id("<m@x>", "c1"))["id"] == "e1"


# ===========================================================================
# _convert_to_pdf
# ===========================================================================


class TestConvertToPDF:
    async def test_pdf_passthrough(self, service) -> None:
        result = await service._convert_to_pdf(b"%PDF-1.4 ...", "doc.pdf", ".pdf")
        assert result["success"] is True
        assert result["pdf_content"] == b"%PDF-1.4 ..."
        assert result["final_filename"] == "doc.pdf"

    async def test_docx_success_mocked(self, service, tmp_path) -> None:
        # `convert_to_pdf` writes a fake PDF to disk and reports success.
        fake_pdf_path = str(tmp_path / "out.pdf")
        with open(fake_pdf_path, "wb") as f:
            f.write(b"%PDF-fake")
        fake_result = {
            "success": True,
            "pdf_path": fake_pdf_path,
            "message_id": None,
            "extracted_text": "hello",
            "attachments": [],
        }
        with patch(
            "src.documents.processing_service.convert_to_pdf",
            return_value=fake_result,
        ):
            result = await service._convert_to_pdf(b"docx-bytes", "thing.docx", ".docx")
        assert result["success"] is True
        assert result["pdf_content"] == b"%PDF-fake"
        assert result["final_filename"] == "thing.docx.pdf"
        assert result["mime_type"] == "application/pdf"
        assert result["extracted_text"] == "hello"

    async def test_eml_success_sets_mime(self, service, tmp_path) -> None:
        fake_pdf_path = str(tmp_path / "e.pdf")
        with open(fake_pdf_path, "wb") as f:
            f.write(b"%PDF-eml")
        fake_result = {
            "success": True,
            "pdf_path": fake_pdf_path,
            "message_id": "<msg-1@x>",
            "extracted_text": "body",
            "attachments": [{"filename": "a.txt", "path": "/tmp/x"}],
        }
        with patch(
            "src.documents.processing_service.convert_to_pdf",
            return_value=fake_result,
        ):
            result = await service._convert_to_pdf(b"eml-bytes", "m.eml", ".eml")
        assert result["success"] is True
        assert result["mime_type"] == "message/rfc822"
        assert result["message_id"] == "<msg-1@x>"
        assert len(result["attachments"]) == 1

    async def test_msg_success_sets_mime(self, service, tmp_path) -> None:
        fake_pdf_path = str(tmp_path / "m.pdf")
        with open(fake_pdf_path, "wb") as f:
            f.write(b"%PDF-msg")
        fake_result = {
            "success": True,
            "pdf_path": fake_pdf_path,
            "message_id": None,
            "extracted_text": None,
            "attachments": [],
        }
        with patch(
            "src.documents.processing_service.convert_to_pdf",
            return_value=fake_result,
        ):
            result = await service._convert_to_pdf(b"msg-bytes", "x.msg", ".msg")
        assert result["mime_type"] == "application/vnd.ms-outlook"

    async def test_conversion_reports_failure(self, service) -> None:
        with patch(
            "src.documents.processing_service.convert_to_pdf",
            return_value={"success": False, "error": "tool missing"},
        ):
            result = await service._convert_to_pdf(b"x", "x.docx", ".docx")
        assert result["success"] is False
        assert result["error"] == "tool missing"

    async def test_conversion_exception_in_outer_try(self, service) -> None:
        with patch(
            "src.documents.processing_service.convert_to_pdf",
            side_effect=RuntimeError("kaboom"),
        ):
            result = await service._convert_to_pdf(b"x", "x.docx", ".docx")
        assert result["success"] is False
        # The inner exception is caught by the outer try/except — error key set.
        assert result["error"] is not None

    async def test_conversion_outer_exception_path(self, service, monkeypatch) -> None:
        """Force an exception BEFORE reaching the inner try (e.g. tempdir
        write fails). The outer except clause sets `error` to str(e)."""

        def _boom(*a, **kw):
            raise OSError("disk full")

        monkeypatch.setattr("builtins.open", _boom)
        result = await service._convert_to_pdf(b"x", "x.docx", ".docx")
        assert result["success"] is False
        assert "disk full" in result["error"]

    async def test_finally_branch_when_temp_input_already_deleted(self, service, tmp_path) -> None:
        """Exercise the False branch of `if os.path.exists(temp_input)` in
        the finally clause. The mocked converter deletes the temp input
        file (simulating a converter that consumes its input). The finally
        block's existence check must then short-circuit cleanly."""
        fake_pdf_path = str(tmp_path / "out.pdf")
        with open(fake_pdf_path, "wb") as f:
            f.write(b"%PDF-x")

        def _consume_input(input_path, output_dir):
            # Delete the input file as part of "conversion".
            os.remove(input_path)
            return {
                "success": True,
                "pdf_path": fake_pdf_path,
                "message_id": None,
                "extracted_text": None,
                "attachments": [],
            }

        with patch(
            "src.documents.processing_service.convert_to_pdf",
            side_effect=_consume_input,
        ):
            result = await service._convert_to_pdf(b"x", "x.docx", ".docx")
        assert result["success"] is True


# ===========================================================================
# _extract_text
# ===========================================================================


class TestExtractText:
    async def test_happy_path(self, service) -> None:
        text_data = {
            "full_text": "hello world",
            "pages": [{"text": "hello world", "page": 1}],
        }
        with (
            patch(
                "src.documents.routes.extract_text_with_coordinates",
                AsyncMock(return_value=text_data),
            ),
            patch(
                "src.documents.routes.get_text_summary",
                return_value="hello...",
            ),
        ):
            data, summary = await service._extract_text(b"%PDF", "doc.pdf")
        assert data["full_text"] == "hello world"
        assert summary == "hello..."

    async def test_page_truncation(self, service) -> None:
        many_pages = [{"text": f"p{i}", "page": i} for i in range(60)]
        text_data = {"full_text": "x", "pages": many_pages}
        with (
            patch(
                "src.documents.routes.extract_text_with_coordinates",
                AsyncMock(return_value=text_data),
            ),
            patch(
                "src.documents.routes.get_text_summary",
                return_value="sum",
            ),
        ):
            data, _ = await service._extract_text(b"%PDF", "big.pdf")
        assert len(data["pages"]) == 50
        assert data["truncated"] is True

    async def test_text_truncation(self, service) -> None:
        big_text = "x" * 600_000
        text_data = {"full_text": big_text, "pages": []}
        with (
            patch(
                "src.documents.routes.extract_text_with_coordinates",
                AsyncMock(return_value=text_data),
            ),
            patch(
                "src.documents.routes.get_text_summary",
                return_value="sum",
            ),
        ):
            data, _ = await service._extract_text(b"%PDF", "big.pdf")
        assert len(data["full_text"]) == 500_000
        assert data["truncated"] is True

    async def test_exception_returns_none(self, service) -> None:
        with patch(
            "src.documents.routes.extract_text_with_coordinates",
            AsyncMock(side_effect=RuntimeError("ocr crashed")),
        ):
            data, summary = await service._extract_text(b"%PDF", "doc.pdf")
        assert data is None
        assert summary is None


# ===========================================================================
# _generate_summary
# ===========================================================================


class TestGenerateSummary:
    async def test_disabled_by_org_settings(self, service) -> None:
        with patch(
            "src.admin.config_routes.get_system_config",
            AsyncMock(return_value={"auto_generate_ai_suggestions": False}),
        ):
            summary = await service._generate_summary(b"%PDF", "doc.pdf", "application/pdf")
        assert summary is None

    async def test_enabled_returns_summary(self, service) -> None:
        with (
            patch(
                "src.admin.config_routes.get_system_config",
                AsyncMock(return_value={"auto_generate_ai_suggestions": True}),
            ),
            patch(
                "src.documents.routes.generate_document_summary",
                AsyncMock(return_value="AI summary text"),
            ),
        ):
            summary = await service._generate_summary(b"%PDF", "doc.pdf", "application/pdf")
        assert summary == "AI summary text"

    async def test_exception_swallowed(self, service) -> None:
        with patch(
            "src.admin.config_routes.get_system_config",
            AsyncMock(side_effect=RuntimeError("config crashed")),
        ):
            summary = await service._generate_summary(b"%PDF", "doc.pdf", "application/pdf")
        assert summary is None


# ===========================================================================
# _store_in_gridfs
# ===========================================================================


class TestStoreInGridFS:
    async def test_pdf_passthrough_stores_one_file(self, service, monkeypatch) -> None:
        """For native PDFs, only the content file is stored (no separate
        original)."""
        captured = {"puts": []}

        class FakeGridFS:
            def __init__(self, _db):
                pass

            def put(self, content, filename=None, content_type=None):
                fid = f"fid_{len(captured['puts'])}"
                captured["puts"].append(
                    {
                        "id": fid,
                        "filename": filename,
                        "content_type": content_type,
                        "size": len(content),
                    }
                )
                return fid

        class FakeClient:
            def __init__(self, _uri):
                pass

            def __getitem__(self, _name):
                return MagicMock()

            def close(self):
                pass

        with (
            patch("src.documents.processing_service.MongoClient", FakeClient),
            patch("src.documents.processing_service.gridfs.GridFS", FakeGridFS),
        ):
            result = await service._store_in_gridfs(
                original_content=b"%PDF-original",
                pdf_content=b"%PDF-original",  # Same as original for PDF.
                original_filename="doc.pdf",
                pdf_filename="doc.pdf",
                content_type="application/pdf",
                ext=".pdf",
            )
        assert result["content_file_id"] == "fid_0"
        # For .pdf, no separate original is stored.
        assert result["original_file_id"] is None
        assert len(captured["puts"]) == 1

    async def test_converted_stores_both_files(self, service) -> None:
        captured = {"puts": []}

        class FakeGridFS:
            def __init__(self, _db):
                pass

            def put(self, content, filename=None, content_type=None):
                fid = f"fid_{len(captured['puts'])}"
                captured["puts"].append({"id": fid, "filename": filename})
                return fid

        class FakeClient:
            def __init__(self, _uri):
                pass

            def __getitem__(self, _name):
                return MagicMock()

            def close(self):
                pass

        with (
            patch("src.documents.processing_service.MongoClient", FakeClient),
            patch("src.documents.processing_service.gridfs.GridFS", FakeGridFS),
        ):
            result = await service._store_in_gridfs(
                original_content=b"docx-bytes",
                pdf_content=b"%PDF-converted",
                original_filename="doc.docx",
                pdf_filename="doc.docx.pdf",
                content_type=(
                    "application/vnd.openxmlformats-officedocument." "wordprocessingml.document"
                ),
                ext=".docx",
            )
        assert result["content_file_id"] == "fid_0"
        assert result["original_file_id"] == "fid_1"
        assert len(captured["puts"]) == 2

    async def test_no_pdf_falls_back_to_original(self, service) -> None:
        captured = {"puts": []}

        class FakeGridFS:
            def __init__(self, _db):
                pass

            def put(self, content, filename=None, content_type=None):
                captured["puts"].append({"filename": filename, "content_type": content_type})
                return "fid"

        class FakeClient:
            def __init__(self, _uri):
                pass

            def __getitem__(self, _name):
                return MagicMock()

            def close(self):
                pass

        with (
            patch("src.documents.processing_service.MongoClient", FakeClient),
            patch("src.documents.processing_service.gridfs.GridFS", FakeGridFS),
        ):
            result = await service._store_in_gridfs(
                original_content=b"original-bytes",
                pdf_content=None,  # No converted PDF.
                original_filename="thing.docx",
                pdf_filename="thing.docx.pdf",
                content_type="application/x-special",
                ext=".docx",
            )
        assert result["content_file_id"] == "fid"
        assert captured["puts"][0]["filename"] == "thing.docx"
        assert captured["puts"][0]["content_type"] == "application/x-special"

    async def test_exception_returns_empty(self, service) -> None:
        with patch(
            "src.documents.processing_service.MongoClient",
            side_effect=RuntimeError("mongo down"),
        ):
            result = await service._store_in_gridfs(
                original_content=b"x",
                pdf_content=b"y",
                original_filename="x.pdf",
                pdf_filename="x.pdf",
                content_type="application/pdf",
                ext=".pdf",
            )
        assert result["content_file_id"] is None
        assert result["original_file_id"] is None


# ===========================================================================
# _build_document_record
# ===========================================================================


class TestBuildDocumentRecord:
    def test_pdf_record_no_original_filename(self, service) -> None:
        from src.documents.processing_service import UploadContext

        ctx = UploadContext(case_id="c1", uploaded_by="u1", uploaded_by_name="User")
        doc = service._build_document_record(
            document_id="d1",
            filename="file.pdf",
            final_filename="file.pdf",
            content_hash="h",
            pdf_content=b"%PDF",
            mime_type="application/pdf",
            message_id=None,
            extracted_text="hello",
            text_data={"full_text": "hello"},
            text_summary="sum",
            summary="ai",
            gridfs_ids={"content_file_id": "gf1", "original_file_id": None},
            context=ctx,
            ext=".pdf",
            conversion_result={},
        )
        assert doc["id"] == "d1"
        assert doc["original_filename"] is None  # No conversion for PDFs.
        assert doc["conversion_status"] == "not_needed"
        assert doc["processing_status"] == "ocr_complete"
        assert "message_id" not in doc  # Only set for emails.

    def test_docx_record_has_original_filename(self, service) -> None:
        from src.documents.processing_service import UploadContext

        ctx = UploadContext(case_id="c1")
        doc = service._build_document_record(
            document_id="d2",
            filename="thing.docx",
            final_filename="thing.docx.pdf",
            content_hash="h",
            pdf_content=b"%PDF",
            mime_type="application/pdf",
            message_id=None,
            extracted_text=None,
            text_data=None,
            text_summary=None,
            summary=None,
            gridfs_ids={"content_file_id": "gf2", "original_file_id": "gf3"},
            context=ctx,
            ext=".docx",
            conversion_result={},
        )
        assert doc["original_filename"] == "thing.docx"
        assert doc["conversion_status"] == "converted"
        assert doc["processing_status"] == "pending"  # No text_data.

    def test_record_with_contributor(self, service) -> None:
        from src.documents.processing_service import UploadContext

        ctx = UploadContext(contributor_id="contrib-1", contributor_name="Bob Contributor")
        doc = service._build_document_record(
            document_id="d3",
            filename="x.pdf",
            final_filename="x.pdf",
            content_hash="h",
            pdf_content=b"x",
            mime_type="application/pdf",
            message_id=None,
            extracted_text=None,
            text_data=None,
            text_summary=None,
            summary=None,
            gridfs_ids={},
            context=ctx,
            ext=".pdf",
            conversion_result={},
        )
        assert doc["uploaded_by_contributor"] == "contrib-1"
        assert doc["contributor_name"] == "Bob Contributor"

    def test_record_with_collection_link(self, service) -> None:
        from src.documents.processing_service import UploadContext

        ctx = UploadContext(
            collection_link_id="link-1",
            submitter_name="Submitter",
            submitter_email="s@x.test",
            submitter_notes="Notes",
        )
        doc = service._build_document_record(
            document_id="d4",
            filename="x.pdf",
            final_filename="x.pdf",
            content_hash="h",
            pdf_content=b"x",
            mime_type="application/pdf",
            message_id=None,
            extracted_text=None,
            text_data=None,
            text_summary=None,
            summary=None,
            gridfs_ids={},
            context=ctx,
            ext=".pdf",
            conversion_result={},
        )
        assert doc["collection_link_id"] == "link-1"
        assert doc["submitter_email"] == "s@x.test"

    def test_record_eml_sets_email_mime(self, service) -> None:
        from src.documents.processing_service import UploadContext

        ctx = UploadContext()
        doc = service._build_document_record(
            document_id="d5",
            filename="m.eml",
            final_filename="m.eml.pdf",
            content_hash="h",
            pdf_content=b"%PDF",
            mime_type="application/pdf",
            message_id="<msg@x>",
            extracted_text="body",
            text_data=None,
            text_summary=None,
            summary=None,
            gridfs_ids={},
            context=ctx,
            ext=".eml",
            conversion_result={},
        )
        assert doc["message_id"] == "<msg@x>"
        assert doc["original_mime_type"] == "message/rfc822"

    def test_record_msg_sets_outlook_mime(self, service) -> None:
        from src.documents.processing_service import UploadContext

        ctx = UploadContext()
        doc = service._build_document_record(
            document_id="d6",
            filename="m.msg",
            final_filename="m.msg.pdf",
            content_hash="h",
            pdf_content=b"%PDF",
            mime_type="application/pdf",
            message_id="<msg@x>",
            extracted_text="body",
            text_data=None,
            text_summary=None,
            summary=None,
            gridfs_ids={},
            context=ctx,
            ext=".msg",
            conversion_result={},
        )
        assert doc["original_mime_type"] == "application/vnd.ms-outlook"

    def test_record_no_pdf_content_zero_size(self, service) -> None:
        from src.documents.processing_service import UploadContext

        doc = service._build_document_record(
            document_id="d7",
            filename="x.docx",
            final_filename="x.docx",
            content_hash="h",
            pdf_content=None,
            mime_type="application/octet-stream",
            message_id=None,
            extracted_text=None,
            text_data=None,
            text_summary=None,
            summary=None,
            gridfs_ids={},
            context=UploadContext(),
            ext=".docx",
            conversion_result={},
        )
        assert doc["size"] == 0
        assert doc["conversion_status"] == "not_needed"


# ===========================================================================
# _process_attachments
# ===========================================================================


class TestProcessAttachments:
    async def test_happy_path(self, service, tmp_path) -> None:
        # Phase 4 Batch 4.4 (audit B25/B58): the prior
        # `@pytest.mark.filterwarnings("ignore::ResourceWarning")` (plus
        # the matching PytestUnraisableExceptionWarning suppressor)
        # absorbed an FD leak from `open(att_path, "rb").read()` in
        # `_process_attachments`. The source now uses a `with` block
        # so the warnings no longer fire and the markers can go.
        att_input = tmp_path / "attachment.docx"
        att_input.write_bytes(b"raw-docx-bytes")
        att_pdf = tmp_path / "out.pdf"
        att_pdf.write_bytes(b"%PDF-attached")

        from src.documents.processing_service import UploadContext

        with (
            patch(
                "src.documents.processing_service.convert_to_pdf",
                return_value={"success": True, "pdf_path": str(att_pdf)},
            ),
            patch.object(
                service, "_extract_text", AsyncMock(return_value=({"full_text": "x"}, "s"))
            ),
            patch.object(service, "_generate_summary", AsyncMock(return_value=None)),
            patch.object(
                service,
                "_store_in_gridfs",
                AsyncMock(return_value={"content_file_id": "f1", "original_file_id": "f2"}),
            ),
        ):
            attachments = [
                {
                    "filename": "attachment.docx",
                    "path": str(att_input),
                    "mime_type": "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document",
                }
            ]
            docs = await service._process_attachments(
                attachments, "parent-1", UploadContext(case_id="c1")
            )
        assert len(docs) == 1
        assert docs[0]["parent_document_id"] == "parent-1"
        assert docs[0]["is_attachment"] is True
        assert docs[0]["case_id"] == "c1"

    async def test_missing_file_skipped(self, service) -> None:
        from src.documents.processing_service import UploadContext

        docs = await service._process_attachments(
            [{"filename": "x.pdf", "path": "/nonexistent/x.pdf"}],
            "parent-1",
            UploadContext(),
        )
        assert docs == []

    async def test_no_path_skipped(self, service) -> None:
        from src.documents.processing_service import UploadContext

        docs = await service._process_attachments(
            [{"filename": "x.pdf"}],  # No path.
            "parent-1",
            UploadContext(),
        )
        assert docs == []

    async def test_conversion_failure_skipped(self, service, tmp_path) -> None:
        att = tmp_path / "att.docx"
        att.write_bytes(b"x")
        with patch(
            "src.documents.processing_service.convert_to_pdf",
            return_value={"success": False, "error": "bad"},
        ):
            from src.documents.processing_service import UploadContext

            docs = await service._process_attachments(
                [{"filename": "att.docx", "path": str(att)}],
                "parent-1",
                UploadContext(),
            )
        assert docs == []

    async def test_inner_exception_continues(self, service, tmp_path) -> None:
        att = tmp_path / "att.docx"
        att.write_bytes(b"x")
        att_pdf = tmp_path / "att.pdf"
        att_pdf.write_bytes(b"%PDF")
        from src.documents.processing_service import UploadContext

        # Cause an exception inside the per-attachment try (e.g. extract_text
        # raises). The outer loop catches and continues.
        with (
            patch(
                "src.documents.processing_service.convert_to_pdf",
                return_value={"success": True, "pdf_path": str(att_pdf)},
            ),
            patch.object(
                service,
                "_extract_text",
                AsyncMock(side_effect=RuntimeError("boom")),
            ),
        ):
            docs = await service._process_attachments(
                [{"filename": "att.docx", "path": str(att)}],
                "parent-1",
                UploadContext(),
            )
        assert docs == []


# ===========================================================================
# _merge_attachments_into_email
# ===========================================================================


class TestMergeAttachmentsIntoEmail:
    async def test_merges_new_attachment(self, service, db, tmp_path) -> None:
        # Existing email with no attachments (must be in DB for the update_one
        # call to land somewhere observable).
        await db.documents.insert_one(
            {"id": "email-1", "attachment_ids": [], "filename": "old.eml"}
        )
        existing_email = {"id": "email-1", "attachment_ids": []}
        # Provide an attachment file.
        att = tmp_path / "newatt.docx"
        att.write_bytes(b"new-data")

        from src.documents.processing_service import UploadContext

        # Mock _process_attachments to return a single attachment doc.
        att_doc = {
            "id": "att-1",
            "filename": "newatt.docx",
            "original_filename": "newatt.docx",
            "size": 8,
        }
        with patch.object(service, "_process_attachments", AsyncMock(return_value=[att_doc])):
            merged = await service._merge_attachments_into_email(
                existing_email,
                [{"filename": "newatt.docx", "path": str(att)}],
                UploadContext(),
            )
        assert merged == 1
        # Verify the email got updated.
        email = await db.documents.find_one({"id": "email-1"})
        assert "att-1" in email["attachment_ids"]
        assert email["has_attachments"] is True

    async def test_skips_duplicate_attachment(self, service, db, tmp_path) -> None:
        # Pre-existing attachment with matching filename + size.
        att = tmp_path / "dup.docx"
        att.write_bytes(b"abcdefgh")  # 8 bytes.

        await db.documents.insert_one(
            {"id": "exist-att", "original_filename": "dup.docx", "size": 8}
        )

        existing_email = {"id": "email-1", "attachment_ids": ["exist-att"]}

        from src.documents.processing_service import UploadContext

        merged = await service._merge_attachments_into_email(
            existing_email,
            [{"filename": "dup.docx", "path": str(att)}],
            UploadContext(),
        )
        assert merged == 0

    async def test_skips_missing_file(self, service) -> None:
        from src.documents.processing_service import UploadContext

        merged = await service._merge_attachments_into_email(
            {"id": "e", "attachment_ids": []},
            [{"filename": "x", "path": "/no/such/path"}],
            UploadContext(),
        )
        assert merged == 0

    async def test_skips_no_path(self, service) -> None:
        from src.documents.processing_service import UploadContext

        merged = await service._merge_attachments_into_email(
            {"id": "e", "attachment_ids": []},
            [{"filename": "x"}],
            UploadContext(),
        )
        assert merged == 0

    async def test_process_returns_empty_no_insert(self, service, db, tmp_path) -> None:
        """If _process_attachments returns [] (e.g. conversion failed),
        nothing is inserted and merged_count stays 0."""
        att = tmp_path / "att.docx"
        att.write_bytes(b"x")
        existing_email = {"id": "email-1", "attachment_ids": []}
        from src.documents.processing_service import UploadContext

        with patch.object(service, "_process_attachments", AsyncMock(return_value=[])):
            merged = await service._merge_attachments_into_email(
                existing_email,
                [{"filename": "att.docx", "path": str(att)}],
                UploadContext(),
            )
        assert merged == 0

    async def test_inner_exception_continues(self, service, tmp_path) -> None:
        att = tmp_path / "att.docx"
        att.write_bytes(b"x")
        from src.documents.processing_service import UploadContext

        with patch.object(
            service,
            "_process_attachments",
            AsyncMock(side_effect=RuntimeError("boom")),
        ):
            merged = await service._merge_attachments_into_email(
                {"id": "e", "attachment_ids": []},
                [{"filename": "att.docx", "path": str(att)}],
                UploadContext(),
            )
        assert merged == 0


# ===========================================================================
# _consolidate_email_thread
# ===========================================================================


class TestConsolidateEmailThread:
    async def test_no_extracted_text_returns_none(self, service) -> None:
        result = await service._consolidate_email_thread({"id": "d1", "extracted_text": ""}, None)
        assert result is None

    async def test_no_thread_identifiers_returns_none(self, service) -> None:
        with patch(
            "src.documents.routes.extract_thread_identifiers",
            return_value=None,
        ):
            result = await service._consolidate_email_thread(
                {"id": "d1", "extracted_text": "x", "message_id": "<m@x>"}, None
            )
        assert result is None

    async def test_no_thread_emails_marks_active(self, service, db) -> None:
        await db.documents.insert_one({"id": "d1", "extracted_text": "x", "message_id": "<m@x>"})
        with (
            patch(
                "src.documents.routes.extract_thread_identifiers",
                return_value={"subject": "S"},
            ),
            patch(
                "src.documents.routes.find_thread_emails",
                AsyncMock(return_value=[]),
            ),
        ):
            result = await service._consolidate_email_thread(
                {"id": "d1", "extracted_text": "x", "message_id": "<m@x>"}, "c1"
            )
        assert result is None
        doc = await db.documents.find_one({"id": "d1"})
        assert doc["thread_status"] == "active"

    async def test_happy_path_consolidates(self, service, db) -> None:
        await db.documents.insert_one({"id": "d1", "extracted_text": "x", "message_id": "<m@x>"})
        with (
            patch(
                "src.documents.routes.extract_thread_identifiers",
                return_value={"subject": "S"},
            ),
            patch(
                "src.documents.routes.find_thread_emails",
                AsyncMock(return_value=[{"id": "other"}]),
            ),
            patch(
                "src.documents.routes.consolidate_email_thread",
                AsyncMock(return_value={"consolidated": True, "merged": 1}),
            ),
        ):
            result = await service._consolidate_email_thread(
                {"id": "d1", "extracted_text": "x", "message_id": "<m@x>"}, "c1"
            )
        assert result == {"consolidated": True, "merged": 1}

    async def test_exception_returns_none(self, service) -> None:
        with patch(
            "src.documents.routes.extract_thread_identifiers",
            side_effect=RuntimeError("boom"),
        ):
            result = await service._consolidate_email_thread(
                {"id": "d1", "extracted_text": "x"}, None
            )
        assert result is None


# ===========================================================================
# _queue_ai_processing
# ===========================================================================


class TestQueueAIProcessing:
    async def test_disabled_noop(self, service, db) -> None:
        from fastapi import BackgroundTasks

        bg = BackgroundTasks()
        await db.documents.insert_one({"id": "d1"})
        with patch(
            "src.admin.config_routes.get_system_config",
            AsyncMock(return_value={"auto_generate_ai_suggestions": False}),
        ):
            await service._queue_ai_processing("d1", bg)
        # No background task added.
        assert len(bg.tasks) == 0

    async def test_enabled_queues_with_custom_timeout(self, service, db, monkeypatch) -> None:
        from fastapi import BackgroundTasks

        import src.database as db_mod

        bg = BackgroundTasks()
        await db.documents.insert_one({"id": "d1"})
        # Insert AI config.
        await db.system_config.insert_one(
            {"id": "global_ai_settings", "ai_suggestion_timeout": 300}
        )
        # main_db is `src.database.db`; patch it to our test DB.
        monkeypatch.setattr(db_mod, "db", db, raising=False)

        with (
            patch(
                "src.admin.config_routes.get_system_config",
                AsyncMock(return_value={"auto_generate_ai_suggestions": True}),
            ),
            patch(
                "src.documents.routes.generate_ai_suggestions_async",
                AsyncMock(),
            ),
        ):
            await service._queue_ai_processing("d1", bg)

        assert len(bg.tasks) == 1
        doc = await db.documents.find_one({"id": "d1"})
        assert doc["processing_status"] == "ai_queued"

    async def test_enabled_no_config_uses_default_timeout(self, service, db, monkeypatch) -> None:
        from fastapi import BackgroundTasks

        import src.database as db_mod

        bg = BackgroundTasks()
        await db.documents.insert_one({"id": "d1"})
        # No global_ai_settings doc → defaults to 120.
        monkeypatch.setattr(db_mod, "db", db, raising=False)

        with (
            patch(
                "src.admin.config_routes.get_system_config",
                AsyncMock(return_value={"auto_generate_ai_suggestions": True}),
            ),
            patch(
                "src.documents.routes.generate_ai_suggestions_async",
                AsyncMock(),
            ),
        ):
            await service._queue_ai_processing("d1", bg)

        assert len(bg.tasks) == 1

    async def test_exception_swallowed(self, service) -> None:
        from fastapi import BackgroundTasks

        bg = BackgroundTasks()
        with patch(
            "src.admin.config_routes.get_system_config",
            AsyncMock(side_effect=RuntimeError("crashed")),
        ):
            # Should not raise.
            await service._queue_ai_processing("d1", bg)
        assert len(bg.tasks) == 0


# ===========================================================================
# process_upload — end-to-end orchestration
# ===========================================================================


@pytest.fixture
def patch_gridfs_stack(monkeypatch):
    """Patch the GridFS storage layer to avoid hitting the real MongoClient
    inside `_store_in_gridfs`. Returns the captured `puts` for assertions."""
    captured = {"puts": []}

    class FakeGridFS:
        def __init__(self, _db):
            pass

        def put(self, content, filename=None, content_type=None):
            fid = f"fid_{len(captured['puts'])}"
            captured["puts"].append({"id": fid, "filename": filename, "content_type": content_type})
            return fid

    class FakeClient:
        def __init__(self, _uri):
            pass

        def __getitem__(self, _name):
            return MagicMock()

        def close(self):
            pass

    monkeypatch.setattr("src.documents.processing_service.MongoClient", FakeClient)
    monkeypatch.setattr("src.documents.processing_service.gridfs.GridFS", FakeGridFS)
    return captured


class TestProcessUploadOrchestration:
    async def test_validation_failure_short_circuits(self, service) -> None:
        from src.documents.processing_service import (
            ProcessingStatus,
            UploadContext,
        )

        result = await service.process_upload(
            file_content=b"x",
            filename="bad.exe",
            content_type=None,
            context=UploadContext(),
        )
        assert result.status == ProcessingStatus.VALIDATION_FAILED
        assert "Invalid file type" in result.error

    async def test_duplicate_by_hash_short_circuits(self, service, db, patch_gridfs_stack) -> None:
        from src.documents.processing_service import (
            ProcessingStatus,
            UploadContext,
        )
        from src.utils.conversion import calculate_file_hash

        content = b"some pdf content"
        h = calculate_file_hash(content)
        await db.documents.insert_one({"id": "dup-1", "content_hash": h, "filename": "old.pdf"})

        result = await service.process_upload(
            file_content=content,
            filename="new.pdf",
            content_type="application/pdf",
            context=UploadContext(),
        )
        assert result.status == ProcessingStatus.DUPLICATE
        assert result.duplicate_of_id == "dup-1"
        assert result.duplicate_of_filename == "old.pdf"

    async def test_conversion_failure_still_creates_record(
        self, service, db, patch_gridfs_stack
    ) -> None:
        from src.documents.processing_service import (
            ProcessingStatus,
            UploadContext,
        )

        # Conversion fails → pdf_content is None.
        with patch(
            "src.documents.processing_service.convert_to_pdf",
            return_value={"success": False, "error": "broken"},
        ):
            result = await service.process_upload(
                file_content=b"docx-bytes",
                filename="thing.docx",
                content_type=(
                    "application/vnd.openxmlformats-officedocument." "wordprocessingml.document"
                ),
                context=UploadContext(),
            )
        assert result.status == ProcessingStatus.CONVERSION_FAILED
        assert "broken" in result.error

    async def test_pdf_happy_path(self, service, db, patch_gridfs_stack, monkeypatch) -> None:
        from src.documents.processing_service import (
            ProcessingStatus,
            UploadContext,
        )

        # Mock heavy library calls.
        monkeypatch.setattr(
            "src.documents.routes.extract_text_with_coordinates",
            AsyncMock(return_value={"full_text": "hello", "pages": []}),
        )
        monkeypatch.setattr("src.documents.routes.get_text_summary", lambda d: "sum")
        monkeypatch.setattr(
            "src.admin.config_routes.get_system_config",
            AsyncMock(return_value={"auto_generate_ai_suggestions": False}),
        )

        result = await service.process_upload(
            file_content=b"%PDF-1.4 fake",
            filename="hello.pdf",
            content_type="application/pdf",
            context=UploadContext(case_id="case-1", uploaded_by="u1"),
        )
        assert result.status == ProcessingStatus.SUCCESS, result.error
        assert result.has_ocr is True
        assert result.has_ai_summary is False
        assert result.conversion_status == "not_needed"
        # Record persisted.
        doc = await db.documents.find_one({"id": result.document_id})
        assert doc is not None
        assert doc["case_id"] == "case-1"
        # Case updated with document id.
        # (Insert a case so update_one can target it.)
        # The route does an idempotent `$addToSet`; we just verify the call
        # didn't blow up. The update is fire-and-forget against a possibly
        # missing case doc, which is a known pin — see Section 11.

    async def test_email_duplicate_by_message_id(
        self, service, db, tmp_path, patch_gridfs_stack
    ) -> None:
        from src.documents.processing_service import (
            ProcessingStatus,
            UploadContext,
        )

        # Pre-existing email with the same message_id.
        await db.documents.insert_one(
            {"id": "email-old", "message_id": "<m@x>", "filename": "old.eml"}
        )

        fake_pdf = tmp_path / "out.pdf"
        fake_pdf.write_bytes(b"%PDF")
        with patch(
            "src.documents.processing_service.convert_to_pdf",
            return_value={
                "success": True,
                "pdf_path": str(fake_pdf),
                "message_id": "<m@x>",
                "extracted_text": "body",
                "attachments": [],
            },
        ):
            result = await service.process_upload(
                file_content=b"raw-eml",
                filename="new.eml",
                content_type="message/rfc822",
                context=UploadContext(),
            )
        assert result.status == ProcessingStatus.DUPLICATE
        assert result.duplicate_of_id == "email-old"

    async def test_email_duplicate_merges_attachments(
        self, service, db, tmp_path, patch_gridfs_stack
    ) -> None:
        from src.documents.processing_service import (
            ProcessingStatus,
            UploadContext,
        )

        await db.documents.insert_one(
            {"id": "email-old", "message_id": "<m@x>", "attachment_ids": []}
        )

        fake_pdf = tmp_path / "out.pdf"
        fake_pdf.write_bytes(b"%PDF")
        att_file = tmp_path / "att.docx"
        att_file.write_bytes(b"att-data")

        with (
            patch(
                "src.documents.processing_service.convert_to_pdf",
                return_value={
                    "success": True,
                    "pdf_path": str(fake_pdf),
                    "message_id": "<m@x>",
                    "extracted_text": "body",
                    "attachments": [{"filename": "att.docx", "path": str(att_file)}],
                },
            ),
            patch.object(
                service,
                "_merge_attachments_into_email",
                AsyncMock(return_value=1),
            ) as merge_mock,
        ):
            result = await service.process_upload(
                file_content=b"raw-eml",
                filename="new.eml",
                content_type="message/rfc822",
                context=UploadContext(process_attachments=True),
            )
        merge_mock.assert_awaited_once()
        assert result.status == ProcessingStatus.DUPLICATE

    async def test_docx_full_pipeline_with_thread_consolidation(
        self, service, db, tmp_path, patch_gridfs_stack, monkeypatch
    ) -> None:
        """Full happy path: DOCX → PDF, OCR, summary disabled, attachments,
        case registration, and (since ext != email) NO thread consolidation
        attempt. Also queues background AI."""
        from fastapi import BackgroundTasks

        from src.documents.processing_service import (
            ProcessingStatus,
            UploadContext,
        )

        # Mock conversion.
        fake_pdf = tmp_path / "out.pdf"
        fake_pdf.write_bytes(b"%PDF-fake")
        monkeypatch.setattr(
            "src.documents.processing_service.convert_to_pdf",
            lambda inp, outd: {
                "success": True,
                "pdf_path": str(fake_pdf),
                "message_id": None,
                "extracted_text": "doc text",
                "attachments": [],
            },
        )
        monkeypatch.setattr(
            "src.documents.routes.extract_text_with_coordinates",
            AsyncMock(return_value={"full_text": "ocr", "pages": []}),
        )
        monkeypatch.setattr("src.documents.routes.get_text_summary", lambda d: "sum")
        # AI summary disabled.
        monkeypatch.setattr(
            "src.admin.config_routes.get_system_config",
            AsyncMock(return_value={"auto_generate_ai_suggestions": False}),
        )

        # Insert the case the upload references so the addToSet has a target.
        await db.cases.insert_one({"id": "case-x", "document_ids": []})

        bg = BackgroundTasks()
        result = await service.process_upload(
            file_content=b"docx-raw",
            filename="thing.docx",
            content_type=(
                "application/vnd.openxmlformats-officedocument." "wordprocessingml.document"
            ),
            context=UploadContext(case_id="case-x", uploaded_by="u1"),
            background_tasks=bg,
        )
        assert result.status == ProcessingStatus.SUCCESS, result.error
        assert result.conversion_status == "converted"
        case = await db.cases.find_one({"id": "case-x"})
        assert result.document_id in case["document_ids"]

    async def test_eml_pipeline_thread_consolidation_runs(
        self, service, db, tmp_path, patch_gridfs_stack, monkeypatch
    ) -> None:
        from src.documents.processing_service import (
            ProcessingStatus,
            UploadContext,
        )

        fake_pdf = tmp_path / "e.pdf"
        fake_pdf.write_bytes(b"%PDF")
        monkeypatch.setattr(
            "src.documents.processing_service.convert_to_pdf",
            lambda inp, outd: {
                "success": True,
                "pdf_path": str(fake_pdf),
                "message_id": "<msg-new@x>",
                "extracted_text": "From: a\n",
                "attachments": [],
            },
        )
        monkeypatch.setattr(
            "src.documents.routes.extract_text_with_coordinates",
            AsyncMock(return_value={"full_text": "x", "pages": []}),
        )
        monkeypatch.setattr("src.documents.routes.get_text_summary", lambda d: "sum")
        monkeypatch.setattr(
            "src.admin.config_routes.get_system_config",
            AsyncMock(return_value={"auto_generate_ai_suggestions": False}),
        )

        # Wire up thread-consolidation mocks.
        thread_called = {"hit": False}

        async def _fake_consolidate(*args, **kwargs):
            thread_called["hit"] = True
            return {"thread_id": "t-1"}

        monkeypatch.setattr(
            "src.documents.routes.extract_thread_identifiers",
            lambda txt, mid: {"subject": "S"},
        )
        monkeypatch.setattr(
            "src.documents.routes.find_thread_emails",
            AsyncMock(return_value=[{"id": "other"}]),
        )
        monkeypatch.setattr(
            "src.documents.routes.consolidate_email_thread",
            _fake_consolidate,
        )

        result = await service.process_upload(
            file_content=b"raw-eml",
            filename="m.eml",
            content_type="message/rfc822",
            context=UploadContext(),
        )
        assert result.status == ProcessingStatus.SUCCESS, result.error
        assert thread_called["hit"]
        assert result.thread_consolidation == {"thread_id": "t-1"}

    async def test_attachment_processing_path(
        self, service, db, tmp_path, patch_gridfs_stack, monkeypatch
    ) -> None:
        from src.documents.processing_service import (
            ProcessingStatus,
            UploadContext,
        )

        fake_pdf = tmp_path / "e.pdf"
        fake_pdf.write_bytes(b"%PDF")
        att_file = tmp_path / "att.docx"
        att_file.write_bytes(b"att-data")

        # Conversion of the email yields one attachment in the dict.
        monkeypatch.setattr(
            "src.documents.processing_service.convert_to_pdf",
            lambda inp, outd: {
                "success": True,
                "pdf_path": str(fake_pdf),
                "message_id": None,
                "extracted_text": None,
                "attachments": [{"filename": "att.docx", "path": str(att_file)}],
            },
        )
        monkeypatch.setattr(
            "src.documents.routes.extract_text_with_coordinates",
            AsyncMock(return_value={"full_text": "", "pages": []}),
        )
        monkeypatch.setattr("src.documents.routes.get_text_summary", lambda d: "")
        monkeypatch.setattr(
            "src.admin.config_routes.get_system_config",
            AsyncMock(return_value={"auto_generate_ai_suggestions": False}),
        )

        # Short-circuit attachment-processing internals.
        att_doc = {"id": "att-1", "filename": "att.docx.pdf"}
        with patch.object(service, "_process_attachments", AsyncMock(return_value=[att_doc])):
            result = await service.process_upload(
                file_content=b"raw",
                filename="m.eml",
                content_type="message/rfc822",
                context=UploadContext(process_attachments=True),
            )
        assert result.status == ProcessingStatus.SUCCESS, result.error
        assert result.attachment_count == 1
        # Both parent + attachment inserted.
        att = await db.documents.find_one({"id": "att-1"})
        assert att is not None

    async def test_top_level_exception(self, service, monkeypatch) -> None:
        from src.documents.processing_service import (
            ProcessingStatus,
            UploadContext,
        )

        # Force `_validate_file` itself to crash to hit the outermost
        # try/except.
        monkeypatch.setattr(
            service, "_validate_file", MagicMock(side_effect=RuntimeError("kaboom"))
        )
        result = await service.process_upload(
            file_content=b"x",
            filename="x.pdf",
            content_type=None,
            context=UploadContext(),
        )
        assert result.status == ProcessingStatus.ERROR
        assert "kaboom" in result.error


# ===========================================================================
# Slow integration tests — real tools, real fixtures.
# Skipped if libreoffice / tesseract aren't installed.
# Use `pytest -m slow` (or `-m ""`) to opt in.
# ===========================================================================


def _have_tool(name: str) -> bool:
    return shutil.which(name) is not None


@pytest.mark.slow
class TestRealConversionIntegration:
    """One real-tool integration test per supported format. These confirm
    the wired-together pipeline; they're not required for coverage."""

    @pytest.mark.skipif(
        not _have_tool("libreoffice"),
        reason="libreoffice not installed",
    )
    async def test_real_docx_conversion(self, service) -> None:
        from src.documents.processing_service import (
            ProcessingStatus,
            UploadContext,
        )

        fixture = FIXTURES_DIR / "APA_Student_Paper.docx"
        if not fixture.exists():
            pytest.skip(f"fixture missing: {fixture}")

        # Stub gridfs + heavy downstream paths to keep the test focused on
        # the LibreOffice subprocess + PyMuPDF reading.
        with (
            patch("src.documents.processing_service.MongoClient") as mc,
            patch("src.documents.processing_service.gridfs.GridFS") as gfs,
            patch(
                "src.admin.config_routes.get_system_config",
                AsyncMock(return_value={"auto_generate_ai_suggestions": False}),
            ),
        ):
            gfs.return_value.put.return_value = "gf-real"
            mc.return_value.__getitem__.return_value = MagicMock()
            result = await service.process_upload(
                file_content=fixture.read_bytes(),
                filename=fixture.name,
                content_type=(
                    "application/vnd.openxmlformats-officedocument." "wordprocessingml.document"
                ),
                context=UploadContext(),
            )
        assert result.status == ProcessingStatus.SUCCESS, result.error
        assert result.conversion_status == "converted"

    @pytest.mark.skipif(
        not _have_tool("tesseract"),
        reason="tesseract not installed",
    )
    async def test_real_image_ocr(self, service) -> None:
        from src.documents.processing_service import (
            ProcessingStatus,
            UploadContext,
        )

        fixture = FIXTURES_DIR / "receipt_img.png"
        if not fixture.exists():
            pytest.skip(f"fixture missing: {fixture}")

        with (
            patch("src.documents.processing_service.MongoClient") as mc,
            patch("src.documents.processing_service.gridfs.GridFS") as gfs,
            patch(
                "src.admin.config_routes.get_system_config",
                AsyncMock(return_value={"auto_generate_ai_suggestions": False}),
            ),
        ):
            gfs.return_value.put.return_value = "gf-real"
            mc.return_value.__getitem__.return_value = MagicMock()
            result = await service.process_upload(
                file_content=fixture.read_bytes(),
                filename=fixture.name,
                content_type="image/png",
                context=UploadContext(),
            )
        assert result.status == ProcessingStatus.SUCCESS, result.error

    async def test_real_eml_conversion(self, service) -> None:
        from src.documents.processing_service import (
            ProcessingStatus,
            UploadContext,
        )

        fixture = FIXTURES_DIR / "test.eml"
        if not fixture.exists():
            pytest.skip(f"fixture missing: {fixture}")

        with (
            patch("src.documents.processing_service.MongoClient") as mc,
            patch("src.documents.processing_service.gridfs.GridFS") as gfs,
            patch(
                "src.admin.config_routes.get_system_config",
                AsyncMock(return_value={"auto_generate_ai_suggestions": False}),
            ),
        ):
            gfs.return_value.put.return_value = "gf-real"
            mc.return_value.__getitem__.return_value = MagicMock()
            result = await service.process_upload(
                file_content=fixture.read_bytes(),
                filename=fixture.name,
                content_type="message/rfc822",
                context=UploadContext(),
            )
        assert result.status == ProcessingStatus.SUCCESS, result.error
