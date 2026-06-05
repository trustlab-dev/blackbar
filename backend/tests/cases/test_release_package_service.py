"""Tests for `src.cases.release_package_service` — release package generation,
review, release, and download workflow.

This is the highest-criticality module in `cases/`: release packages are
irreversible operator-visible artifacts. Bugs here leak unredacted data, so
the target is 100% line + branch coverage per audit Section 5b.

Architecture: this module is heavily I/O bound (Mongo + GridFS), so tests use
`AsyncMock` for the motor database and `unittest.mock.patch` for GridFS /
PDF / cover-letter generation helpers. The few paths that exercise live DB
behaviour are left to the route-level integration tests in Batch 2.2.C; here
we target the unit boundary of `release_package_service`.

Phase 2.2.B absorbed and rebuilt the original `tests/test_release_package.py`
after Phase 1 single-tenant cleanup removed the `tenant_db=` /
`tenant_id=` / `tenant_settings=` kwargs from every service entry point.
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.cases import release_package_service
from src.cases.release_package_models import (
    ReleasePackageDB,
    ReleasePackageGenerate,
    ReleasePackageRelease,
    ReleasePackageStatus,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    """An AsyncMock motor database with the collections this service uses.

    `db.name` is a plain attribute (motor exposes it sync), so we override
    it on the AsyncMock to a real string rather than another AsyncMock —
    code paths feed `db.name` into `sync_client[db.name]` and a MagicMock
    would resolve oddly there.
    """
    db = AsyncMock()
    db.name = "blackbar_test"
    db.cases = AsyncMock()
    db.documents = AsyncMock()
    db.release_packages = AsyncMock()
    return db


@pytest.fixture
def mock_case():
    """A representative case dict — only the fields read by the service."""
    return {
        "id": "case-123",
        "tracking_number": "FOI-2025-001",
        "title": "Test FOI Request",
        "requester": {"name": "John Doe", "email": "john@example.com"},
        "created_at": datetime(2025, 11, 20, 10, 0, 0),
    }


@pytest.fixture
def mock_documents():
    """Two approved/released documents with embedded content."""
    return [
        {
            "id": "doc-1",
            "case_id": "case-123",
            "filename": "document1.pdf",
            "status": "approved",
            "redactions": [
                {"category": "S22", "coordinates": {"x": 100, "y": 100, "width": 50, "height": 20}},
                {"category": "S15", "coordinates": {"x": 200, "y": 200, "width": 60, "height": 25}},
            ],
            "content": b"PDF content here",
        },
        {
            "id": "doc-2",
            "case_id": "case-123",
            "filename": "document2.pdf",
            "status": "released",
            "redactions": [
                {"category": "S22", "coordinates": {"x": 150, "y": 150, "width": 40, "height": 15}}
            ],
            "content": b"Another PDF content",
        },
    ]


@pytest.fixture
def release_settings():
    """A representative release-settings dict (Phase 1.9b renamed this
    kwarg from `tenant_settings` -> `release_settings`)."""
    return {
        "default_expiration_days": 30,
        "min_expiration_days": 7,
        "max_expiration_days": 90,
        "default_max_downloads": 10,
        "max_downloads_limit": 100,
        "unlimited_downloads_allowed": False,
        "include_cover_letter_default": True,
        "include_manifest": True,
        "auto_notify_requester": True,
    }


# ---------------------------------------------------------------------------
# get_document_content
# ---------------------------------------------------------------------------


class TestGetDocumentContent:
    @pytest.mark.asyncio
    async def test_returns_embedded_content_when_no_gridfs(self, mock_db):
        doc = {"id": "doc-1", "content": b"embedded bytes"}

        result = await release_package_service.get_document_content(doc, mock_db)

        assert result == b"embedded bytes"

    @pytest.mark.asyncio
    async def test_returns_gridfs_content_when_file_id_present(self, mock_db):
        doc = {"id": "doc-1", "content_file_id": "gridfs-abc"}

        mock_grid_out = MagicMock()
        mock_grid_out.read.return_value = b"gridfs bytes"
        mock_fs = MagicMock()
        mock_fs.get.return_value = mock_grid_out

        with (
            patch("src.cases.release_package_service.MongoClient") as mock_client,
            patch("src.cases.release_package_service.gridfs.GridFS", return_value=mock_fs),
        ):
            mock_client.return_value.__getitem__.return_value = MagicMock()

            result = await release_package_service.get_document_content(doc, mock_db)

        assert result == b"gridfs bytes"
        mock_fs.get.assert_called_once_with("gridfs-abc")

    @pytest.mark.asyncio
    async def test_falls_back_to_embedded_on_gridfs_failure(self, mock_db):
        doc = {"id": "doc-1", "content_file_id": "gridfs-abc", "content": b"fallback"}

        with patch("src.cases.release_package_service.MongoClient", side_effect=Exception("boom")):
            result = await release_package_service.get_document_content(doc, mock_db)

        assert result == b"fallback"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_content(self, mock_db):
        doc = {"id": "doc-1"}

        result = await release_package_service.get_document_content(doc, mock_db)

        assert result is None


# ---------------------------------------------------------------------------
# delete_existing_draft
# ---------------------------------------------------------------------------


class TestDeleteExistingDraft:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_existing_draft(self, mock_db):
        mock_db.release_packages.find_one = AsyncMock(return_value=None)

        result = await release_package_service.delete_existing_draft("case-123", mock_db)

        assert result is None
        mock_db.release_packages.delete_one.assert_not_called()

    @pytest.mark.asyncio
    async def test_deletes_existing_draft_with_gridfs_file(self, mock_db):
        existing = {
            "id": "draft-old",
            "case_id": "case-123",
            "status": ReleasePackageStatus.DRAFT.value,
            "file_id": "gridfs-file-id",
        }
        mock_db.release_packages.find_one = AsyncMock(return_value=existing)
        mock_db.release_packages.delete_one = AsyncMock()

        mock_fs = MagicMock()
        with (
            patch("src.cases.release_package_service.MongoClient") as mock_client,
            patch("src.cases.release_package_service.gridfs.GridFS", return_value=mock_fs),
            patch("src.cases.release_package_service.ObjectId", side_effect=lambda x: x),
        ):
            mock_client.return_value.__getitem__.return_value = MagicMock()

            result = await release_package_service.delete_existing_draft("case-123", mock_db)

        assert result == "draft-old"
        mock_fs.delete.assert_called_once()
        mock_db.release_packages.delete_one.assert_called_once_with({"id": "draft-old"})

    @pytest.mark.asyncio
    async def test_deletes_draft_when_gridfs_delete_fails(self, mock_db):
        existing = {
            "id": "draft-old",
            "case_id": "case-123",
            "status": ReleasePackageStatus.DRAFT.value,
            "file_id": "gridfs-file-id",
        }
        mock_db.release_packages.find_one = AsyncMock(return_value=existing)
        mock_db.release_packages.delete_one = AsyncMock()

        with patch(
            "src.cases.release_package_service.MongoClient", side_effect=Exception("gridfs boom")
        ):
            result = await release_package_service.delete_existing_draft("case-123", mock_db)

        # GridFS failure is logged but the draft record is still removed.
        assert result == "draft-old"
        mock_db.release_packages.delete_one.assert_called_once_with({"id": "draft-old"})

    @pytest.mark.asyncio
    async def test_deletes_draft_without_gridfs_file(self, mock_db):
        existing = {
            "id": "draft-old",
            "case_id": "case-123",
            "status": ReleasePackageStatus.DRAFT.value,
            # No file_id -- generation must have failed mid-flight.
        }
        mock_db.release_packages.find_one = AsyncMock(return_value=existing)
        mock_db.release_packages.delete_one = AsyncMock()

        result = await release_package_service.delete_existing_draft("case-123", mock_db)

        assert result == "draft-old"
        mock_db.release_packages.delete_one.assert_called_once_with({"id": "draft-old"})


# ---------------------------------------------------------------------------
# start_package_generation
# ---------------------------------------------------------------------------


class TestStartPackageGeneration:
    @pytest.mark.asyncio
    async def test_creates_record_with_generating_status(
        self, mock_db, mock_case, release_settings
    ):
        mock_db.cases.find_one = AsyncMock(return_value=mock_case)
        mock_db.release_packages.find_one = AsyncMock(return_value=None)
        mock_db.release_packages.insert_one = AsyncMock()
        mock_db.cases.update_one = AsyncMock()

        request = ReleasePackageGenerate(include_cover_letter=True)

        package_id, replaced_id = await release_package_service.start_package_generation(
            case_id="case-123",
            created_by="user-789",
            created_by_name="Test Analyst",
            request=request,
            release_settings=release_settings,
            db=mock_db,
        )

        assert package_id is not None
        assert replaced_id is None
        mock_db.release_packages.insert_one.assert_called_once()
        inserted = mock_db.release_packages.insert_one.call_args[0][0]
        assert inserted["status"] == ReleasePackageStatus.GENERATING.value
        assert inserted["case_id"] == "case-123"
        assert inserted["filename"].startswith("FOI-2025-001-Release")
        assert inserted["include_cover_letter"] is True
        # Case is updated with the new draft pointer.
        mock_db.cases.update_one.assert_called_once_with(
            {"id": "case-123"}, {"$set": {"current_draft_id": package_id}}
        )

    @pytest.mark.asyncio
    async def test_replaces_existing_draft(self, mock_db, mock_case, release_settings):
        existing_draft = {
            "id": "old-draft-123",
            "case_id": "case-123",
            "status": ReleasePackageStatus.DRAFT.value,
            # No file_id to keep this test free of GridFS plumbing -- already
            # covered explicitly in TestDeleteExistingDraft.
        }
        mock_db.cases.find_one = AsyncMock(return_value=mock_case)
        mock_db.release_packages.find_one = AsyncMock(return_value=existing_draft)
        mock_db.release_packages.delete_one = AsyncMock()
        mock_db.release_packages.insert_one = AsyncMock()
        mock_db.cases.update_one = AsyncMock()

        request = ReleasePackageGenerate(include_cover_letter=False)

        package_id, replaced_id = await release_package_service.start_package_generation(
            case_id="case-123",
            created_by="user-789",
            created_by_name="Test Analyst",
            request=request,
            release_settings=release_settings,
            db=mock_db,
        )

        assert replaced_id == "old-draft-123"
        assert package_id != "old-draft-123"
        mock_db.release_packages.delete_one.assert_called_once_with({"id": "old-draft-123"})

    @pytest.mark.asyncio
    async def test_case_not_found_raises(self, mock_db, release_settings):
        mock_db.cases.find_one = AsyncMock(return_value=None)
        request = ReleasePackageGenerate(include_cover_letter=True)

        with pytest.raises(ValueError, match="Case not found"):
            await release_package_service.start_package_generation(
                case_id="nonexistent",
                created_by="user-789",
                created_by_name="Test Analyst",
                request=request,
                release_settings=release_settings,
                db=mock_db,
            )

    @pytest.mark.asyncio
    async def test_filename_falls_back_to_case_id_when_no_tracking_number(
        self, mock_db, release_settings
    ):
        case = {"id": "case-without-tracking"}
        mock_db.cases.find_one = AsyncMock(return_value=case)
        mock_db.release_packages.find_one = AsyncMock(return_value=None)
        mock_db.release_packages.insert_one = AsyncMock()
        mock_db.cases.update_one = AsyncMock()

        request = ReleasePackageGenerate()

        await release_package_service.start_package_generation(
            case_id="case-without-tracking",
            created_by="user-789",
            created_by_name="Test Analyst",
            request=request,
            release_settings=release_settings,
            db=mock_db,
        )

        inserted = mock_db.release_packages.insert_one.call_args[0][0]
        assert inserted["filename"] == "case-without-tracking-Release.zip"


# ---------------------------------------------------------------------------
# process_package_generation
# ---------------------------------------------------------------------------


class TestProcessPackageGeneration:
    """The background worker. Mocks GridFS + the PDF redactor + the cover
    letter / summary helpers since none of them are this module's contract."""

    @pytest.mark.asyncio
    async def test_happy_path_writes_zip_and_marks_draft(
        self, mock_db, mock_case, mock_documents, release_settings
    ):
        mock_db.cases.find_one = AsyncMock(return_value=mock_case)
        # documents.find returns a Cursor with to_list; mock that whole chain.
        cursor = AsyncMock()
        cursor.to_list = AsyncMock(return_value=mock_documents)
        mock_db.documents.find = MagicMock(return_value=cursor)
        mock_db.release_packages.find_one = AsyncMock(
            return_value={
                "id": "pkg-123",
                "filename": "FOI-2025-001-Release.zip",
            }
        )
        mock_db.release_packages.update_one = AsyncMock()

        request = ReleasePackageGenerate(include_cover_letter=True)

        with (
            patch("src.cases.release_package_service.MongoClient") as mock_client,
            patch("src.cases.release_package_service.gridfs.GridFS") as mock_grid_cls,
            patch(
                "src.cases.release_package_service.apply_redactions_to_pdf",
                return_value=b"REDACTED",
            ),
            patch("src.cases.release_package_service.generate_cover_letter", return_value="cover"),
            patch(
                "src.cases.release_package_service.generate_release_summary", return_value="summary"
            ),
        ):
            mock_client.return_value.__getitem__.return_value = MagicMock()
            mock_fs = MagicMock()
            mock_fs.put.return_value = "new-gridfs-id"
            mock_grid_cls.return_value = mock_fs

            await release_package_service.process_package_generation(
                package_id="pkg-123",
                case_id="case-123",
                db=mock_db,
                request=request,
                release_settings=release_settings,
            )

        # Last update_one call should mark status DRAFT with progress 100.
        final_call = mock_db.release_packages.update_one.call_args_list[-1]
        update_payload = final_call[0][1]["$set"]
        assert update_payload["status"] == ReleasePackageStatus.DRAFT.value
        assert update_payload["generation_progress"] == 100
        assert update_payload["document_count"] == 2
        assert update_payload["total_redactions"] == 3
        assert update_payload["file_id"] == "new-gridfs-id"

    @pytest.mark.asyncio
    async def test_case_not_found_marks_failed(self, mock_db, release_settings):
        mock_db.cases.find_one = AsyncMock(return_value=None)
        mock_db.release_packages.update_one = AsyncMock()

        request = ReleasePackageGenerate()

        await release_package_service.process_package_generation(
            package_id="pkg-123",
            case_id="missing-case",
            db=mock_db,
            request=request,
            release_settings=release_settings,
        )

        # The outer try/except marks the package failed instead of raising.
        last_call_args = mock_db.release_packages.update_one.call_args[0]
        assert last_call_args[0] == {"id": "pkg-123"}
        assert last_call_args[1]["$set"]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_no_releasable_documents_marks_failed(self, mock_db, mock_case, release_settings):
        mock_db.cases.find_one = AsyncMock(return_value=mock_case)
        cursor = AsyncMock()
        cursor.to_list = AsyncMock(return_value=[])  # zero docs
        mock_db.documents.find = MagicMock(return_value=cursor)
        mock_db.release_packages.update_one = AsyncMock()

        request = ReleasePackageGenerate()

        await release_package_service.process_package_generation(
            package_id="pkg-123",
            case_id="case-123",
            db=mock_db,
            request=request,
            release_settings=release_settings,
        )

        final_call = mock_db.release_packages.update_one.call_args[0]
        assert final_call[1]["$set"]["status"] == "failed"
        assert "No documents" in final_call[1]["$set"]["generation_message"]

    @pytest.mark.asyncio
    async def test_filters_out_unreleased_documents(self, mock_db, mock_case, release_settings):
        # Two docs: one approved (included), one in-progress (excluded).
        docs = [
            {
                "id": "doc-included",
                "case_id": "case-123",
                "filename": "ok.pdf",
                "status": "released",
                "redactions": [],
                "content": b"PDF",
            },
            {
                "id": "doc-excluded",
                "case_id": "case-123",
                "filename": "wip.pdf",
                "status": "in_review",
                "redactions": [],
                "content": b"PDF",
            },
        ]
        mock_db.cases.find_one = AsyncMock(return_value=mock_case)
        cursor = AsyncMock()
        cursor.to_list = AsyncMock(return_value=docs)
        mock_db.documents.find = MagicMock(return_value=cursor)
        mock_db.release_packages.find_one = AsyncMock(
            return_value={
                "id": "pkg-123",
                "filename": "FOI.zip",
            }
        )
        mock_db.release_packages.update_one = AsyncMock()

        request = ReleasePackageGenerate(include_cover_letter=False)

        with (
            patch("src.cases.release_package_service.MongoClient") as mock_client,
            patch("src.cases.release_package_service.gridfs.GridFS") as mock_grid_cls,
            patch("src.cases.release_package_service.generate_release_summary", return_value="x"),
        ):
            mock_client.return_value.__getitem__.return_value = MagicMock()
            mock_fs = MagicMock()
            mock_fs.put.return_value = "new-gridfs-id"
            mock_grid_cls.return_value = mock_fs

            await release_package_service.process_package_generation(
                package_id="pkg-123",
                case_id="case-123",
                db=mock_db,
                request=request,
                release_settings=release_settings,
            )

        update_payload = mock_db.release_packages.update_one.call_args_list[-1][0][1]["$set"]
        assert update_payload["document_count"] == 1

    @pytest.mark.asyncio
    async def test_skips_documents_with_no_content(self, mock_db, mock_case, release_settings):
        docs = [
            {
                "id": "doc-1",
                "case_id": "case-123",
                "filename": "no-content.pdf",
                "status": "released",
                "redactions": [],
                # Neither content nor content_file_id -> skipped.
            },
            {
                "id": "doc-2",
                "case_id": "case-123",
                "filename": "ok.pdf",
                "status": "released",
                "redactions": [],
                "content": b"PDF",
            },
        ]
        mock_db.cases.find_one = AsyncMock(return_value=mock_case)
        cursor = AsyncMock()
        cursor.to_list = AsyncMock(return_value=docs)
        mock_db.documents.find = MagicMock(return_value=cursor)
        mock_db.release_packages.find_one = AsyncMock(
            return_value={
                "id": "pkg-123",
                "filename": "FOI.zip",
            }
        )
        mock_db.release_packages.update_one = AsyncMock()

        request = ReleasePackageGenerate(include_cover_letter=False)

        with (
            patch("src.cases.release_package_service.MongoClient") as mock_client,
            patch("src.cases.release_package_service.gridfs.GridFS") as mock_grid_cls,
            patch("src.cases.release_package_service.generate_release_summary", return_value="x"),
        ):
            mock_client.return_value.__getitem__.return_value = MagicMock()
            mock_fs = MagicMock()
            mock_fs.put.return_value = "new-gridfs-id"
            mock_grid_cls.return_value = mock_fs

            await release_package_service.process_package_generation(
                package_id="pkg-123",
                case_id="case-123",
                db=mock_db,
                request=request,
                release_settings=release_settings,
            )

        update_payload = mock_db.release_packages.update_one.call_args_list[-1][0][1]["$set"]
        # Only 1 doc made it into the ZIP -- the contentless one was skipped.
        assert update_payload["document_count"] == 1

    @pytest.mark.asyncio
    async def test_redaction_error_marks_package_failed(self, mock_db, mock_case, release_settings):
        """SECURITY regression (audit B10, fixed 2026-05-12).

        If apply_redactions_to_pdf raises, the package MUST be marked
        failed — never fall back to the unredacted original. A silent
        fallback is a data-leak vector: the operator releases a "draft"
        thinking it's redacted when in fact it contains the originals.
        """
        docs = [
            {
                "id": "doc-1",
                "case_id": "case-123",
                "filename": "doc.pdf",
                "status": "released",
                "redactions": [{"category": "S22"}],
                "content": b"PDF",
            }
        ]
        mock_db.cases.find_one = AsyncMock(return_value=mock_case)
        cursor = AsyncMock()
        cursor.to_list = AsyncMock(return_value=docs)
        mock_db.documents.find = MagicMock(return_value=cursor)
        mock_db.release_packages.find_one = AsyncMock(
            return_value={
                "id": "pkg-123",
                "filename": "FOI.zip",
            }
        )
        mock_db.release_packages.update_one = AsyncMock()

        request = ReleasePackageGenerate(include_cover_letter=False)

        with (
            patch("src.cases.release_package_service.MongoClient") as mock_client,
            patch("src.cases.release_package_service.gridfs.GridFS") as mock_grid_cls,
            patch(
                "src.cases.release_package_service.apply_redactions_to_pdf",
                side_effect=Exception("redactor boom"),
            ),
            patch("src.cases.release_package_service.generate_release_summary", return_value="x"),
        ):
            mock_client.return_value.__getitem__.return_value = MagicMock()
            mock_fs = MagicMock()
            mock_fs.put.return_value = "new-gridfs-id"
            mock_grid_cls.return_value = mock_fs

            await release_package_service.process_package_generation(
                package_id="pkg-123",
                case_id="case-123",
                db=mock_db,
                request=request,
                release_settings=release_settings,
            )

        # Failure path: package is marked failed with the error captured,
        # the GridFS .put() is never called (no archive written), and the
        # original-content fallback never happens.
        update_payload = mock_db.release_packages.update_one.call_args_list[-1][0][1]["$set"]
        assert update_payload["status"] == "failed"
        assert "redactor boom" in update_payload["generation_message"]
        mock_fs.put.assert_not_called()

    @pytest.mark.asyncio
    async def test_filename_without_pdf_extension_gets_pdf(
        self, mock_db, mock_case, release_settings
    ):
        docs = [
            {
                "id": "doc-1",
                "case_id": "case-123",
                "filename": "notes.txt",
                "status": "released",
                "redactions": [],
                "content": b"data",
            }
        ]
        mock_db.cases.find_one = AsyncMock(return_value=mock_case)
        cursor = AsyncMock()
        cursor.to_list = AsyncMock(return_value=docs)
        mock_db.documents.find = MagicMock(return_value=cursor)
        mock_db.release_packages.find_one = AsyncMock(
            return_value={
                "id": "pkg-123",
                "filename": "FOI.zip",
            }
        )
        mock_db.release_packages.update_one = AsyncMock()

        request = ReleasePackageGenerate(include_cover_letter=False)

        with (
            patch("src.cases.release_package_service.MongoClient") as mock_client,
            patch("src.cases.release_package_service.gridfs.GridFS") as mock_grid_cls,
            patch("src.cases.release_package_service.generate_release_summary", return_value="x"),
        ):
            mock_client.return_value.__getitem__.return_value = MagicMock()
            mock_fs = MagicMock()
            mock_fs.put.return_value = "new-gridfs-id"
            mock_grid_cls.return_value = mock_fs

            await release_package_service.process_package_generation(
                package_id="pkg-123",
                case_id="case-123",
                db=mock_db,
                request=request,
                release_settings=release_settings,
            )

        update_payload = mock_db.release_packages.update_one.call_args_list[-1][0][1]["$set"]
        included = update_payload["included_documents"][0]
        assert included["filename"].endswith(".pdf")

    @pytest.mark.asyncio
    async def test_specific_document_ids_narrows_query(self, mock_db, mock_case, release_settings):
        cursor = AsyncMock()
        cursor.to_list = AsyncMock(return_value=[])
        mock_db.cases.find_one = AsyncMock(return_value=mock_case)
        mock_db.documents.find = MagicMock(return_value=cursor)
        mock_db.release_packages.update_one = AsyncMock()

        request = ReleasePackageGenerate(document_ids=["doc-a", "doc-b"])

        await release_package_service.process_package_generation(
            package_id="pkg-123",
            case_id="case-123",
            db=mock_db,
            request=request,
            release_settings=release_settings,
        )

        # The narrowed query is passed through to motor.find.
        mock_db.documents.find.assert_called_once()
        query = mock_db.documents.find.call_args[0][0]
        assert query["case_id"] == "case-123"
        assert query["id"] == {"$in": ["doc-a", "doc-b"]}

    @pytest.mark.asyncio
    async def test_omits_manifest_when_setting_disabled(self, mock_db, mock_case, release_settings):
        docs = [
            {
                "id": "doc-1",
                "case_id": "case-123",
                "filename": "ok.pdf",
                "status": "released",
                "redactions": [],
                "content": b"PDF",
            }
        ]
        mock_db.cases.find_one = AsyncMock(return_value=mock_case)
        cursor = AsyncMock()
        cursor.to_list = AsyncMock(return_value=docs)
        mock_db.documents.find = MagicMock(return_value=cursor)
        mock_db.release_packages.find_one = AsyncMock(
            return_value={
                "id": "pkg-123",
                "filename": "FOI.zip",
            }
        )
        mock_db.release_packages.update_one = AsyncMock()

        captured_zip = {}

        def capture_put(content, **_kwargs):
            captured_zip["bytes"] = content
            return "new-gridfs-id"

        settings_no_manifest = {**release_settings, "include_manifest": False}
        request = ReleasePackageGenerate(include_cover_letter=False)

        with (
            patch("src.cases.release_package_service.MongoClient") as mock_client,
            patch("src.cases.release_package_service.gridfs.GridFS") as mock_grid_cls,
        ):
            mock_client.return_value.__getitem__.return_value = MagicMock()
            mock_fs = MagicMock()
            mock_fs.put.side_effect = capture_put
            mock_grid_cls.return_value = mock_fs

            await release_package_service.process_package_generation(
                package_id="pkg-123",
                case_id="case-123",
                db=mock_db,
                request=request,
                release_settings=settings_no_manifest,
            )

        with zipfile.ZipFile(io.BytesIO(captured_zip["bytes"])) as zf:
            names = zf.namelist()
        assert not any("MANIFEST" in n for n in names)

    @pytest.mark.asyncio
    async def test_requester_string_falls_back_to_requester_name(self, mock_db, release_settings):
        # When `requester` is not a dict, the worker reads `requester_name`
        # for the cover letter. Also exercises the str(created_at) branch.
        case = {
            "id": "case-123",
            "tracking_number": "FOI-2025-002",
            "title": "X",
            "requester": "Anonymous",
            "requester_name": "Anonymous Submitter",
            "created_at": "2025-11-20",
        }
        docs = [
            {
                "id": "d",
                "case_id": "case-123",
                "filename": "x.pdf",
                "status": "released",
                "redactions": [],
                "content": b"PDF",
            }
        ]
        mock_db.cases.find_one = AsyncMock(return_value=case)
        cursor = AsyncMock()
        cursor.to_list = AsyncMock(return_value=docs)
        mock_db.documents.find = MagicMock(return_value=cursor)
        mock_db.release_packages.find_one = AsyncMock(
            return_value={
                "id": "pkg-123",
                "filename": "FOI.zip",
            }
        )
        mock_db.release_packages.update_one = AsyncMock()

        request = ReleasePackageGenerate(include_cover_letter=True)
        captured = {}

        def capture_cover(case_data, _doc_info):
            captured["case_data"] = case_data
            return "cover"

        with (
            patch("src.cases.release_package_service.MongoClient") as mock_client,
            patch("src.cases.release_package_service.gridfs.GridFS") as mock_grid_cls,
            patch(
                "src.cases.release_package_service.generate_cover_letter", side_effect=capture_cover
            ),
            patch("src.cases.release_package_service.generate_release_summary", return_value="x"),
        ):
            mock_client.return_value.__getitem__.return_value = MagicMock()
            mock_fs = MagicMock()
            mock_fs.put.return_value = "id"
            mock_grid_cls.return_value = mock_fs

            await release_package_service.process_package_generation(
                package_id="pkg-123",
                case_id="case-123",
                db=mock_db,
                request=request,
                release_settings=release_settings,
            )

        assert captured["case_data"]["requester_name"] == "Anonymous Submitter"


