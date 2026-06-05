"""Integration tests for `src.documents.document_status_routes`.

Phase 2.3.C (2/5). Target >=80% line coverage on
`src.documents.document_status_routes` — single + bulk document status
mutation with case audit log writes.

Endpoints under test (mounted at `/api/v1/documents/...` via
`document_status_router` included from `documents/routes.py`):

    PUT    /{document_id}/status
    PUT    /bulk/status

**Auth:** both endpoints gate on `check_role(["owner","admin","analyst"])`.
Plain `user` and `guest` are rejected at the decorator. No case-team
check downstream.

**State machine:** status values come from `DocumentStatus` enum
(`new`, `under_review`, `redaction_required`, `redaction_in_progress`,
`ready_for_approval`, `approved`, `released`, `withheld` — see
`src/documents/models.py`). The endpoints accept any value the enum
permits; there is no state-transition validation (any -> any allowed).

Source-API findings pinned (audit Section 11 candidates):
- **Route registration order bug (same class as B12):** the bulk
  endpoint `PUT /bulk/status` is registered AFTER `PUT /{document_id}/status`
  within `document_status_routes.py`. FastAPI matches in registration
  order; `PUT /bulk/status` therefore matches the single-doc handler
  with `document_id="bulk"`, which returns 404 "Document not found".
  The bulk handler is functionally unreachable through the public
  URL. Pinned in test_bulk_endpoint_unreachable_routes_to_single_doc.
- The bulk endpoint silently swallows per-doc exceptions and skips
  missing docs (no error returned to the caller). `updated_count` may
  be < `total_requested` with no breakdown of which docs failed.
- Audit log entries for the bulk path carry `bulk_update: True` flag;
  single-doc entries don't.
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
    """Rebind document_status routes' get_db + dependencies users to the
    per-test motor db."""
    import src.database as db_mod
    import src.dependencies as deps_mod
    from src.documents import document_status_routes
    from src.documents import routes as documents_routes

    async def _override_get_db():
        return db

    app.dependency_overrides[document_status_routes.get_db] = _override_get_db
    app.dependency_overrides[documents_routes.get_db] = _override_get_db
    monkeypatch.setattr(deps_mod, "users", db.users)
    monkeypatch.setattr(db_mod, "users", db.users)

    yield db

    app.dependency_overrides.pop(document_status_routes.get_db, None)
    app.dependency_overrides.pop(documents_routes.get_db, None)


async def _seed_case(db: AsyncIOMotorDatabase, **overrides: Any) -> str:
    case = make_case(**overrides)
    await db.cases.insert_one(case)
    return case["id"]


async def _seed_document(db: AsyncIOMotorDatabase, **overrides: Any) -> str:
    doc = make_document(**overrides)
    await db.documents.insert_one(doc)
    return doc["id"]


# ---------------------------------------------------------------------------
# PUT /{document_id}/status
# ---------------------------------------------------------------------------


class TestUpdateDocumentStatus:
    async def test_admin_updates_status_and_writes_audit(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        doc_id = await _seed_document(db, case_id=case_id, status="new")
        r = await client.put(
            f"/api/v1/documents/{doc_id}/status",
            json={"status": "under_review", "notes": "starting review"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["old_status"] == "new"
        assert body["new_status"] == "under_review"
        assert body["document_id"] == doc_id

        # Verify persistence
        doc = await db.documents.find_one({"id": doc_id})
        assert doc["status"] == "under_review"
        assert "status_updated_at" in doc
        assert "status_updated_by" in doc

        # Verify audit log entry on the case
        case = await db.cases.find_one({"id": case_id})
        entries = [
            e for e in case.get("audit_log", []) if e.get("action") == "document_status_changed"
        ]
        assert len(entries) == 1
        details = entries[0]["details"]
        assert details["old_status"] == "new"
        assert details["new_status"] == "under_review"
        assert details["notes"] == "starting review"
        assert details["document_id"] == doc_id

    async def test_update_status_doc_not_found(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.put(
            "/api/v1/documents/ghost/status",
            json={"status": "approved"},
        )
        assert r.status_code == 404
        assert "Document not found" in r.text

    @pytest.mark.parametrize("role", ["user", "guest"])
    async def test_update_status_role_decorator_forbids(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        role: str,
    ) -> None:
        """check_role(['owner','admin','analyst']) rejects user and guest."""
        client = await authed_client_factory(role=role, email=f"forbid-{role}@example.com")
        case_id = await _seed_case(db)
        doc_id = await _seed_document(db, case_id=case_id)
        r = await client.put(
            f"/api/v1/documents/{doc_id}/status",
            json={"status": "approved"},
        )
        assert r.status_code == 403

    @pytest.mark.parametrize(
        "from_status,to_status",
        [
            ("new", "under_review"),
            ("under_review", "redaction_required"),
            ("redaction_required", "redaction_in_progress"),
            ("redaction_in_progress", "ready_for_approval"),
            ("ready_for_approval", "approved"),
            ("approved", "released"),
            ("released", "withheld"),
            ("withheld", "new"),  # backward transition allowed
        ],
    )
    async def test_state_transitions_unrestricted(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        from_status: str,
        to_status: str,
    ) -> None:
        """Pin reality: there is NO state-machine guard. Any -> any allowed."""
        client = await authed_client_factory(
            role="admin", email=f"sm-{from_status}-{to_status}@example.com"
        )
        case_id = await _seed_case(db)
        doc_id = await _seed_document(db, case_id=case_id, status=from_status)
        r = await client.put(
            f"/api/v1/documents/{doc_id}/status",
            json={"status": to_status},
        )
        assert r.status_code == 200, r.text
        assert r.json()["new_status"] == to_status

    async def test_update_status_invalid_enum_value(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Pydantic enum validation rejects an unknown status.

        Phase 4 Batch 4.4 (audit B7) fixed the deprecated
        `HTTP_422_UNPROCESSABLE_ENTITY` constant in
        `src/utils/error_handler.py`; the per-test filterwarnings
        suppressor is no longer required."""
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        doc_id = await _seed_document(db, case_id=case_id)
        r = await client.put(
            f"/api/v1/documents/{doc_id}/status",
            json={"status": "bogus"},
        )
        assert r.status_code == 422

    async def test_update_status_no_case_skips_audit(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """When doc.case_id is falsy, the audit-log block is skipped (pins
        the `if doc.get("case_id")` False branch)."""
        client = await authed_client_factory(role="admin")
        doc = make_document(status="new")
        doc["case_id"] = None
        await db.documents.insert_one(doc)
        r = await client.put(
            f"/api/v1/documents/{doc['id']}/status",
            json={"status": "approved"},
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# PUT /bulk/status
# ---------------------------------------------------------------------------
#
# NOTE: the public URL `PUT /api/v1/documents/bulk/status` is unreachable
# due to route-order: `PUT /{document_id}/status` registers first and
# matches `document_id="bulk"`, returning 404. Pinned below. The handler's
# logic is exercised by calling the function directly with a stub
# Request.


class TestBulkUpdateDocumentStatus:
    async def test_bulk_endpoint_resolves_to_bulk_handler(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Phase 4 Batch 4.4 (audit B33): `PUT /bulk/status` is now
        registered before `/{document_id}/status`, so FastAPI's
        first-match rule resolves the bulk URL to the bulk handler
        instead of treating "bulk" as a document_id and 404'ing.

        Test flipped from `test_bulk_endpoint_unreachable_routes_to_single_doc`
        which pinned the prior dead-code state."""
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        doc_id = await _seed_document(db, case_id=case_id, status="new")
        r = await client.put(
            "/api/v1/documents/bulk/status",
            json={"document_ids": [doc_id], "status": "approved"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["updated_count"] == 1
        assert body["total_requested"] == 1

    async def _call_bulk_handler(
        self,
        db: AsyncIOMotorDatabase,
        *,
        document_ids: list[str],
        status: str,
        notes: str | None = None,
        user_id: str = "test-admin",
    ) -> dict:
        """Drive the unreachable handler directly via the function object."""
        from unittest.mock import MagicMock

        from src.documents.document_status_routes import (
            bulk_update_document_status,
        )
        from src.documents.models import DocumentStatus

        fake_request = MagicMock()
        current_user = {"id": user_id, "username": "admin-user"}
        return await bulk_update_document_status(
            request=fake_request,
            document_ids=document_ids,
            status=DocumentStatus(status),
            db=db,
            notes=notes,
            current_user=current_user,
        )

    async def test_bulk_handler_updates_multiple_docs_and_audits(
        self,
        db: AsyncIOMotorDatabase,
        patch_routes_db,
    ) -> None:
        """Direct-handler call exercises the body. Pins success
        envelope, count, and per-doc audit-log entries tagged
        bulk_update=True."""
        case_id = await _seed_case(db)
        ids = [await _seed_document(db, case_id=case_id, status="new") for _ in range(3)]
        result = await self._call_bulk_handler(
            db,
            document_ids=ids,
            status="under_review",
            notes="batch",
        )
        assert result["success"] is True
        assert result["updated_count"] == 3
        assert result["total_requested"] == 3
        for doc_id in ids:
            d = await db.documents.find_one({"id": doc_id})
            assert d["status"] == "under_review"
        case = await db.cases.find_one({"id": case_id})
        bulk_entries = [
            e
            for e in case.get("audit_log", [])
            if e.get("action") == "document_status_changed"
            and e.get("details", {}).get("bulk_update") is True
        ]
        assert len(bulk_entries) == 3

    async def test_bulk_handler_skips_missing_docs_silently(
        self,
        db: AsyncIOMotorDatabase,
        patch_routes_db,
    ) -> None:
        """Missing doc ids are silently dropped (`if not doc: continue`)
        without per-id error surfacing."""
        case_id = await _seed_case(db)
        real_id = await _seed_document(db, case_id=case_id, status="new")
        result = await self._call_bulk_handler(
            db,
            document_ids=[real_id, "ghost-1", "ghost-2"],
            status="approved",
        )
        assert result["updated_count"] == 1
        assert result["total_requested"] == 3

    async def test_bulk_handler_empty_list_returns_zero(
        self,
        db: AsyncIOMotorDatabase,
        patch_routes_db,
    ) -> None:
        result = await self._call_bulk_handler(db, document_ids=[], status="approved")
        assert result["updated_count"] == 0
        assert result["total_requested"] == 0

    @pytest.mark.parametrize("role", ["user", "guest"])
    async def test_bulk_url_role_decorator_forbids(
        self,
        authed_client_factory,
        patch_routes_db,
        role: str,
    ) -> None:
        """Even though the URL hits the single-doc handler due to
        route-order, both handlers share the same role allowlist so
        the 403 is still asserted for non-allowed roles."""
        client = await authed_client_factory(role=role, email=f"bulk-forbid-{role}@example.com")
        r = await client.put(
            "/api/v1/documents/bulk/status",
            json={"document_ids": [], "status": "approved"},
        )
        assert r.status_code == 403

    async def test_bulk_handler_doc_with_no_case_skips_audit(
        self,
        db: AsyncIOMotorDatabase,
        patch_routes_db,
    ) -> None:
        """No case_id on the doc -> the per-iteration audit-write block
        is skipped (`if doc.get("case_id")` False)."""
        doc = make_document(status="new")
        doc["case_id"] = None
        await db.documents.insert_one(doc)
        result = await self._call_bulk_handler(db, document_ids=[doc["id"]], status="approved")
        assert result["updated_count"] == 1
        updated = await db.documents.find_one({"id": doc["id"]})
        assert updated["status"] == "approved"

    async def test_bulk_handler_per_doc_exception_swallowed(
        self,
        db: AsyncIOMotorDatabase,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Exception inside the loop is caught and the iteration continues
        (pins the `except Exception as e: logger.error(...); continue`
        branch). We patch `db.documents.find_one` to raise for one id."""
        case_id = await _seed_case(db)
        good_id = await _seed_document(db, case_id=case_id, status="new")
        boom_id = "make-it-explode"

        # Wrap db.documents.find_one to raise for one specific id
        real_find_one = db.documents.find_one
        call_count = {"n": 0}

        async def _exploding_find_one(query, *a, **kw):
            call_count["n"] += 1
            if query.get("id") == boom_id:
                raise RuntimeError("simulated db blip")
            return await real_find_one(query, *a, **kw)

        monkeypatch.setattr(db.documents, "find_one", _exploding_find_one)
        result = await self._call_bulk_handler(
            db, document_ids=[good_id, boom_id], status="approved"
        )
        # Good one updated, bad one skipped silently
        assert result["updated_count"] == 1
        assert result["total_requested"] == 2


# ---------------------------------------------------------------------------
# Direct unit tests for module helpers
# ---------------------------------------------------------------------------


async def test_get_db_helper_returns_shared_database(mongo_uri: str) -> None:
    from unittest.mock import MagicMock

    from src.documents.document_status_routes import get_db

    fake_request = MagicMock()
    result = await get_db(fake_request)
    assert result.name == "blackbar"
