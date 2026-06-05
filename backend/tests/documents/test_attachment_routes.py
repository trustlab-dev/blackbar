"""Integration tests for `src.documents.attachment_routes`.

Phase 2.3.C (1/5). Target >=80% line coverage on
`src.documents.attachment_routes` — per-document attachment listing,
binary content fetch, and AI analysis fetch.

Endpoints under test (all mounted at `/api/v1/documents/...` because
`attachment_router` is `include_router`'d under `documents/routes.py`
which is mounted at `/api/v1/documents`):

    GET    /{document_id}/attachments
    GET    /{document_id}/attachments/{attachment_id}
    GET    /{document_id}/attachments/{attachment_id}/analysis

**Auth model nuance:** all three endpoints use `check_role(...)` (4-tier
system roles). The list endpoint additionally allows `guest`; the other
two require `owner/admin/analyst/user`. List+guest also runs
`check_document_access` which respects `shared_with`.

Source-API findings pinned (audit Section 11 candidates):
- `get_attachment` and `get_attachment_analysis` only verify the
  attachment id is in the parent doc's `attachment_ids` array — they
  do NOT run `check_document_access`. A user/analyst with no relation
  to the parent case can still pull binary content as long as the role
  decorator passes. Pinned in tests; flagged for B-finding.
- `get_attachment_analysis`'s 404 for "Attachment not found" (line 128)
  is unreachable in practice: if the attachment_id is in the parent's
  `attachment_ids` list, the attachment was inserted there by the
  processing pipeline; an attachment that disappears between the
  parent-doc lookup and the projection lookup would hit it. Race
  condition only.
"""

from __future__ import annotations

from typing import Any

import pytest
from motor.motor_asyncio import AsyncIOMotorDatabase

from tests.factories import make_case, make_document

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_routes_db(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase, app):
    """Rebind the attachment routes' `get_db` and dependencies module's
    captured `users` to the per-test motor database. attachment_routes
    has its own get_db helper; documents/routes.py also defines one
    that backs the parent route's deps. Override both."""
    import src.database as db_mod
    import src.dependencies as deps_mod
    from src.documents import attachment_routes
    from src.documents import routes as documents_routes

    async def _override_get_db():
        return db

    app.dependency_overrides[attachment_routes.get_db] = _override_get_db
    app.dependency_overrides[documents_routes.get_db] = _override_get_db
    monkeypatch.setattr(deps_mod, "users", db.users)
    monkeypatch.setattr(db_mod, "users", db.users)

    yield db

    app.dependency_overrides.pop(attachment_routes.get_db, None)
    app.dependency_overrides.pop(documents_routes.get_db, None)


async def _seed_doc_with_attachments(
    db: AsyncIOMotorDatabase,
    case_id: str,
    *,
    attachments: list[dict[str, Any]] | None = None,
    **doc_overrides: Any,
) -> tuple[str, list[str]]:
    """Seed a parent document with `has_attachments=True` and N child
    attachment docs. Returns (parent_doc_id, [attachment_id, ...])."""
    attachments = attachments or []
    att_ids = []
    for att in attachments:
        att_doc = make_document(**att)
        await db.documents.insert_one(att_doc)
        att_ids.append(att_doc["id"])
    parent = make_document(
        case_id=case_id,
        has_attachments=bool(att_ids),
        attachment_ids=att_ids,
        **doc_overrides,
    )
    await db.documents.insert_one(parent)
    return parent["id"], att_ids


async def _seed_case(
    db: AsyncIOMotorDatabase,
    *,
    case_team: list[dict[str, Any]] | None = None,
    **case_overrides: Any,
) -> str:
    case = make_case(case_team=case_team or [], **case_overrides)
    await db.cases.insert_one(case)
    return case["id"]


# ---------------------------------------------------------------------------
# GET /{document_id}/attachments
# ---------------------------------------------------------------------------