# ---------------------------------------------------------------------------
# release_package
# ---------------------------------------------------------------------------


def _draft_dict(**overrides):
    base = {
        "id": "pkg-123",
        "case_id": "case-123",
        "status": ReleasePackageStatus.DRAFT.value,
        "filename": "FOI.zip",
        "size_bytes": 100,
        "document_count": 1,
        "total_redactions": 0,
        "access_token": "tok",
        "created_at": datetime.utcnow(),
        "created_by": "u",
        "created_by_name": "U",
    }
    base.update(overrides)
    return base


class TestReleasePackage:
    @pytest.mark.asyncio
    async def test_releases_draft_successfully(self, mock_db, release_settings):
        draft = _draft_dict()
        released = {**draft, "status": ReleasePackageStatus.RELEASED.value}
        mock_db.release_packages.find_one = AsyncMock(side_effect=[draft, released])
        mock_db.release_packages.update_one = AsyncMock()
        mock_db.release_packages.update_many = AsyncMock()
        mock_db.cases.update_one = AsyncMock()

        request = ReleasePackageRelease(
            expires_in_days=30,
            max_downloads=10,
            notify_requester=True,
            custom_message="hi",
        )

        result = await release_package_service.release_package(
            package_id="pkg-123",
            db=mock_db,
            released_by="u",
            released_by_name="U",
            request=request,
            release_settings=release_settings,
        )

        assert result.status == ReleasePackageStatus.RELEASED
        mock_db.release_packages.update_many.assert_called_once()
        assert mock_db.release_packages.update_one.call_count >= 1
        mock_db.cases.update_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_draft_rejected(self, mock_db, release_settings):
        generating = {
            "id": "pkg",
            "case_id": "c",
            "status": ReleasePackageStatus.GENERATING.value,
        }
        mock_db.release_packages.find_one = AsyncMock(return_value=generating)

        with pytest.raises(ValueError, match="must be in draft status"):
            await release_package_service.release_package(
                package_id="pkg",
                db=mock_db,
                released_by="u",
                released_by_name="U",
                request=ReleasePackageRelease(notify_requester=False),
                release_settings=release_settings,
            )

    @pytest.mark.asyncio
    async def test_release_double_rejected(self, mock_db, release_settings):
        """Releasing an already-released package fails with a clear message."""
        already_released = {
            "id": "pkg",
            "case_id": "c",
            "status": ReleasePackageStatus.RELEASED.value,
        }
        mock_db.release_packages.find_one = AsyncMock(return_value=already_released)

        with pytest.raises(ValueError, match="must be in draft status"):
            await release_package_service.release_package(
                package_id="pkg",
                db=mock_db,
                released_by="u",
                released_by_name="U",
                request=ReleasePackageRelease(notify_requester=False),
                release_settings=release_settings,
            )

    @pytest.mark.asyncio
    async def test_package_not_found_raises(self, mock_db, release_settings):
        mock_db.release_packages.find_one = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="Package not found"):
            await release_package_service.release_package(
                package_id="pkg-missing",
                db=mock_db,
                released_by="u",
                released_by_name="U",
                request=ReleasePackageRelease(notify_requester=False),
                release_settings=release_settings,
            )

    @pytest.mark.asyncio
    async def test_expiration_clamped_to_max(self, mock_db, release_settings):
        draft = _draft_dict()
        released = {**draft, "status": ReleasePackageStatus.RELEASED.value}
        mock_db.release_packages.find_one = AsyncMock(side_effect=[draft, released])
        mock_db.release_packages.update_one = AsyncMock()
        mock_db.release_packages.update_many = AsyncMock()
        mock_db.cases.update_one = AsyncMock()

        # Request 9999 days -> clamped to max_expiration_days (90).
        request = ReleasePackageRelease(
            expires_in_days=9999,
            max_downloads=None,
            notify_requester=False,
        )

        before = datetime.utcnow()
        await release_package_service.release_package(
            package_id="pkg",
            db=mock_db,
            released_by="u",
            released_by_name="U",
            request=request,
            release_settings=release_settings,
        )

        release_call = mock_db.release_packages.update_one.call_args_list[0]
        set_payload = release_call[0][1]["$set"]
        days = (set_payload["expires_at"] - before).days
        assert 89 <= days <= 91

    @pytest.mark.asyncio
    async def test_expiration_clamped_to_min(self, mock_db, release_settings):
        draft = _draft_dict()
        released = {**draft, "status": ReleasePackageStatus.RELEASED.value}
        mock_db.release_packages.find_one = AsyncMock(side_effect=[draft, released])
        mock_db.release_packages.update_one = AsyncMock()
        mock_db.release_packages.update_many = AsyncMock()
        mock_db.cases.update_one = AsyncMock()

        # Request 1 day -> clamped UP to min_expiration_days (7).
        request = ReleasePackageRelease(expires_in_days=1, notify_requester=False)

        before = datetime.utcnow()
        await release_package_service.release_package(
            package_id="pkg",
            db=mock_db,
            released_by="u",
            released_by_name="U",
            request=request,
            release_settings=release_settings,
        )

        release_call = mock_db.release_packages.update_one.call_args_list[0]
        set_payload = release_call[0][1]["$set"]
        days = (set_payload["expires_at"] - before).days
        assert 6 <= days <= 8

    @pytest.mark.asyncio
    async def test_max_downloads_unlimited_branch(self, mock_db, release_settings):
        draft = _draft_dict()
        released = {**draft, "status": ReleasePackageStatus.RELEASED.value}
        mock_db.release_packages.find_one = AsyncMock(side_effect=[draft, released])
        mock_db.release_packages.update_one = AsyncMock()
        mock_db.release_packages.update_many = AsyncMock()
        mock_db.cases.update_one = AsyncMock()

        unlimited_settings = {**release_settings, "unlimited_downloads_allowed": True}
        request = ReleasePackageRelease(
            max_downloads=999999,
            notify_requester=False,
        )

        await release_package_service.release_package(
            package_id="pkg",
            db=mock_db,
            released_by="u",
            released_by_name="U",
            request=request,
            release_settings=unlimited_settings,
        )

        release_call = mock_db.release_packages.update_one.call_args_list[0]
        set_payload = release_call[0][1]["$set"]
        # With unlimited allowed, the requested 999999 passes through unclamped.
        assert set_payload["max_downloads"] == 999999

    @pytest.mark.asyncio
    async def test_max_downloads_falsy_falls_through_to_max_limit(self, mock_db, release_settings):
        draft = _draft_dict()
        released = {**draft, "status": ReleasePackageStatus.RELEASED.value}
        mock_db.release_packages.find_one = AsyncMock(side_effect=[draft, released])
        mock_db.release_packages.update_one = AsyncMock()
        mock_db.release_packages.update_many = AsyncMock()
        mock_db.cases.update_one = AsyncMock()

        # Pin reality: when `request.max_downloads` is 0 and the
        # `default_max_downloads` setting is also 0 (or absent and
        # request supplies 0), the conditional-min collapses to
        # `else max_limit` and the service emits the `max_downloads_limit`
        # setting (100). This is the only path that exercises the
        # ternary's else branch.
        settings = {**release_settings, "default_max_downloads": 0}
        request = ReleasePackageRelease(max_downloads=0, notify_requester=False)

        await release_package_service.release_package(
            package_id="pkg",
            db=mock_db,
            released_by="u",
            released_by_name="U",
            request=request,
            release_settings=settings,
        )

        release_call = mock_db.release_packages.update_one.call_args_list[0]
        set_payload = release_call[0][1]["$set"]
        assert set_payload["max_downloads"] == 100

    @pytest.mark.asyncio
    async def test_revokes_previous_release(self, mock_db, release_settings):
        draft = _draft_dict(id="pkg-new")
        released = {**draft, "status": ReleasePackageStatus.RELEASED.value}
        mock_db.release_packages.find_one = AsyncMock(side_effect=[draft, released])
        mock_db.release_packages.update_one = AsyncMock()
        mock_db.release_packages.update_many = AsyncMock()
        mock_db.cases.update_one = AsyncMock()

        await release_package_service.release_package(
            package_id="pkg-new",
            db=mock_db,
            released_by="u",
            released_by_name="U",
            request=ReleasePackageRelease(notify_requester=False),
            release_settings=release_settings,
        )

        mock_db.release_packages.update_many.assert_called_once()
        filt = mock_db.release_packages.update_many.call_args[0][0]
        assert filt["case_id"] == "case-123"
        assert filt["status"] == ReleasePackageStatus.RELEASED.value
        assert filt["id"] == {"$ne": "pkg-new"}

    @pytest.mark.asyncio
    async def test_notify_requester_writes_audit_field(self, mock_db, release_settings):
        draft = _draft_dict()
        released = {**draft, "status": ReleasePackageStatus.RELEASED.value}
        mock_db.release_packages.find_one = AsyncMock(side_effect=[draft, released])
        mock_db.release_packages.update_one = AsyncMock()
        mock_db.release_packages.update_many = AsyncMock()
        mock_db.cases.update_one = AsyncMock()

        await release_package_service.release_package(
            package_id="pkg",
            db=mock_db,
            released_by="u",
            released_by_name="U",
            request=ReleasePackageRelease(notify_requester=True),
            release_settings=release_settings,
        )

        # Two update_one calls: the release write, then the notify-flag write.
        calls = mock_db.release_packages.update_one.call_args_list
        assert len(calls) == 2
        notify_payload = calls[1][0][1]["$set"]
        assert notify_payload["requester_notified"] is True

    @pytest.mark.asyncio
    async def test_no_notification_skips_notify_field(self, mock_db, release_settings):
        draft = _draft_dict()
        released = {**draft, "status": ReleasePackageStatus.RELEASED.value}
        mock_db.release_packages.find_one = AsyncMock(side_effect=[draft, released])
        mock_db.release_packages.update_one = AsyncMock()
        mock_db.release_packages.update_many = AsyncMock()
        mock_db.cases.update_one = AsyncMock()

        await release_package_service.release_package(
            package_id="pkg",
            db=mock_db,
            released_by="u",
            released_by_name="U",
            request=ReleasePackageRelease(notify_requester=False),
            release_settings=release_settings,
        )

        # Only one update_one (the release write) -- no notify follow-up.
        assert mock_db.release_packages.update_one.call_count == 1


