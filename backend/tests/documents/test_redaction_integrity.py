"""End-to-end redaction integrity: what an analyst applies is what the
release removes (DOC-02, DOC-05, DOC-07, DOC-13, DOC-19 follow-up).

These tests drive the real routes against the Mongo testcontainer, store
real PDFs in GridFS, run the real release-package generator and then read
the released PDF back with PyMuPDF. A redaction that leaves text
recoverable is a data breach, so every assertion is on extracted text.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from datetime import datetime
from typing import Any

import fitz  # PyMuPDF
import pytest
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase, AsyncIOMotorGridFSBucket

from src.cases import release_package_service
from src.cases.release_package_models import ReleasePackageGenerate
from src.utils.ai_redaction import enrich_suggestions_with_coordinates
from tests.factories import make_case, make_document

SECRET = "Alice Smith"


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_all_db(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase, app, mongo_uri):
    import src.database as db_mod
    import src.dependencies as deps_mod
    from src.documents import (
        document_status_routes,
        redaction_routes,
        redaction_suggestion_routes,
    )
    from src.documents import routes as documents_routes

    async def _override_get_db():
        return db

    overridden = [
        redaction_routes.get_db,
        redaction_suggestion_routes.get_db,
        documents_routes.get_db,
        document_status_routes.get_db,
    ]
    for dep in overridden:
        app.dependency_overrides[dep] = _override_get_db
    monkeypatch.setattr(redaction_suggestion_routes, "db", db)
    monkeypatch.setattr(deps_mod, "users", db.users)
    monkeypatch.setattr(db_mod, "users", db.users)
    monkeypatch.setattr(release_package_service, "MONGODB_URI", mongo_uri)
    yield db
    for dep in overridden:
        app.dependency_overrides.pop(dep, None)


def make_pdf(lines: list[tuple[float, str]], rotation: int = 0, **meta: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    for y, text in lines:
        page.insert_text((72, y), text, fontsize=12)
    if rotation:
        page.set_rotation(rotation)
    if meta:
        doc.set_metadata(meta)
    data = doc.tobytes()
    doc.close()
    return data


def displayed_box(pdf: bytes, text: str, occurrence: int = 0) -> dict[str, float]:
    doc = fitz.open(stream=pdf, filetype="pdf")
    page = doc[0]
    rect = page.search_for(text)[occurrence] * page.rotation_matrix
    doc.close()
    return {"page": 1, "x": rect.x0, "y": rect.y0, "width": rect.width, "height": rect.height}


async def store_pdf(db: AsyncIOMotorDatabase, pdf: bytes) -> ObjectId:
    bucket = AsyncIOMotorGridFSBucket(db)
    return await bucket.upload_from_stream("doc.pdf", pdf)


async def seed_doc(db: AsyncIOMotorDatabase, case_id: str, pdf: bytes | None, **extra: Any) -> str:
    fields: dict[str, Any] = {"case_id": case_id, "status": "approved", "page_dims": None}
    if pdf is not None:
        fields["content_file_id"] = await store_pdf(db, pdf)
    fields.update(extra)
    doc = make_document(**fields)
    await db.documents.insert_one(doc)
    return doc["id"]


async def seed_case(db: AsyncIOMotorDatabase, team: list[tuple[str, str]] | None = None) -> str:
    case = make_case(
        case_team=[
            {"user_id": uid, "role": role, "status": "active", "added_at": "2026-01-01"}
            for uid, role in (team or [])
        ]
    )
    await db.cases.insert_one(case)
    return case["id"]


async def generate_release(db: AsyncIOMotorDatabase, case_id: str) -> dict[str, Any]:
    package_id = str(uuid.uuid4())
    await db.release_packages.insert_one(
        {
            "id": package_id,
            "case_id": case_id,
            "filename": "FOI-Release.zip",
            "access_token": "tok",
            "created_at": datetime.utcnow(),
            "created_by": "u",
            "created_by_name": "U",
            "status": "generating",
        }
    )
    await release_package_service.process_package_generation(
        package_id=package_id,
        case_id=case_id,
        db=db,
        request=ReleasePackageGenerate(include_cover_letter=False),
        release_settings={"include_manifest": True},
    )
    return await db.release_packages.find_one({"id": package_id})


async def released_pdfs(db: AsyncIOMotorDatabase, package: dict[str, Any]) -> dict[str, bytes]:
    bucket = AsyncIOMotorGridFSBucket(db)
    stream = await bucket.open_download_stream(ObjectId(package["file_id"]))
    archive = zipfile.ZipFile(io.BytesIO(await stream.read()))
    return {n: archive.read(n) for n in archive.namelist() if n.endswith(".pdf")}


def pdf_text(pdf: bytes) -> str:
    doc = fitz.open(stream=pdf, filetype="pdf")
    try:
        return "".join(page.get_text() for page in doc)
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# DOC-02 / LLM-01: bulk-applied AI suggestions and bulk text redactions
# ---------------------------------------------------------------------------


class TestBulkAppliedRedactionsAreBurnedIn:
    async def test_ai_suggestion_in_stored_shape_is_removed_from_release(
        self, db, authed_client_factory, patch_all_db
    ) -> None:
        pdf = make_pdf([(100, f"Requester: {SECRET} called"), (300, "public paragraph")])
        # The exact shape the viewer route caches: geometry nested under
        # "coordinates", produced by the real enrichment helper.
        suggestions = enrich_suggestions_with_coordinates(
            [{"text": SECRET, "category": "S22", "confidence": "high", "reason": "name"}], pdf
        )
        assert "x" not in suggestions[0] and suggestions[0]["coordinates"]["width"] > 0

        case_id = await seed_case(db)
        doc_id = await seed_doc(
            db, case_id, pdf, ai_suggestions={"suggestions": suggestions, "summary": "s"}
        )
        client = await authed_client_factory(role="analyst")

        r = await client.post(
            "/api/v1/documents/bulk/apply-ai-suggestions",
            json={"case_id": case_id, "confidence_threshold": "medium"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["suggestions_applied"] == 1

        stored = (await db.documents.find_one({"id": doc_id}))["redactions"]
        assert len(stored) == 1
        assert stored[0]["width"] > 0 and stored[0]["height"] > 0
        assert stored[0]["id"] and stored[0]["status"] == "approved"

        package = await generate_release(db, case_id)
        assert package["status"] == "draft", package.get("generation_message")
        (released,) = (await released_pdfs(db, package)).values()
        text = pdf_text(released)
        assert SECRET not in text
        assert "public paragraph" in text

    async def test_ai_suggestion_on_rotated_page_is_removed(
        self, db, authed_client_factory, patch_all_db
    ) -> None:
        pdf = make_pdf([(100, f"Requester: {SECRET} called")], rotation=90)
        suggestions = enrich_suggestions_with_coordinates(
            [{"text": SECRET, "category": "S22", "confidence": "high"}], pdf
        )
        case_id = await seed_case(db)
        await seed_doc(db, case_id, pdf, ai_suggestions={"suggestions": suggestions})
        client = await authed_client_factory(role="analyst")

        r = await client.post(
            "/api/v1/documents/bulk/apply-ai-suggestions", json={"case_id": case_id}
        )
        assert r.status_code == 200, r.text

        package = await generate_release(db, case_id)
        assert package["status"] == "draft", package.get("generation_message")
        (released,) = (await released_pdfs(db, package)).values()
        assert SECRET not in pdf_text(released)

    async def test_ai_suggestion_with_off_page_box_is_rejected_with_422(
        self, db, authed_client_factory, patch_all_db
    ) -> None:
        pdf = make_pdf([(100, SECRET)])
        bad = {
            "text": SECRET,
            "category": "S22",
            "confidence": "high",
            "page": 3,
            "has_coordinates": True,
            "coordinates": {"x": 10, "y": 10, "width": 50, "height": 10},
        }
        case_id = await seed_case(db)
        doc_id = await seed_doc(db, case_id, pdf, ai_suggestions={"suggestions": [bad]})
        client = await authed_client_factory(role="analyst")

        r = await client.post(
            "/api/v1/documents/bulk/apply-ai-suggestions", json={"case_id": case_id}
        )
        assert r.status_code == 422, r.text
        assert (await db.documents.find_one({"id": doc_id}))["redactions"] == []

    async def test_bulk_text_redaction_is_located_and_removed(
        self, db, authed_client_factory, patch_all_db
    ) -> None:
        pdf = make_pdf([(100, f"From {SECRET}"), (200, f"cc {SECRET} and others")])
        case_id = await seed_case(db)
        doc_id = await seed_doc(db, case_id, pdf, extracted_text=f"From {SECRET} cc {SECRET}")
        client = await authed_client_factory(role="analyst")

        r = await client.post(
            "/api/v1/documents/bulk/apply-redaction",
            json={
                "case_id": case_id,
                "search_text": SECRET,
                "category": "S22",
                "reason": "personal information",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["redactions_created"] == 2
        assert body["unresolved_documents"] == []

        stored = (await db.documents.find_one({"id": doc_id}))["redactions"]
        assert all(s["width"] > 0 and s["id"] and not s.get("needs_coordinates") for s in stored)

        package = await generate_release(db, case_id)
        assert package["status"] == "draft", package.get("generation_message")
        (released,) = (await released_pdfs(db, package)).values()
        text = pdf_text(released)
        assert SECRET not in text
        assert "and others" in text

    async def test_bulk_text_match_that_cannot_be_located_is_reported(
        self, db, authed_client_factory, patch_all_db
    ) -> None:
        # extracted_text says the name is there, the PDF layer does not have
        # it (e.g. image-only page with no OCR words). Nothing silent.
        pdf = make_pdf([(100, "no names here")])
        case_id = await seed_case(db)
        doc_id = await seed_doc(db, case_id, pdf, extracted_text=f"hello {SECRET}")
        client = await authed_client_factory(role="analyst")

        r = await client.post(
            "/api/v1/documents/bulk/apply-redaction",
            json={"case_id": case_id, "search_text": SECRET, "category": "S22", "reason": "x"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is False
        assert body["redactions_created"] == 0
        assert [u["document_id"] for u in body["unresolved_documents"]] == [doc_id]


# ---------------------------------------------------------------------------
# DOC-13: one release rule for export and release
# ---------------------------------------------------------------------------


class TestReleaseRule:
    async def _seed_mixed(self, db) -> tuple[str, str, bytes]:
        pdf = make_pdf([(100, "APPROVEDSECRET"), (300, "REJECTEDTEXT")])
        case_id = await seed_case(db)
        doc_id = await seed_doc(
            db,
            case_id,
            pdf,
            redactions=[
                {"id": "a", "status": "approved", **displayed_box(pdf, "APPROVEDSECRET")},
                {"id": "r", "status": "rejected", **displayed_box(pdf, "REJECTEDTEXT")},
            ],
        )
        return case_id, doc_id, pdf

    async def test_export_applies_only_approved(
        self, db, authed_client_factory, patch_all_db
    ) -> None:
        _, doc_id, _ = await self._seed_mixed(db)
        client = await authed_client_factory(role="analyst")
        r = await client.get(f"/api/v1/documents/{doc_id}/export")
        assert r.status_code == 200, r.text
        text = pdf_text(r.content)
        assert "APPROVEDSECRET" not in text
        assert "REJECTEDTEXT" in text

    async def test_release_applies_only_approved(self, db, patch_all_db) -> None:
        case_id, _, _ = await self._seed_mixed(db)
        package = await generate_release(db, case_id)
        assert package["status"] == "draft", package.get("generation_message")
        assert package["total_redactions"] == 1
        (released,) = (await released_pdfs(db, package)).values()
        text = pdf_text(released)
        assert "APPROVEDSECRET" not in text
        assert "REJECTEDTEXT" in text

    async def test_unresolved_redaction_blocks_export_and_release(
        self, db, authed_client_factory, patch_all_db
    ) -> None:
        pdf = make_pdf([(100, "PROPOSEDTEXT")])
        case_id = await seed_case(db)
        doc_id = await seed_doc(
            db,
            case_id,
            pdf,
            redactions=[
                {
                    "id": "p",
                    "type": "proposed",
                    "status": "proposed",
                    **displayed_box(pdf, "PROPOSEDTEXT"),
                }
            ],
        )
        client = await authed_client_factory(role="analyst")
        r = await client.get(f"/api/v1/documents/{doc_id}/export")
        assert r.status_code == 409, r.text

        package = await generate_release(db, case_id)
        assert package["status"] == "failed"
        assert package.get("file_id") is None
        assert [f["document_id"] for f in package["failed_documents"]] == [doc_id]
        assert "awaiting review" in package["failed_documents"][0]["reason"]


# ---------------------------------------------------------------------------
# DOC-05 / DOC-07 / DOC-19 in the release path
# ---------------------------------------------------------------------------


class TestReleasePackageSafety:
    async def test_zero_redaction_document_is_sanitised(self, db, patch_all_db) -> None:
        pdf = make_pdf([(100, "body")], author="Jane Records", title="internal title")
        case_id = await seed_case(db)
        await seed_doc(db, case_id, pdf)
        package = await generate_release(db, case_id)
        assert package["status"] == "draft", package.get("generation_message")
        (released,) = (await released_pdfs(db, package)).values()
        assert released != pdf
        doc = fitz.open(stream=released, filetype="pdf")
        assert not doc.metadata.get("author") and not doc.metadata.get("title")
        doc.close()

    async def test_invalid_stored_redaction_fails_that_document_loudly(
        self, db, patch_all_db
    ) -> None:
        pdf = make_pdf([(100, SECRET)])
        case_id = await seed_case(db)
        doc_id = await seed_doc(
            db,
            case_id,
            pdf,
            redactions=[{"id": "z", "status": "approved", "page": 1, "x": 0, "y": 0}],
        )
        package = await generate_release(db, case_id)
        assert package["status"] == "failed"
        assert package.get("file_id") is None
        assert package["failed_documents"][0]["document_id"] == doc_id

    async def test_conversion_failed_document_is_skipped_and_flagged(
        self, db, patch_all_db
    ) -> None:
        good = make_pdf([(100, "releasable")])
        case_id = await seed_case(db)
        await seed_doc(db, case_id, good)
        bad_id = await seed_doc(
            db,
            case_id,
            b"PK\x03\x04 native docx bytes",
            conversion_failed=True,
            filename="report.docx",
        )
        package = await generate_release(db, case_id)
        assert package["status"] == "draft", package.get("generation_message")
        assert package["document_count"] == 1
        assert [s["document_id"] for s in package["skipped_documents"]] == [bad_id]
        names = list((await released_pdfs(db, package)).keys())
        assert len(names) == 1 and "report" not in names[0]

    async def test_zip_entry_names_are_sanitised(self, db, patch_all_db) -> None:
        pdf = make_pdf([(100, "body")])
        case_id = await seed_case(db)
        await seed_doc(db, case_id, pdf, filename="../../../etc/evil\r\n.pdf")
        package = await generate_release(db, case_id)
        assert package["status"] == "draft", package.get("generation_message")
        (name,) = (await released_pdfs(db, package)).keys()
        assert "/" not in name and "\\" not in name and ".." not in name
        assert "\r" not in name and "\n" not in name
