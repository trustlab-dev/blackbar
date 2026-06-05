"""Integration tests for `src.documents.routes` core CRUD endpoints.

Phase 2.3.D. Target >=80% line coverage on `src.documents.routes` —
9 core endpoints registered on the documents router:

    GET    /                              list_documents
    GET    /{document_id}                 get_document            (binary PDF)
    GET    /{document_id}/download        download_original_file  (binary)
    GET    /{document_id}/metadata        get_document_metadata
    GET    /{document_id}/export          export_document_with_redactions (binary PDF)
    GET    /{document_id}/processing_status get_processing_status
    GET    /{document_id}/audit-logs      get_document_audit_logs
    POST   /                              upload_document
    DELETE /{document_id}                 delete_document

The upload endpoint delegates to `DocumentProcessingService.process_upload`,
which has its own dedicated test file in `test_processing_service.py` —
here we mock the service to assert the route's response-handling branches
(success / duplicate / validation_failed / conversion_failed / error).

Auth model:
- Most read endpoints accept `owner/admin/analyst/user` (and some also
  `guest`).
- DELETE is restricted to `owner/admin`.
- audit-logs to `owner/admin/analyst` (not user/guest).
- For non-admin/owner reads, `check_document_access` runs and applies
  shared_with (guest) / case-team (others) gates.

Source-API findings pinned (audit Section 11 candidates):
- `export_document_with_redactions` catches all exceptions broadly and
  returns 500 — including the case where `doc["content"]` is missing.
  A document without embedded PDF content (e.g. GridFS-only) cannot
  currently be exported via this endpoint. Pinned below.
- `get_document_audit_logs` and `delete_document` do NOT use Pydantic
  validation on the path param — non-existent ids just return 404.
- `delete_document` calls `db.cases.update_one` to pull document_id even
  if there's no `case_id` (it short-circuits with an `if case_id`).
- Listed documents intentionally exclude `content` field but the
  response shape only surfaces a minimal subset — many DB fields (eg
  `case_id`, `file_hash`, `extracted_text`) are not exposed by /list.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from motor.motor_asyncio import AsyncIOMotorDatabase

from tests.factories import make_case, make_document

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_routes_db(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase, app):
    """Rebind the documents/routes.py `get_db` to the per-test motor db,
    plus the `src.dependencies.users` / `src.database.users` symbols so
    `get_current_user`'s user lookup uses the test DB.

    documents/routes.py uses `Depends(get_db)` for all its endpoints; the
    `app.dependency_overrides` mechanism covers them cleanly. We don't
    need to patch any module-level `db` symbol since the route module
    captures one via `from ..database import db` at line 11 but does not
    USE it in the 9 endpoints under test (only the merge_attachments /
    aggregate_attachments helpers use it, and those are exercised by
    upload flow tests in test_processing_service.py).
    """
    import src.database as db_mod
    import src.dependencies as deps_mod
    from src.documents import routes as documents_routes

    async def _override_get_db():
        return db

    app.dependency_overrides[documents_routes.get_db] = _override_get_db
    monkeypatch.setattr(deps_mod, "users", db.users)
    monkeypatch.setattr(db_mod, "users", db.users)
    # Also patch the route module's captured `db` for the helper fns
    monkeypatch.setattr(documents_routes, "db", db)

    yield db

    app.dependency_overrides.pop(documents_routes.get_db, None)


def _make_minimal_pdf_bytes() -> bytes:
    """Build a tiny valid 1-page PDF in memory using PyMuPDF."""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 50), "Hello world test PDF", fontsize=10)
    out = doc.tobytes()
    doc.close()
    return out


# ---------------------------------------------------------------------------
# GET /  list_documents
# ---------------------------------------------------------------------------


class TestListDocuments:
    async def test_admin_lists_all_documents(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        # Seed two documents
        doc1 = make_document(
            filename="alpha.pdf",
            mime_type="application/pdf",
            redactions=[{"x": 1, "y": 2}],
            has_attachments=True,
        )
        doc2 = make_document(
            filename="beta.docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        await db.documents.insert_many([doc1, doc2])

        r = await client.get("/api/v1/documents/")
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body) == 2
        # Pinned response shape — only these fields are returned
        for item in body:
            assert set(item.keys()) == {
                "id",
                "filename",
                "redactions",
                "uploadDate",
                "mimeType",
                "hasAttachments",
            }
        # Verify mapping (redactions is a COUNT, not array)
        by_name = {x["filename"]: x for x in body}
        assert by_name["alpha.pdf"]["redactions"] == 1
        assert by_name["alpha.pdf"]["hasAttachments"] is True
        assert by_name["alpha.pdf"]["mimeType"] == "application/pdf"
        assert by_name["beta.docx"]["redactions"] == 0
        assert by_name["beta.docx"]["hasAttachments"] is False

    async def test_list_excludes_binary_content(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Verify the projection drops `content` — wire bytes should never
        leak through the list endpoint."""
        client = await authed_client_factory(role="admin")
        doc = make_document(content=b"BINARY-DATA-DO-NOT-LEAK")
        await db.documents.insert_one(doc)
        r = await client.get("/api/v1/documents/")
        assert r.status_code == 200
        assert "content" not in r.json()[0]
        assert "BINARY-DATA-DO-NOT-LEAK" not in r.text

    async def test_list_empty_returns_empty_array(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/documents/")
        assert r.status_code == 200
        assert r.json() == []

    async def test_list_unauthenticated_returns_401(self, client, patch_routes_db) -> None:
        r = client.get("/api/v1/documents/")
        assert r.status_code == 401

    async def test_list_guest_forbidden(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Guest role is NOT in the list endpoint's allowed roles."""
        client = await authed_client_factory(role="guest")
        r = await client.get("/api/v1/documents/")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# GET /{document_id}  get_document (PDF content)
# ---------------------------------------------------------------------------


class TestGetDocument:
    async def test_admin_gets_pdf_content_legacy_embedded(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Document with `content` field (legacy storage)."""
        client = await authed_client_factory(role="admin")
        pdf = b"%PDF-1.4 minimal"
        doc = make_document(content=pdf)
        await db.documents.insert_one(doc)
        r = await client.get(f"/api/v1/documents/{doc['id']}")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert r.content == pdf

    async def test_get_document_not_found_returns_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/documents/ghost")
        assert r.status_code == 404
        assert "Document not found" in r.text

    async def test_get_document_no_content_returns_404(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Doc exists but has neither GridFS pointer nor embedded content."""
        client = await authed_client_factory(role="admin")
        doc = make_document()  # no content
        await db.documents.insert_one(doc)
        r = await client.get(f"/api/v1/documents/{doc['id']}")
        assert r.status_code == 404
        assert "Document content not found" in r.text

    async def test_guest_with_share_can_access(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="guest", email="gst-doc@example.test")
        me = await db.users.find_one({"email": "gst-doc@example.test"})
        case = make_case()
        await db.cases.insert_one(case)
        doc = make_document(
            case_id=case["id"],
            content=b"%PDF-1.4 ok",
            shared_with=[{"user_id": me["id"]}],
        )
        await db.documents.insert_one(doc)
        r = await client.get(f"/api/v1/documents/{doc['id']}")
        assert r.status_code == 200

    async def test_guest_without_share_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="guest", email="gst2-doc@example.test")
        case = make_case()
        await db.cases.insert_one(case)
        doc = make_document(case_id=case["id"], content=b"x")
        await db.documents.insert_one(doc)
        r = await client.get(f"/api/v1/documents/{doc['id']}")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# GET /{document_id}/download  download_original_file
# ---------------------------------------------------------------------------


class TestDownloadOriginalFile:
    async def test_admin_downloads_legacy_pdf(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """No `original_file_id` / no `content_file_id` -> falls through
        to the legacy embedded content branch."""
        client = await authed_client_factory(role="admin")
        doc = make_document(filename="alpha.pdf", content=b"%PDF-1.4 legacy")
        await db.documents.insert_one(doc)
        r = await client.get(f"/api/v1/documents/{doc['id']}/download")
        assert r.status_code == 200, r.text
        assert r.content == b"%PDF-1.4 legacy"
        assert r.headers["content-type"] == "application/pdf"
        assert 'filename="alpha.pdf"' in r.headers["content-disposition"]

    async def test_download_document_not_found(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/documents/ghost/download")
        assert r.status_code == 404

    async def test_download_no_content_returns_404(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Doc exists but has neither original_file_id, content_file_id,
        nor embedded content -> 404."""
        client = await authed_client_factory(role="admin")
        doc = make_document()
        await db.documents.insert_one(doc)
        r = await client.get(f"/api/v1/documents/{doc['id']}/download")
        assert r.status_code == 404

    async def test_download_guest_without_share_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="guest", email="gst-dl@example.test")
        case = make_case()
        await db.cases.insert_one(case)
        doc = make_document(case_id=case["id"], content=b"%PDF-1.4")
        await db.documents.insert_one(doc)
        r = await client.get(f"/api/v1/documents/{doc['id']}/download")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# GET /{document_id}/metadata  get_document_metadata
# ---------------------------------------------------------------------------


class TestGetDocumentMetadata:
    async def test_admin_gets_metadata(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        doc = make_document(
            filename="meta.pdf",
            mime_type="application/pdf",
            size=1234,
            redactions=[{"x": 1, "y": 2}],
            text_summary="A short summary",
            text_data={"full_text": "Hello", "pages": [{"page": 1, "text": "Hello"}]},
        )
        await db.documents.insert_one(doc)
        r = await client.get(f"/api/v1/documents/{doc['id']}/metadata")
        assert r.status_code == 200, r.text
        body = r.json()
        # Pinned shape
        assert set(body.keys()) == {
            "id",
            "filename",
            "redactions",
            "text_data",
            "text_summary",
            "mime_type",
            "size",
        }
        assert body["filename"] == "meta.pdf"
        assert body["redactions"] == [{"x": 1, "y": 2}]
        assert body["text_data"] == {
            "full_text": "Hello",
            "pages": [{"page": 1, "text": "Hello"}],
        }
        assert body["text_summary"] == "A short summary"
        assert body["mime_type"] == "application/pdf"
        assert body["size"] == 1234

    async def test_metadata_synthesizes_text_data_from_extracted_text(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """If `text_data` is missing but `extracted_text` is present, the
        route synthesizes a compatibility `text_data` dict."""
        client = await authed_client_factory(role="admin")
        doc = make_document(extracted_text="Plain text extraction")
        await db.documents.insert_one(doc)
        r = await client.get(f"/api/v1/documents/{doc['id']}/metadata")
        assert r.status_code == 200
        body = r.json()
        assert body["text_data"] == {
            "full_text": "Plain text extraction",
            "pages": [],
        }

    async def test_metadata_not_found(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/documents/ghost/metadata")
        assert r.status_code == 404

    async def test_metadata_guest_with_share_allowed(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="guest", email="gst-meta@example.test")
        me = await db.users.find_one({"email": "gst-meta@example.test"})
        case = make_case()
        await db.cases.insert_one(case)
        doc = make_document(
            case_id=case["id"],
            shared_with=[{"user_id": me["id"]}],
        )
        await db.documents.insert_one(doc)
        r = await client.get(f"/api/v1/documents/{doc['id']}/metadata")
        assert r.status_code == 200

    async def test_metadata_user_off_team_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="user", email="off-meta@example.test")
        case = make_case(
            case_team=[{"user_id": "someone-else", "role": "analyst", "status": "active"}]
        )
        await db.cases.insert_one(case)
        doc = make_document(case_id=case["id"])
        await db.documents.insert_one(doc)
        r = await client.get(f"/api/v1/documents/{doc['id']}/metadata")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# GET /{document_id}/export  export_document_with_redactions
# ---------------------------------------------------------------------------


class TestExportDocumentWithRedactions:
    async def test_export_no_redactions_returns_original(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        pdf = _make_minimal_pdf_bytes()
        doc = make_document(filename="myfile.pdf", content=pdf)
        await db.documents.insert_one(doc)
        r = await client.get(f"/api/v1/documents/{doc['id']}/export")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert r.content == pdf
        # Filename contains NOREDACTIONS marker + first-8 of doc id
        cd = r.headers["content-disposition"]
        assert "NOREDACTIONS" in cd
        assert doc["id"][:8] in cd

    async def test_export_with_redactions_applies_them(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Verify the export pipeline runs PyMuPDF redaction application
        and returns a new PDF with REDACTED in filename. We don't assert
        exact byte equality because PyMuPDF rewrites the document, but
        we DO confirm the response is a valid PDF and not the original."""
        client = await authed_client_factory(role="admin")
        pdf = _make_minimal_pdf_bytes()
        doc = make_document(
            filename="confidential.pdf",
            content=pdf,
            redactions=[
                {
                    "page": 1,
                    "x": 10,
                    "y": 10,
                    "width": 50,
                    "height": 10,
                    "status": "approved",
                    "reason": "s.22",
                },
                # Rejected redaction should be SKIPPED
                {
                    "page": 1,
                    "x": 0,
                    "y": 0,
                    "width": 10,
                    "height": 10,
                    "status": "rejected",
                },
                # Out-of-range page should be SKIPPED
                {
                    "page": 999,
                    "x": 0,
                    "y": 0,
                    "width": 10,
                    "height": 10,
                    "status": "approved",
                },
            ],
        )
        await db.documents.insert_one(doc)
        r = await client.get(f"/api/v1/documents/{doc['id']}/export")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF")
        cd = r.headers["content-disposition"]
        assert "REDACTED" in cd
        assert doc["id"][:8] in cd
        # The export rewrote the PDF: different bytes from input
        assert r.content != pdf

    async def test_export_not_found(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Phase 4 Batch 4.4 (audit B39): missing-document path now
        surfaces the intentional 404. Previously the broad
        `except Exception` swallowed it into a 500."""
        client = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/documents/ghost/export")
        assert r.status_code == 404

    async def test_export_guest_forbidden_by_role(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Export endpoint role gate excludes guest (unlike get/metadata)."""
        client = await authed_client_factory(role="guest")
        r = await client.get("/api/v1/documents/anyid/export")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# POST /  upload_document
# ---------------------------------------------------------------------------


class TestUploadDocument:
    """Upload route delegates almost everything to
    `DocumentProcessingService.process_upload` — which has full coverage
    in `test_processing_service.py`. Here we mock the service to assert
    the route's branch logic for each ProcessingStatus return."""

    async def test_upload_success_response_shape(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        from src.documents.processing_service import ProcessingResult, ProcessingStatus

        mock_result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            document_id="abc-123",
            filename="upload.pdf",
            attachment_count=2,
            has_ocr=True,
            has_ai_summary=False,
            thread_consolidation={"merged": 3},
            warnings=["pdf was OCR'd"],
        )

        with patch(
            "src.documents.processing_service.DocumentProcessingService.process_upload",
            new=AsyncMock(return_value=mock_result),
        ):
            r = await client.post(
                "/api/v1/documents/",
                files={"file": ("upload.pdf", b"%PDF-1.4", "application/pdf")},
            )

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["id"] == "abc-123"
        assert body["filename"] == "upload.pdf"
        assert body["attachments"] == 2
        assert body["has_ocr"] is True
        assert body["has_ai_summary"] is False
        assert body["thread_consolidation"] == {"merged": 3}
        assert body["warnings"] == ["pdf was OCR'd"]

    async def test_upload_duplicate_returns_marker(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        from src.documents.processing_service import ProcessingResult, ProcessingStatus

        mock_result = ProcessingResult(
            status=ProcessingStatus.DUPLICATE,
            is_duplicate=True,
            duplicate_of_id="existing-id",
            duplicate_of_filename="orig.pdf",
        )
        with patch(
            "src.documents.processing_service.DocumentProcessingService.process_upload",
            new=AsyncMock(return_value=mock_result),
        ):
            r = await client.post(
                "/api/v1/documents/",
                files={"file": ("dup.pdf", b"%PDF-1.4", "application/pdf")},
            )

        assert r.status_code == 200
        body = r.json()
        assert body["is_duplicate"] is True
        assert body["duplicate_of_id"] == "existing-id"
        assert body["duplicate_of_filename"] == "orig.pdf"
        assert body["upload_date"] is None

    async def test_upload_validation_failed_returns_400(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        from src.documents.processing_service import ProcessingResult, ProcessingStatus

        mock_result = ProcessingResult(
            status=ProcessingStatus.VALIDATION_FAILED,
            message="Invalid file type '.exe'",
        )
        with patch(
            "src.documents.processing_service.DocumentProcessingService.process_upload",
            new=AsyncMock(return_value=mock_result),
        ):
            r = await client.post(
                "/api/v1/documents/",
                files={"file": ("bad.exe", b"MZ", "application/octet-stream")},
            )

        assert r.status_code == 400
        # error_handler wraps detail string in `error.message` envelope
        assert "Invalid file type" in r.text

    async def test_upload_conversion_failed_returns_200_with_warning(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Conversion failure is not fatal — the document is still created
        and the response includes a warning string."""
        client = await authed_client_factory(role="admin")
        from src.documents.processing_service import ProcessingResult, ProcessingStatus

        mock_result = ProcessingResult(
            status=ProcessingStatus.CONVERSION_FAILED,
            document_id="part-123",
            filename="weird.docx",
            error="libreoffice timed out",
            attachment_count=0,
        )
        with patch(
            "src.documents.processing_service.DocumentProcessingService.process_upload",
            new=AsyncMock(return_value=mock_result),
        ):
            r = await client.post(
                "/api/v1/documents/",
                files={
                    "file": (
                        "weird.docx",
                        b"PK\x03\x04 fake docx",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                },
            )

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["id"] == "part-123"
        assert body["warning"] == "libreoffice timed out"
        assert "warning" in body["message"].lower()

    async def test_upload_error_returns_500(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        from src.documents.processing_service import ProcessingResult, ProcessingStatus

        mock_result = ProcessingResult(
            status=ProcessingStatus.ERROR,
            error="GridFS write failed",
        )
        with patch(
            "src.documents.processing_service.DocumentProcessingService.process_upload",
            new=AsyncMock(return_value=mock_result),
        ):
            r = await client.post(
                "/api/v1/documents/",
                files={"file": ("ok.pdf", b"%PDF-1.4", "application/pdf")},
            )

        assert r.status_code == 500
        assert "GridFS" in r.text

    async def test_upload_guest_forbidden(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="guest")
        r = await client.post(
            "/api/v1/documents/",
            files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")},
        )
        assert r.status_code == 403

    async def test_upload_unauthenticated_returns_401(self, client, patch_routes_db) -> None:
        r = client.post(
            "/api/v1/documents/",
            files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")},
        )
        assert r.status_code == 401

    async def test_upload_real_sample_pdf_with_case_id(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        fixtures_dir,
    ) -> None:
        """End-to-end-ish test: mock only the inner service to verify the
        FastAPI form-handling extracts both `file` and `case_id` correctly.
        This pins the route's UploadFile + Form pluming."""
        client = await authed_client_factory(role="admin")
        from src.documents.processing_service import ProcessingResult, ProcessingStatus

        captured: dict[str, Any] = {}

        async def fake_process_upload(
            self, *, file_content, filename, content_type, context, background_tasks=None
        ):
            captured["filename"] = filename
            captured["case_id"] = context.case_id
            captured["uploaded_by"] = context.uploaded_by
            captured["content_type"] = content_type
            captured["size"] = len(file_content)
            return ProcessingResult(
                status=ProcessingStatus.SUCCESS,
                document_id="doc-1",
                filename=filename,
            )

        sample = fixtures_dir / "FOIPPA_Test_Document.docx"
        with patch(
            "src.documents.processing_service.DocumentProcessingService.process_upload",
            new=fake_process_upload,
        ):
            with open(sample, "rb") as f:
                r = await client.post(
                    "/api/v1/documents/",
                    files={
                        "file": (
                            "FOIPPA_Test_Document.docx",
                            f.read(),
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        )
                    },
                    data={"case_id": "case-XYZ"},
                )

        assert r.status_code == 200, r.text
        assert captured["filename"] == "FOIPPA_Test_Document.docx"
        assert captured["case_id"] == "case-XYZ"
        # Uploaded_by is the seeded admin user's id (uuid)
        assert captured["uploaded_by"]


# ---------------------------------------------------------------------------
# DELETE /{document_id}  delete_document
# ---------------------------------------------------------------------------


class TestDeleteDocument:
    async def test_admin_deletes_doc_and_attachments(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        case = make_case()
        await db.cases.insert_one(case)
        att1 = make_document(parent_document_id="parent-1")
        att2 = make_document(parent_document_id="parent-1")
        doc = make_document(id="parent-1", case_id=case["id"])
        await db.documents.insert_many([doc, att1, att2])
        await db.cases.update_one({"id": case["id"]}, {"$set": {"document_ids": ["parent-1"]}})

        r = await client.delete("/api/v1/documents/parent-1")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["message"] == "Document deleted successfully"
        assert body["attachments_deleted"] == 2
        # Verify gone from DB
        assert await db.documents.find_one({"id": "parent-1"}) is None
        # Case's document_ids was pulled
        updated_case = await db.cases.find_one({"id": case["id"]})
        assert "parent-1" not in updated_case.get("document_ids", [])

    async def test_delete_clears_email_supersession(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Deleting an email that superseded others clears the
        superseded_by reference on those siblings."""
        client = await authed_client_factory(role="admin")
        email_doc = make_document(id="email-1", mime_type="message/rfc822")
        sibling = make_document(
            id="email-2",
            mime_type="message/rfc822",
            superseded_by="email-1",
            thread_status="superseded",
        )
        await db.documents.insert_many([email_doc, sibling])

        r = await client.delete("/api/v1/documents/email-1")
        assert r.status_code == 200
        updated_sibling = await db.documents.find_one({"id": "email-2"})
        assert updated_sibling["thread_status"] == "active"
        assert updated_sibling["superseded_by"] is None

    async def test_delete_not_found(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.delete("/api/v1/documents/ghost")
        assert r.status_code == 404

    async def test_delete_user_role_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Only owner/admin can DELETE; 'user' role is rejected."""
        client = await authed_client_factory(role="user")
        doc = make_document()
        await db.documents.insert_one(doc)
        r = await client.delete(f"/api/v1/documents/{doc['id']}")
        assert r.status_code == 403

    async def test_delete_analyst_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Even analyst can't delete."""
        client = await authed_client_factory(role="analyst")
        doc = make_document()
        await db.documents.insert_one(doc)
        r = await client.delete(f"/api/v1/documents/{doc['id']}")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# GET /{document_id}/processing_status  get_processing_status
# ---------------------------------------------------------------------------


class TestGetProcessingStatus:
    async def test_returns_progress_for_doc_with_attachments(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        doc = make_document(total_attachments=4, processed_attachments=2)
        await db.documents.insert_one(doc)
        r = await client.get(f"/api/v1/documents/{doc['id']}/processing_status")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body == {
            "total_attachments": 4,
            "processed_attachments": 2,
            "is_complete": False,
            "progress_percentage": 50,
        }

    async def test_complete_when_processed_equals_total(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        doc = make_document(total_attachments=3, processed_attachments=3)
        await db.documents.insert_one(doc)
        r = await client.get(f"/api/v1/documents/{doc['id']}/processing_status")
        assert r.status_code == 200
        body = r.json()
        assert body["is_complete"] is True
        assert body["progress_percentage"] == 100

    async def test_legacy_doc_without_total_field(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Document predating the total_attachments feature: has_attachments
        False -> total=0 processed=0 is_complete=True."""
        client = await authed_client_factory(role="admin")
        doc = make_document(has_attachments=False)
        # Explicitly remove total_attachments if factory ever adds it
        doc.pop("total_attachments", None)
        doc.pop("processed_attachments", None)
        await db.documents.insert_one(doc)
        r = await client.get(f"/api/v1/documents/{doc['id']}/processing_status")
        assert r.status_code == 200
        body = r.json()
        assert body["total_attachments"] == 0
        assert body["is_complete"] is True
        assert body["progress_percentage"] == 100

    async def test_legacy_doc_with_attachment_ids_reports_count(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Phase 4 Batch 4.4 (audit B38): the projection now includes
        `has_attachments` and `attachment_ids`, so the legacy-doc
        fallback branch can actually count them. A legacy document
        with `has_attachments=True` and N attachment_ids now reports
        `total_attachments=N` and `processed_attachments=N` (the
        fallback assumes all-processed for pre-feature docs).

        Test flipped from the prior `_unreachable_branch` pin asserting
        total/processed both 0."""
        client = await authed_client_factory(role="admin")
        doc = make_document(
            has_attachments=True,
            attachment_ids=["a1", "a2", "a3"],
        )
        doc.pop("total_attachments", None)
        doc.pop("processed_attachments", None)
        await db.documents.insert_one(doc)
        r = await client.get(f"/api/v1/documents/{doc['id']}/processing_status")
        assert r.status_code == 200
        body = r.json()
        assert body["total_attachments"] == 3
        assert body["processed_attachments"] == 3
        assert body["is_complete"] is True
        assert body["progress_percentage"] == 100

    async def test_processing_status_not_found(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Phase 4 Batch 4.4 (audit B40): the missing-document path now
        surfaces the intentional 404; the broad-except wrap no longer
        swallows it into a 500."""
        client = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/documents/ghost/processing_status")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /{document_id}/audit-logs  get_document_audit_logs
# ---------------------------------------------------------------------------


class TestGetDocumentAuditLogs:
    async def test_admin_gets_filtered_audit_logs(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        # Build case with mixed audit log entries
        case_id = "case-audit"
        now = datetime.utcnow()
        older = now - timedelta(hours=1)
        case = make_case(
            id=case_id,
            audit_log=[
                {
                    "action": "document_uploaded",
                    "username": "alice",
                    "timestamp": now,
                    "details": {"document_id": "doc-X", "filename": "x.pdf"},
                },
                {
                    "action": "document_renamed",
                    "username": "bob",
                    "timestamp": older,
                    "details": {"document_id": "doc-X", "old": "a", "new": "x"},
                },
                # NOT related to doc-X
                {
                    "action": "case_assigned",
                    "username": "carol",
                    "timestamp": now,
                    "details": {"assignee": "carol"},
                },
                # Related via filename match (no document_id)
                {
                    "action": "document_viewed",
                    "username": "dave",
                    "timestamp": older,
                    "details": {"filename": "x.pdf"},
                },
            ],
        )
        await db.cases.insert_one(case)
        doc = make_document(id="doc-X", filename="x.pdf", case_id=case_id)
        await db.documents.insert_one(doc)

        r = await client.get("/api/v1/documents/doc-X/audit-logs")
        assert r.status_code == 200, r.text
        body = r.json()
        # Pinned envelope shape
        assert set(body.keys()) == {"logs"}
        logs = body["logs"]
        # 3 logs match (2 via document_id, 1 via filename); case_assigned excluded
        assert len(logs) == 3
        # Sorted newest first
        timestamps = [l["timestamp"] for l in logs]
        assert timestamps == sorted(timestamps, reverse=True)
        # Each entry has the documented shape
        for entry in logs:
            assert set(entry.keys()) == {"action", "username", "timestamp", "details"}

    async def test_audit_logs_doc_without_case_returns_empty(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        doc = make_document()  # no case_id
        await db.documents.insert_one(doc)
        r = await client.get(f"/api/v1/documents/{doc['id']}/audit-logs")
        assert r.status_code == 200
        assert r.json() == {"logs": []}

    async def test_audit_logs_doc_case_missing_returns_empty(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Doc references a case_id that doesn't exist -> empty logs."""
        client = await authed_client_factory(role="admin")
        doc = make_document(case_id="ghost-case")
        await db.documents.insert_one(doc)
        r = await client.get(f"/api/v1/documents/{doc['id']}/audit-logs")
        assert r.status_code == 200
        assert r.json() == {"logs": []}

    async def test_audit_logs_not_found(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/documents/ghost/audit-logs")
        assert r.status_code == 404

    async def test_audit_logs_user_role_forbidden(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """user/guest can't access audit logs (analyst+ only)."""
        client = await authed_client_factory(role="user")
        r = await client.get("/api/v1/documents/anyid/audit-logs")
        assert r.status_code == 403

    async def test_audit_logs_user_off_team_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Analyst who passes the role gate but isn't on the case team
        gets 403 via check_document_access."""
        client = await authed_client_factory(role="analyst", email="off-audit@example.test")
        case = make_case(
            case_team=[{"user_id": "someone-else", "role": "analyst", "status": "active"}],
        )
        await db.cases.insert_one(case)
        doc = make_document(case_id=case["id"])
        await db.documents.insert_one(doc)
        r = await client.get(f"/api/v1/documents/{doc['id']}/audit-logs")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Direct module-helper unit tests
# ---------------------------------------------------------------------------


class TestModuleHelpers:
    def test_sanitize_filename_strips_path_separators(self) -> None:
        from src.documents.routes import _sanitize_filename

        # Path separators get stripped via os.path.basename
        assert _sanitize_filename("../evil.pdf") == "evil.pdf"
        assert _sanitize_filename("/etc/passwd") == "passwd"

    def test_sanitize_filename_strips_newlines_and_nulls(self) -> None:
        from src.documents.routes import _sanitize_filename

        assert _sanitize_filename("foo\nbar.pdf") == "foobar.pdf"
        assert _sanitize_filename("foo\rbar.pdf") == "foobar.pdf"
        assert _sanitize_filename("foo\x00bar.pdf") == "foobar.pdf"

    def test_check_document_access_owner_admin_always_allowed(self) -> None:
        from src.documents.routes import check_document_access

        assert check_document_access({}, {"id": "u", "role": "owner"}) is True
        assert check_document_access({}, {"id": "u", "role": "admin"}) is True

    def test_check_document_access_guest_share_match(self) -> None:
        from src.documents.routes import check_document_access

        doc = {"shared_with": [{"user_id": "u1"}]}
        assert check_document_access(doc, {"id": "u1", "role": "guest"}) is True
        assert check_document_access(doc, {"id": "u2", "role": "guest"}) is False

    def test_check_document_access_no_case_for_non_special_role(self) -> None:
        from src.documents.routes import check_document_access

        # analyst with no case -> falls through to return False
        assert check_document_access({}, {"id": "u", "role": "analyst"}, case=None) is False

    def test_check_document_access_user_on_case_team(self) -> None:
        from src.documents.routes import check_document_access

        case = {"case_team": [{"user_id": "u1", "role": "analyst", "status": "active"}]}
        assert check_document_access({}, {"id": "u1", "role": "analyst"}, case=case) is True

    async def test_get_db_helper_returns_database(self, mongo_uri: str) -> None:
        """The module-level `get_db` helper is normally overridden in tests
        but we exercise it directly here for coverage."""
        from unittest.mock import MagicMock

        from src.documents.routes import get_db

        fake_request = MagicMock()
        result = await get_db(fake_request)
        assert result.name == "blackbar"


# ---------------------------------------------------------------------------
# GridFS branch coverage for get_document / download
# ---------------------------------------------------------------------------


class TestGridFSBranches:
    """Cover the GridFS read paths in get_document + download_original_file
    by patching the sync MongoClient + gridfs.GridFS used by those routes."""

    async def test_get_document_via_gridfs_success(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch,
    ) -> None:
        client = await authed_client_factory(role="admin")
        pdf_bytes = b"%PDF-1.4 from-gridfs"

        class FakeGridOut:
            def read(self):
                return pdf_bytes

            content_type = "application/pdf"

        class FakeGridFS:
            def __init__(self, _db):
                pass

            def get(self, fid):
                assert fid == "grid-content-id"
                return FakeGridOut()

        class FakeClient:
            def __init__(self, _uri):
                pass

            def __getitem__(self, _name):
                return MagicMock()

            def close(self):
                pass

        monkeypatch.setattr("pymongo.MongoClient", FakeClient)
        monkeypatch.setattr("gridfs.GridFS", FakeGridFS)

        doc = make_document(content_file_id="grid-content-id")
        await db.documents.insert_one(doc)
        r = await client.get(f"/api/v1/documents/{doc['id']}")
        assert r.status_code == 200
        assert r.content == pdf_bytes
        assert r.headers["content-type"] == "application/pdf"

    async def test_get_document_gridfs_failure_falls_back_to_legacy(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch,
    ) -> None:
        """GridFS raises -> route logs warning and falls through to
        legacy embedded content."""
        client = await authed_client_factory(role="admin")

        class FakeGridFS:
            def __init__(self, _db):
                pass

            def get(self, fid):
                raise RuntimeError("gridfs boom")

        class FakeClient:
            def __init__(self, _uri):
                pass

            def __getitem__(self, _name):
                return MagicMock()

            def close(self):
                pass

        monkeypatch.setattr("pymongo.MongoClient", FakeClient)
        monkeypatch.setattr("gridfs.GridFS", FakeGridFS)

        doc = make_document(content_file_id="will-fail", content=b"%PDF-legacy")
        await db.documents.insert_one(doc)
        r = await client.get(f"/api/v1/documents/{doc['id']}")
        assert r.status_code == 200
        assert r.content == b"%PDF-legacy"

    async def test_download_original_file_via_gridfs(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch,
    ) -> None:
        """Document with `original_file_id` -> returns original via GridFS
        with original_filename + content_type."""
        client = await authed_client_factory(role="admin")
        original_bytes = b"PK\x03\x04 docx content"

        class FakeGridOut:
            def read(self):
                return original_bytes

            content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

        class FakeGridFS:
            def __init__(self, _db):
                pass

            def get(self, fid):
                return FakeGridOut()

        class FakeClient:
            def __init__(self, _uri):
                pass

            def __getitem__(self, _name):
                return MagicMock()

            def close(self):
                pass

        monkeypatch.setattr("pymongo.MongoClient", FakeClient)
        monkeypatch.setattr("gridfs.GridFS", FakeGridFS)

        doc = make_document(
            filename="converted.pdf",
            original_file_id="orig-id",
            original_filename="report.docx",
        )
        await db.documents.insert_one(doc)
        r = await client.get(f"/api/v1/documents/{doc['id']}/download")
        assert r.status_code == 200, r.text
        assert r.content == original_bytes
        assert "report.docx" in r.headers["content-disposition"]
        assert "wordprocessing" in r.headers["content-type"]

    async def test_download_original_gridfs_failure_falls_back_to_pdf(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch,
    ) -> None:
        """If the original_file_id GridFS read fails, route falls through
        to PDF (which itself can be from another GridFS pointer or
        embedded content)."""
        client = await authed_client_factory(role="admin")

        class FakeGridFS:
            def __init__(self, _db):
                pass

            def get(self, fid):
                raise RuntimeError("missing")

        class FakeClient:
            def __init__(self, _uri):
                pass

            def __getitem__(self, _name):
                return MagicMock()

            def close(self):
                pass

        monkeypatch.setattr("pymongo.MongoClient", FakeClient)
        monkeypatch.setattr("gridfs.GridFS", FakeGridFS)

        doc = make_document(
            filename="fallback.pdf",
            original_file_id="bad-orig",
            content=b"%PDF-1.4 legacy fallback",
        )
        await db.documents.insert_one(doc)
        r = await client.get(f"/api/v1/documents/{doc['id']}/download")
        assert r.status_code == 200
        assert r.content == b"%PDF-1.4 legacy fallback"

    async def test_download_via_content_file_id_gridfs(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch,
    ) -> None:
        """Document with no original_file_id but has content_file_id
        (collection-link upload) -> downloads PDF via GridFS."""
        client = await authed_client_factory(role="admin")
        pdf_bytes = b"%PDF-1.4 from-content-grid"

        class FakeGridOut:
            def read(self):
                return pdf_bytes

            content_type = "application/pdf"

        class FakeGridFS:
            def __init__(self, _db):
                pass

            def get(self, fid):
                return FakeGridOut()

        class FakeClient:
            def __init__(self, _uri):
                pass

            def __getitem__(self, _name):
                return MagicMock()

            def close(self):
                pass

        monkeypatch.setattr("pymongo.MongoClient", FakeClient)
        monkeypatch.setattr("gridfs.GridFS", FakeGridFS)

        doc = make_document(
            filename="collected.pdf",
            content_file_id="content-grid",
        )
        await db.documents.insert_one(doc)
        r = await client.get(f"/api/v1/documents/{doc['id']}/download")
        assert r.status_code == 200
        assert r.content == pdf_bytes
        assert 'filename="collected.pdf"' in r.headers["content-disposition"]

    async def test_download_via_content_file_id_gridfs_failure(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch,
    ) -> None:
        """content_file_id GridFS fails -> falls through to legacy
        content -> if no content either, returns 404."""
        client = await authed_client_factory(role="admin")

        class FakeGridFS:
            def __init__(self, _db):
                pass

            def get(self, fid):
                raise RuntimeError("nope")

        class FakeClient:
            def __init__(self, _uri):
                pass

            def __getitem__(self, _name):
                return MagicMock()

            def close(self):
                pass

        monkeypatch.setattr("pymongo.MongoClient", FakeClient)
        monkeypatch.setattr("gridfs.GridFS", FakeGridFS)

        # No fallback embedded content -> 404
        doc = make_document(content_file_id="will-fail")
        await db.documents.insert_one(doc)
        r = await client.get(f"/api/v1/documents/{doc['id']}/download")
        assert r.status_code == 404

    async def test_delete_with_original_file_id_calls_gridfs_delete(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch,
    ) -> None:
        """Delete path with `original_file_id` set -> hits GridFS delete
        cleanup (lines 792-802)."""
        client = await authed_client_factory(role="admin")
        deleted: list[str] = []

        class FakeGridFS:
            def __init__(self, _db):
                pass

            def delete(self, fid):
                deleted.append(fid)

        class FakeClient:
            def __init__(self, _uri):
                pass

            def __getitem__(self, _name):
                return MagicMock()

            def close(self):
                pass

        monkeypatch.setattr("pymongo.MongoClient", FakeClient)
        monkeypatch.setattr("gridfs.GridFS", FakeGridFS)

        doc = make_document(id="del-1", original_file_id="orig-to-delete")
        await db.documents.insert_one(doc)
        r = await client.delete("/api/v1/documents/del-1")
        assert r.status_code == 200
        assert deleted == ["orig-to-delete"]

    async def test_delete_gridfs_error_is_logged_not_raised(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch,
    ) -> None:
        """GridFS cleanup errors are swallowed — delete still succeeds."""
        client = await authed_client_factory(role="admin")

        class FakeGridFS:
            def __init__(self, _db):
                pass

            def delete(self, fid):
                raise RuntimeError("gridfs unavailable")

        class FakeClient:
            def __init__(self, _uri):
                pass

            def __getitem__(self, _name):
                return MagicMock()

            def close(self):
                pass

        monkeypatch.setattr("pymongo.MongoClient", FakeClient)
        monkeypatch.setattr("gridfs.GridFS", FakeGridFS)

        doc = make_document(id="del-2", original_file_id="orig-bad")
        await db.documents.insert_one(doc)
        r = await client.delete("/api/v1/documents/del-2")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Helper functions: merge_attachments_into_existing_email
# ---------------------------------------------------------------------------


class TestMergeAttachmentsIntoExistingEmail:
    async def test_no_attachments_returns_zero(
        self, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        from fastapi import BackgroundTasks

        from src.documents.routes import merge_attachments_into_existing_email

        existing = make_document(id="email-1")
        await db.documents.insert_one(existing)
        bg = BackgroundTasks()
        count = await merge_attachments_into_existing_email(existing, [], bg)
        assert count == 0

    async def test_merges_new_attachments(
        self,
        db: AsyncIOMotorDatabase,
        patch_routes_db,
        tmp_path,
    ) -> None:
        from fastapi import BackgroundTasks

        from src.documents.routes import merge_attachments_into_existing_email

        existing = make_document(id="email-mrg", attachment_ids=[])
        await db.documents.insert_one(existing)

        # Two attachments on disk
        path1 = tmp_path / "a.pdf"
        path1.write_bytes(b"pdf-1")
        path2 = tmp_path / "b.png"
        path2.write_bytes(b"png-bytes")

        attachments = [
            {"filename": "a.pdf", "size": 5, "path": str(path1), "mime_type": "application/pdf"},
            {"filename": "b.png", "size": 9, "path": str(path2), "mime_type": "image/png"},
        ]

        bg = BackgroundTasks()
        count = await merge_attachments_into_existing_email(existing, attachments, bg)
        assert count == 2
        # Email updated
        updated = await db.documents.find_one({"id": "email-mrg"})
        assert updated["has_attachments"] is True
        assert updated["total_attachments"] == 2
        # Attachments inserted
        att_count = await db.documents.count_documents({"parent_document_id": "email-mrg"})
        assert att_count == 2
        # Background tasks queued
        assert len(bg.tasks) == 2

    async def test_skips_duplicate_by_filename_and_size(
        self,
        db: AsyncIOMotorDatabase,
        patch_routes_db,
        tmp_path,
    ) -> None:
        from fastapi import BackgroundTasks

        from src.documents.routes import merge_attachments_into_existing_email

        # Pre-existing attachment with name+size match
        existing_att = make_document(
            id="att-existing",
            filename="dup.pdf",
            size=10,
            parent_document_id="email-dup",
        )
        await db.documents.insert_one(existing_att)
        existing = make_document(
            id="email-dup",
            attachment_ids=["att-existing"],
        )
        await db.documents.insert_one(existing)

        new_path = tmp_path / "dup.pdf"
        new_path.write_bytes(b"x" * 10)
        attachments = [
            {"filename": "dup.pdf", "size": 10, "path": str(new_path)},
        ]
        bg = BackgroundTasks()
        count = await merge_attachments_into_existing_email(existing, attachments, bg)
        # Dedup -> 0 merged
        assert count == 0

    async def test_skips_attachment_with_missing_path(
        self,
        db: AsyncIOMotorDatabase,
        patch_routes_db,
    ) -> None:
        from fastapi import BackgroundTasks

        from src.documents.routes import merge_attachments_into_existing_email

        existing = make_document(id="email-mp")
        await db.documents.insert_one(existing)
        attachments = [
            {"filename": "gone.pdf", "size": 1, "path": "/nonexistent/path.pdf"},
            {"filename": "no_path.pdf", "size": 1},  # missing path key
        ]
        bg = BackgroundTasks()
        count = await merge_attachments_into_existing_email(existing, attachments, bg)
        assert count == 0


# ---------------------------------------------------------------------------
# Helper functions: aggregate_attachments_to_canonical
# ---------------------------------------------------------------------------


class TestAggregateAttachmentsToCanonical:
    async def test_no_superseded_returns_early(
        self, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        from src.documents.routes import aggregate_attachments_to_canonical

        # Just verify it doesn't crash
        await aggregate_attachments_to_canonical("canonical", [])

    async def test_canonical_doc_missing_logs_warning(
        self, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        from src.documents.routes import aggregate_attachments_to_canonical

        await aggregate_attachments_to_canonical("ghost", ["x"])
        # No exception; canonical doc not found -> early return

    async def test_aggregates_unique_attachments(
        self, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        from src.documents.routes import aggregate_attachments_to_canonical

        # canonical with no existing attachments
        canonical = make_document(id="canon")
        await db.documents.insert_one(canonical)

        # Superseded email with 2 attachments
        att1 = make_document(
            id="agg-att1", filename="x.pdf", size=10, parent_document_id="old-email"
        )
        att2 = make_document(
            id="agg-att2", filename="y.png", size=20, parent_document_id="old-email"
        )
        await db.documents.insert_many([att1, att2])
        superseded = make_document(
            id="old-email",
            attachment_ids=["agg-att1", "agg-att2"],
        )
        await db.documents.insert_one(superseded)

        await aggregate_attachments_to_canonical("canon", ["old-email"])

        updated = await db.documents.find_one({"id": "canon"})
        assert updated["has_attachments"] is True
        assert updated["total_attachments"] == 2
        assert set(updated["attachment_ids"]) == {"agg-att1", "agg-att2"}
        # Reparented
        reparented = await db.documents.find_one({"id": "agg-att1"})
        assert reparented["parent_document_id"] == "canon"

    async def test_skips_dedup_by_filename_size(
        self, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        from src.documents.routes import aggregate_attachments_to_canonical

        # Canonical already has 'dup.pdf' size=5
        canon_att = make_document(
            id="canon-att", filename="dup.pdf", size=5, parent_document_id="canon-d"
        )
        await db.documents.insert_one(canon_att)
        canonical = make_document(id="canon-d", attachment_ids=["canon-att"])
        await db.documents.insert_one(canonical)

        # Superseded email has same filename+size -> should be skipped
        super_att = make_document(
            id="super-att", filename="dup.pdf", size=5, parent_document_id="super-d"
        )
        await db.documents.insert_one(super_att)
        superseded = make_document(id="super-d", attachment_ids=["super-att"])
        await db.documents.insert_one(superseded)

        await aggregate_attachments_to_canonical("canon-d", ["super-d"])
        updated = await db.documents.find_one({"id": "canon-d"})
        # No new attachments added (the dup was skipped) -> early return,
        # so has_attachments stays as factory default (False)
        # The `if not new_ids: return` path was hit, so no update happened.
        # We pin that the canonical's attachment_ids did NOT grow.
        assert updated["attachment_ids"] == ["canon-att"]

    async def test_skips_superseded_email_not_found(
        self, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        from src.documents.routes import aggregate_attachments_to_canonical

        canonical = make_document(id="canon-snf")
        await db.documents.insert_one(canonical)

        # Reference a non-existent superseded id
        await aggregate_attachments_to_canonical("canon-snf", ["ghost-email"])
        # No crash; no updates
        updated = await db.documents.find_one({"id": "canon-snf"})
        assert "attachment_ids" not in updated or updated["attachment_ids"] == []

    async def test_skips_superseded_with_no_attachments(
        self, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        from src.documents.routes import aggregate_attachments_to_canonical

        canonical = make_document(id="canon-sa")
        await db.documents.insert_one(canonical)
        # Superseded email has no attachment_ids -> skip continuation
        superseded = make_document(id="super-empty", attachment_ids=[])
        await db.documents.insert_one(superseded)

        await aggregate_attachments_to_canonical("canon-sa", ["super-empty"])
        updated = await db.documents.find_one({"id": "canon-sa"})
        assert "attachment_ids" not in updated or updated["attachment_ids"] == []


# ---------------------------------------------------------------------------
# Background task: generate_ai_suggestions_async
# ---------------------------------------------------------------------------


class TestGenerateAISuggestionsAsync:
    async def test_success_writes_cache(
        self, db: AsyncIOMotorDatabase, patch_routes_db, monkeypatch
    ) -> None:
        from src.documents import routes as documents_routes
        from src.documents.routes import generate_ai_suggestions_async

        doc = make_document(
            id="ai-1",
            extracted_text="Sensitive name: Alice",
            content=b"%PDF",
        )
        await db.documents.insert_one(doc)

        async def fake_suggestions(text, ctx=None):
            return {"suggestions": [{"text": "Alice", "category": "name"}], "summary": "1 PII"}

        def fake_enrich(suggestions, pdf, text_data):
            return suggestions

        monkeypatch.setattr(documents_routes, "get_redaction_suggestions", fake_suggestions)
        monkeypatch.setattr(documents_routes, "enrich_suggestions_with_coordinates", fake_enrich)

        await generate_ai_suggestions_async("ai-1", timeout=5, db=db)

        updated = await db.documents.find_one({"id": "ai-1"})
        assert updated["processing_status"] == "ai_complete"
        assert updated["ai_suggestions"]["suggestions"] == [{"text": "Alice", "category": "name"}]
        assert updated["ai_suggestions"]["summary"] == "1 PII"

    async def test_doc_not_found_returns_early(
        self, db: AsyncIOMotorDatabase, patch_routes_db
    ) -> None:
        from src.documents.routes import generate_ai_suggestions_async

        # No document seeded; function should log and return
        await generate_ai_suggestions_async("ghost-ai", db=db)
        # No exception; nothing inserted
        assert await db.documents.find_one({"id": "ghost-ai"}) is None

    async def test_no_extracted_text_skips(self, db: AsyncIOMotorDatabase, patch_routes_db) -> None:
        from src.documents.routes import generate_ai_suggestions_async

        doc = make_document(id="ai-no-text")
        await db.documents.insert_one(doc)
        await generate_ai_suggestions_async("ai-no-text", db=db)
        # Status was updated to ai_processing but no ai_suggestions cache
        updated = await db.documents.find_one({"id": "ai-no-text"})
        assert updated["processing_status"] == "ai_processing"
        assert "ai_suggestions" not in updated

    async def test_text_data_fallback_used_when_extracted_text_missing(
        self, db: AsyncIOMotorDatabase, patch_routes_db, monkeypatch
    ) -> None:
        from src.documents import routes as documents_routes
        from src.documents.routes import generate_ai_suggestions_async

        doc = make_document(
            id="ai-textdata",
            text_data={"full_text": "From the text_data field"},
            content=b"%PDF",
        )
        await db.documents.insert_one(doc)

        captured: dict[str, str] = {}

        async def fake_suggestions(text, ctx=None):
            captured["text"] = text
            captured["ctx"] = ctx
            return {"suggestions": [], "summary": ""}

        monkeypatch.setattr(documents_routes, "get_redaction_suggestions", fake_suggestions)
        monkeypatch.setattr(
            documents_routes,
            "enrich_suggestions_with_coordinates",
            lambda s, p, t: s,
        )

        await generate_ai_suggestions_async("ai-textdata", db=db)
        assert captured["text"] == "From the text_data field"

    async def test_includes_case_context_when_case_present(
        self, db: AsyncIOMotorDatabase, patch_routes_db, monkeypatch
    ) -> None:
        from src.documents import routes as documents_routes
        from src.documents.routes import generate_ai_suggestions_async

        case = make_case(id="ai-case", title="Records about Contract X")
        await db.cases.insert_one(case)
        doc = make_document(
            id="ai-with-case",
            extracted_text="hello",
            case_id="ai-case",
            content=b"%PDF",
        )
        await db.documents.insert_one(doc)

        captured: dict[str, Any] = {}

        async def fake_suggestions(text, ctx=None):
            captured["ctx"] = ctx
            return {"suggestions": [], "summary": ""}

        monkeypatch.setattr(documents_routes, "get_redaction_suggestions", fake_suggestions)
        monkeypatch.setattr(
            documents_routes,
            "enrich_suggestions_with_coordinates",
            lambda s, p, t: s,
        )

        await generate_ai_suggestions_async("ai-with-case", db=db)
        assert captured["ctx"] is not None
        assert "Records about Contract X" in captured["ctx"]

    async def test_timeout_writes_timeout_status(
        self, db: AsyncIOMotorDatabase, patch_routes_db, monkeypatch
    ) -> None:
        import asyncio

        from src.documents import routes as documents_routes
        from src.documents.routes import generate_ai_suggestions_async

        doc = make_document(id="ai-timeout", extracted_text="something")
        await db.documents.insert_one(doc)

        async def slow_suggestions(text, ctx=None):
            await asyncio.sleep(1)
            return {"suggestions": [], "summary": ""}

        monkeypatch.setattr(documents_routes, "get_redaction_suggestions", slow_suggestions)

        await generate_ai_suggestions_async("ai-timeout", timeout=0, db=db)

        updated = await db.documents.find_one({"id": "ai-timeout"})
        assert updated["processing_status"] == "ai_timeout"
        assert updated["ai_suggestions"]["error"] == "timeout"

    async def test_exception_writes_error_status(
        self, db: AsyncIOMotorDatabase, patch_routes_db, monkeypatch
    ) -> None:
        from src.documents import routes as documents_routes
        from src.documents.routes import generate_ai_suggestions_async

        doc = make_document(id="ai-err", extracted_text="text")
        await db.documents.insert_one(doc)

        async def boom(text, ctx=None):
            raise RuntimeError("LLM provider exploded")

        monkeypatch.setattr(documents_routes, "get_redaction_suggestions", boom)

        await generate_ai_suggestions_async("ai-err", timeout=5, db=db)

        updated = await db.documents.find_one({"id": "ai-err"})
        assert updated["processing_status"] == "ai_error"
        assert "exploded" in updated["ai_suggestions"]["error"]

    async def test_no_db_provided_uses_get_database(
        self, db: AsyncIOMotorDatabase, patch_routes_db, monkeypatch
    ) -> None:
        """Covers the `if db is None: db = get_database()` branch."""
        from src.documents.routes import generate_ai_suggestions_async

        doc = make_document(id="ai-nodb")
        await db.documents.insert_one(doc)

        monkeypatch.setattr(
            "src.core.database.get_database",
            lambda: db,
        )

        # Function returns silently (no extracted_text); we just want
        # the db-fallback line to execute.
        await generate_ai_suggestions_async("ai-nodb")
        # If it ran without crashing, the branch was covered.