# ---------------------------------------------------------------------------
# get_release_package / get_release_package_by_token
# ---------------------------------------------------------------------------


class TestGetReleasePackage:
    @pytest.mark.asyncio
    async def test_get_by_id_returns_package(self, mock_db):
        pkg = {
            "id": "pkg-1",
            "case_id": "c",
            "status": ReleasePackageStatus.DRAFT.value,
            "filename": "f.zip",
            "size_bytes": 0,
            "document_count": 0,
            "total_redactions": 0,
            "access_token": "t",
            "created_at": datetime.utcnow(),
            "created_by": "u",
            "created_by_name": "U",
        }
        mock_db.release_packages.find_one = AsyncMock(return_value=pkg)

        result = await release_package_service.get_release_package("pkg-1", mock_db)

        assert result is not None
        assert result.id == "pkg-1"

    @pytest.mark.asyncio
    async def test_get_by_id_returns_none_when_missing(self, mock_db):
        mock_db.release_packages.find_one = AsyncMock(return_value=None)

        result = await release_package_service.get_release_package("missing", mock_db)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_token_returns_package(self, mock_db):
        pkg = {
            "id": "pkg-1",
            "case_id": "c",
            "status": ReleasePackageStatus.RELEASED.value,
            "filename": "f.zip",
            "size_bytes": 0,
            "document_count": 0,
            "total_redactions": 0,
            "access_token": "secure-tok",
            "created_at": datetime.utcnow(),
            "created_by": "u",
            "created_by_name": "U",
        }
        mock_db.release_packages.find_one = AsyncMock(return_value=pkg)

        result = await release_package_service.get_release_package_by_token(
            "secure-tok",
            mock_db,
        )

        assert result is not None
        mock_db.release_packages.find_one.assert_called_with({"access_token": "secure-tok"})

    @pytest.mark.asyncio
    async def test_get_by_token_returns_none_when_missing(self, mock_db):
        mock_db.release_packages.find_one = AsyncMock(return_value=None)

        result = await release_package_service.get_release_package_by_token(
            "bad-tok",
            mock_db,
        )

        assert result is None