class TestListAttachments:
    async def test_admin_lists_attachments_with_metadata(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        parent_id, att_ids = await _seed_doc_with_attachments(
            db,
            case_id,
            attachments=[
                {
                    "filename": "att1.pdf",
                    "mime_type": "application/pdf",
                    "size": 123,
                },
                {
                    "filename": "att2.png",
                    "mime_type": "image/png",
                    "size": 456,
                },
            ],
        )
        r = await client.get(f"/api/v1/documents/{parent_id}/attachments")
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body) == 2
        filenames = {item["filename"] for item in body}
        assert filenames == {"att1.pdf", "att2.png"}
        assert all("id" in item for item in body)
        # Pinned response shape
        assert {"id", "filename", "mime_type", "size", "upload_date"} <= set(body[0].keys())

    async def test_list_returns_empty_when_no_attachments(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """has_attachments=False / empty attachment_ids -> empty list, not 404."""
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        parent_id, _ = await _seed_doc_with_attachments(db, case_id)
        r = await client.get(f"/api/v1/documents/{parent_id}/attachments")
        assert r.status_code == 200
        assert r.json() == []

    async def test_list_document_not_found(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/documents/ghost/attachments")
        assert r.status_code == 404
        assert "Document not found" in r.text

    async def test_list_guest_with_share_can_access(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Guest listed in `shared_with` passes `check_document_access`."""
        client = await authed_client_factory(role="guest", email="gst-att@example.com")
        me = await db.users.find_one({"email": "gst-att@example.com"})
        case_id = await _seed_case(db)
        parent_id, _ = await _seed_doc_with_attachments(
            db,
            case_id,
            attachments=[{"filename": "x.pdf"}],
            shared_with=[{"user_id": me["id"]}],
        )
        r = await client.get(f"/api/v1/documents/{parent_id}/attachments")
        assert r.status_code == 200
        assert len(r.json()) == 1

    async def test_list_guest_without_share_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Guest not in `shared_with` -> 403 (passes role gate, fails
        access gate)."""
        client = await authed_client_factory(role="guest", email="gst2-att@example.com")
        case_id = await _seed_case(db)
        parent_id, _ = await _seed_doc_with_attachments(db, case_id)
        r = await client.get(f"/api/v1/documents/{parent_id}/attachments")
        assert r.status_code == 403
        assert "don't have access" in r.text

    async def test_list_user_off_team_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Non-admin user not on case team -> 403."""
        client = await authed_client_factory(role="user", email="off-att@example.com")
        case_id = await _seed_case(
            db, case_team=[{"user_id": "someone-else", "role": "analyst", "status": "active"}]
        )
        parent_id, _ = await _seed_doc_with_attachments(db, case_id)
        r = await client.get(f"/api/v1/documents/{parent_id}/attachments")
        assert r.status_code == 403

    async def test_list_user_on_team_can_access(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="user", email="on-att@example.com")
        me = await db.users.find_one({"email": "on-att@example.com"})
        case_id = await _seed_case(
            db, case_team=[{"user_id": me["id"], "role": "analyst", "status": "active"}]
        )
        parent_id, _ = await _seed_doc_with_attachments(
            db, case_id, attachments=[{"filename": "x.pdf"}]
        )
        r = await client.get(f"/api/v1/documents/{parent_id}/attachments")
        assert r.status_code == 200
        assert len(r.json()) == 1


# ---------------------------------------------------------------------------
# GET /{document_id}/attachments/{attachment_id}
# ---------------------------------------------------------------------------


class TestGetAttachment:
    async def test_admin_fetches_attachment_binary(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        # Pre-construct attachment with content+filename then attach it.
        from tests.factories import make_document as _md

        att = _md(
            filename="report.pdf",
            mime_type="application/pdf",
            content=b"%PDF-1.4 fake bytes",
        )
        await db.documents.insert_one(att)
        parent = _md(case_id=case_id, has_attachments=True, attachment_ids=[att["id"]])
        await db.documents.insert_one(parent)

        r = await client.get(f"/api/v1/documents/{parent['id']}/attachments/{att['id']}")
        assert r.status_code == 200, r.text
        assert r.content == b"%PDF-1.4 fake bytes"
        assert r.headers["content-type"] == "application/pdf"
        assert 'filename="report.pdf"' in r.headers["content-disposition"]

    async def test_get_attachment_not_in_parent_attachment_ids(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """attachment_id not listed in parent.attachment_ids -> 404."""
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        parent_id, _ = await _seed_doc_with_attachments(db, case_id)
        r = await client.get(f"/api/v1/documents/{parent_id}/attachments/ghost")
        assert r.status_code == 404
        assert "Document or attachment not found" in r.text

    async def test_get_attachment_parent_doc_not_found(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/documents/ghost/attachments/x")
        assert r.status_code == 404

    async def test_get_attachment_guest_forbidden_by_role(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """The role decorator for this endpoint excludes guest, even
        though list_attachments allows guest."""
        client = await authed_client_factory(role="guest")
        case_id = await _seed_case(db)
        parent_id, att_ids = await _seed_doc_with_attachments(
            db, case_id, attachments=[{"filename": "x.pdf"}]
        )
        r = await client.get(f"/api/v1/documents/{parent_id}/attachments/{att_ids[0]}")
        assert r.status_code == 403

    async def test_get_attachment_disappeared_returns_404(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Parent doc's attachment_ids references an attachment that
        doesn't exist as its own document. Pins the "Attachment not
        found" branch (separate from "Document or attachment not found")."""
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        # Manually create parent with an orphan attachment id (no
        # corresponding child doc).
        parent = make_document(
            case_id=case_id,
            has_attachments=True,
            attachment_ids=["orphan-att-id"],
        )
        await db.documents.insert_one(parent)
        r = await client.get(f"/api/v1/documents/{parent['id']}/attachments/orphan-att-id")
        assert r.status_code == 404
        assert "Attachment not found" in r.text


# ---------------------------------------------------------------------------
# GET /{document_id}/attachments/{attachment_id}/analysis
# ---------------------------------------------------------------------------


class TestGetAttachmentAnalysis:
    async def test_admin_fetches_analysis(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        from tests.factories import make_document as _md

        att = _md(
            filename="email.eml",
            processed=True,
            summary="This is a summary",
            ai_suggestions=[{"kind": "redact", "text": "John Doe"}],
            processing_error=None,
        )
        await db.documents.insert_one(att)
        parent = _md(case_id=case_id, has_attachments=True, attachment_ids=[att["id"]])
        await db.documents.insert_one(parent)
        r = await client.get(f"/api/v1/documents/{parent['id']}/attachments/{att['id']}/analysis")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["id"] == att["id"]
        assert body["filename"] == "email.eml"
        assert body["processed"] is True
        assert body["summary"] == "This is a summary"
        assert body["ai_suggestions"] == [{"kind": "redact", "text": "John Doe"}]
        assert body["processing_error"] is None

    async def test_analysis_attachment_not_in_parent_returns_404(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        parent_id, _ = await _seed_doc_with_attachments(db, case_id)
        r = await client.get(f"/api/v1/documents/{parent_id}/attachments/ghost/analysis")
        assert r.status_code == 404

    async def test_analysis_returns_defaults_for_unprocessed(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Attachment with no analysis fields populated returns sensible
        defaults (processed=False, summary=None, ai_suggestions=[],
        processing_error=None)."""
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        from tests.factories import make_document as _md

        att = _md(filename="raw.pdf")
        await db.documents.insert_one(att)
        parent = _md(case_id=case_id, has_attachments=True, attachment_ids=[att["id"]])
        await db.documents.insert_one(parent)
        r = await client.get(f"/api/v1/documents/{parent['id']}/attachments/{att['id']}/analysis")
        assert r.status_code == 200
        body = r.json()
        assert body["processed"] is False
        assert body["summary"] is None
        assert body["ai_suggestions"] == []
        assert body["processing_error"] is None

    async def test_analysis_guest_forbidden_by_role(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="guest")
        case_id = await _seed_case(db)
        parent_id, att_ids = await _seed_doc_with_attachments(
            db, case_id, attachments=[{"filename": "x.pdf"}]
        )
        r = await client.get(f"/api/v1/documents/{parent_id}/attachments/{att_ids[0]}/analysis")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Direct unit tests for module helpers
# ---------------------------------------------------------------------------


async def test_get_db_helper_returns_shared_database(mongo_uri: str) -> None:
    """The module-level `get_db` is normally overridden via
    app.dependency_overrides in route tests; cover it directly."""
    from unittest.mock import MagicMock

    from src.documents.attachment_routes import get_db

    fake_request = MagicMock()
    result = await get_db(fake_request)
    assert result.name == "blackbar"


def test_check_document_access_owner_and_admin_always_allowed() -> None:
    from src.documents.attachment_routes import check_document_access

    assert check_document_access({}, {"id": "u", "role": "owner"}) is True
    assert check_document_access({}, {"id": "u", "role": "admin"}) is True


def test_check_document_access_others_no_case_denies() -> None:
    """Non-owner/admin/guest user with no case context -> falls through
    to `return False`."""
    from src.documents.attachment_routes import check_document_access

    assert check_document_access({}, {"id": "u", "role": "analyst"}, case=None) is False


def test_check_document_access_guest_share_match() -> None:
    from src.documents.attachment_routes import check_document_access

    doc = {"shared_with": [{"user_id": "u1"}, {"user_id": "u2"}]}
    assert check_document_access(doc, {"id": "u1", "role": "guest"}) is True
    assert check_document_access(doc, {"id": "u3", "role": "guest"}) is False