# ---------------------------------------------------------------------------
# download_draft_package (analyst review)
# ---------------------------------------------------------------------------


def _make_pkg(**overrides) -> ReleasePackageDB:
    base = {
        "id": "pkg-1",
        "case_id": "c",
        "filename": "FOI-Release.zip",
        "size_bytes": 0,
        "document_count": 0,
        "total_redactions": 0,
        "access_token": "tok",
        "status": ReleasePackageStatus.DRAFT,
        "created_at": datetime.utcnow(),
        "created_by": "u",
        "created_by_name": "U",
        "file_id": "gridfs-id",
    }
    base.update(overrides)
    return ReleasePackageDB(**base)


class TestDownloadDraftPackage:
    @pytest.mark.asyncio
    async def test_downloads_draft_with_draft_suffix(self, mock_db):
        pkg = _make_pkg(status=ReleasePackageStatus.DRAFT)
        mock_grid_out = MagicMock()
        mock_grid_out.read.return_value = b"ZIP-DRAFT"

        with (
            patch("src.cases.release_package_service.MongoClient") as mock_client,
            patch("src.cases.release_package_service.gridfs.GridFS") as mock_grid_cls,
            patch("src.cases.release_package_service.ObjectId", side_effect=lambda x: x),
        ):
            mock_client.return_value.__getitem__.return_value = MagicMock()
            mock_fs = MagicMock()
            mock_fs.get.return_value = mock_grid_out
            mock_grid_cls.return_value = mock_fs

            content, filename = await release_package_service.download_draft_package(
                package=pkg,
                db=mock_db,
                downloaded_by="user-x",
                ip_address="1.2.3.4",
                user_agent="UA",
            )

        assert content == b"ZIP-DRAFT"
        assert filename == "FOI-Release-DRAFT.zip"
        mock_db.release_packages.update_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_downloads_released_package_for_analyst(self, mock_db):
        pkg = _make_pkg(status=ReleasePackageStatus.RELEASED)
        mock_grid_out = MagicMock()
        mock_grid_out.read.return_value = b"ZIP"

        with (
            patch("src.cases.release_package_service.MongoClient") as mock_client,
            patch("src.cases.release_package_service.gridfs.GridFS") as mock_grid_cls,
            patch("src.cases.release_package_service.ObjectId", side_effect=lambda x: x),
        ):
            mock_client.return_value.__getitem__.return_value = MagicMock()
            mock_fs = MagicMock()
            mock_fs.get.return_value = mock_grid_out
            mock_grid_cls.return_value = mock_fs

            content, _ = await release_package_service.download_draft_package(
                package=pkg,
                db=mock_db,
                downloaded_by="user-x",
            )

        assert content == b"ZIP"

    @pytest.mark.asyncio
    async def test_revoked_status_rejected(self, mock_db):
        pkg = _make_pkg(status=ReleasePackageStatus.REVOKED)

        with pytest.raises(ValueError, match="must be in draft or released status"):
            await release_package_service.download_draft_package(
                package=pkg,
                db=mock_db,
                downloaded_by="user-x",
            )

    @pytest.mark.asyncio
    async def test_no_file_id_rejected(self, mock_db):
        pkg = _make_pkg(file_id=None)

        with pytest.raises(ValueError, match="Package file not found"):
            await release_package_service.download_draft_package(
                package=pkg,
                db=mock_db,
                downloaded_by="user-x",
            )


# ---------------------------------------------------------------------------
# download_public_package
# ---------------------------------------------------------------------------


class TestDownloadPublicPackage:
    @pytest.mark.asyncio
    async def test_downloads_released_package(self, mock_db):
        pkg = _make_pkg(
            status=ReleasePackageStatus.RELEASED,
            expires_at=datetime.utcnow() + timedelta(days=30),
            max_downloads=10,
            download_count=0,
        )
        mock_grid_out = MagicMock()
        mock_grid_out.read.return_value = b"PUBLIC ZIP"

        with (
            patch("src.cases.release_package_service.MongoClient") as mock_client,
            patch("src.cases.release_package_service.gridfs.GridFS") as mock_grid_cls,
            patch("src.cases.release_package_service.ObjectId", side_effect=lambda x: x),
        ):
            mock_client.return_value.__getitem__.return_value = MagicMock()
            mock_fs = MagicMock()
            mock_fs.get.return_value = mock_grid_out
            mock_grid_cls.return_value = mock_fs

            content, filename = await release_package_service.download_public_package(
                package=pkg,
                db=mock_db,
                ip_address="1.2.3.4",
                user_agent="UA",
            )

        assert content == b"PUBLIC ZIP"
        assert filename == pkg.filename
        mock_db.release_packages.update_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_draft_status_rejected_with_specific_message(self, mock_db):
        pkg = _make_pkg(status=ReleasePackageStatus.DRAFT)

        with pytest.raises(ValueError, match="has not been released"):
            await release_package_service.download_public_package(package=pkg, db=mock_db)

    @pytest.mark.asyncio
    async def test_expired_status_rejected(self, mock_db):
        pkg = _make_pkg(status=ReleasePackageStatus.EXPIRED)

        with pytest.raises(ValueError, match="expired"):
            await release_package_service.download_public_package(package=pkg, db=mock_db)

    @pytest.mark.asyncio
    async def test_revoked_status_rejected(self, mock_db):
        pkg = _make_pkg(status=ReleasePackageStatus.REVOKED)

        with pytest.raises(ValueError, match="revoked"):
            await release_package_service.download_public_package(package=pkg, db=mock_db)

    @pytest.mark.asyncio
    async def test_generating_status_rejected_generic(self, mock_db):
        # Pin reality: the GENERATING fallthrough hits the generic
        # "not available for download" branch.
        pkg = _make_pkg(status=ReleasePackageStatus.GENERATING)

        with pytest.raises(ValueError, match="not available for download"):
            await release_package_service.download_public_package(package=pkg, db=mock_db)

    @pytest.mark.asyncio
    async def test_past_expiration_marks_expired_then_rejects(self, mock_db):
        pkg = _make_pkg(
            status=ReleasePackageStatus.RELEASED,
            expires_at=datetime.utcnow() - timedelta(days=1),
        )

        with pytest.raises(ValueError, match="expired"):
            await release_package_service.download_public_package(package=pkg, db=mock_db)

        # The expiry path flips the package's stored status to EXPIRED so
        # subsequent reads short-circuit.
        mock_db.release_packages.update_one.assert_called_once()
        update_call = mock_db.release_packages.update_one.call_args
        assert update_call[0][1]["$set"]["status"] == ReleasePackageStatus.EXPIRED.value

    @pytest.mark.asyncio
    async def test_download_limit_reached(self, mock_db):
        pkg = _make_pkg(
            status=ReleasePackageStatus.RELEASED,
            expires_at=datetime.utcnow() + timedelta(days=30),
            max_downloads=10,
            download_count=10,
        )

        with pytest.raises(ValueError, match="Download limit reached"):
            await release_package_service.download_public_package(package=pkg, db=mock_db)

    @pytest.mark.asyncio
    async def test_no_file_id_rejected(self, mock_db):
        pkg = _make_pkg(
            status=ReleasePackageStatus.RELEASED,
            expires_at=datetime.utcnow() + timedelta(days=30),
            file_id=None,
        )

        with pytest.raises(ValueError, match="Package file not found"):
            await release_package_service.download_public_package(package=pkg, db=mock_db)


# ---------------------------------------------------------------------------
# revoke_release_package
# ---------------------------------------------------------------------------


class TestRevokeReleasePackage:
    @pytest.mark.asyncio
    async def test_revokes_existing_package(self, mock_db):
        mock_db.release_packages.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
        mock_db.cases.update_one = AsyncMock()

        result = await release_package_service.revoke_release_package(
            package_id="pkg-123",
            db=mock_db,
            revoked_by="admin",
        )

        assert result is True
        mock_db.release_packages.update_one.assert_called_once()
        mock_db.cases.update_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_returns_false(self, mock_db):
        mock_db.release_packages.update_one = AsyncMock(return_value=MagicMock(modified_count=0))

        result = await release_package_service.revoke_release_package(
            package_id="ghost",
            db=mock_db,
            revoked_by="admin",
        )

        assert result is False
        # No case-side update fires when the package update was a no-op.
        mock_db.cases.update_one.assert_not_called()


# ---------------------------------------------------------------------------
# list_release_packages - pinned as dead code per audit Section 3e
# ---------------------------------------------------------------------------


class TestListReleasePackages:
    """`list_release_packages` is currently unreferenced from any route or
    service (verified via `grep -r "list_release_packages" backend/src`).

    Audit Section 3e flagged this. We still cover both branches so coverage
    stays at 100% and the function's contract is documented if it's wired
    back up -- but the function itself is a candidate for removal."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_packages(self, mock_db):
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.to_list = AsyncMock(return_value=[])
        mock_db.release_packages.find = MagicMock(return_value=cursor)

        result = await release_package_service.list_release_packages("case-123", mock_db)

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_packages_for_case(self, mock_db):
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.to_list = AsyncMock(
            return_value=[
                {
                    "id": "pkg-1",
                    "case_id": "case-123",
                    "status": ReleasePackageStatus.RELEASED.value,
                    "filename": "f.zip",
                    "size_bytes": 0,
                    "document_count": 0,
                    "total_redactions": 0,
                    "access_token": "t",
                    "created_at": datetime.utcnow(),
                    "created_by": "u",
                    "created_by_name": "U",
                }
            ]
        )
        mock_db.release_packages.find = MagicMock(return_value=cursor)

        result = await release_package_service.list_release_packages("case-123", mock_db)

        assert len(result) == 1
        assert isinstance(result[0], ReleasePackageDB)
        assert result[0].id == "pkg-1"


# ---------------------------------------------------------------------------
# get_current_package_state
# ---------------------------------------------------------------------------


class TestGetCurrentPackageState:
    @pytest.mark.asyncio
    async def test_returns_both_when_present(self, mock_db):
        draft = {
            "id": "draft",
            "case_id": "case-123",
            "status": ReleasePackageStatus.DRAFT.value,
            "filename": "f.zip",
            "size_bytes": 0,
            "document_count": 0,
            "total_redactions": 0,
            "access_token": "t",
            "created_at": datetime.utcnow(),
            "created_by": "u",
            "created_by_name": "U",
        }
        release = {**draft, "id": "release", "status": ReleasePackageStatus.RELEASED.value}
        mock_db.release_packages.find_one = AsyncMock(side_effect=[draft, release])

        d, r = await release_package_service.get_current_package_state(
            case_id="case-123",
            db=mock_db,
        )

        assert d is not None and d.id == "draft"
        assert r is not None and r.id == "release"

    @pytest.mark.asyncio
    async def test_returns_none_for_both_when_absent(self, mock_db):
        mock_db.release_packages.find_one = AsyncMock(return_value=None)

        d, r = await release_package_service.get_current_package_state(
            case_id="case-123",
            db=mock_db,
        )

        assert d is None
        assert r is None
