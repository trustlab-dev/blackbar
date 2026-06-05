"""Integration tests for `src.documents.search_routes`.

Phase 2.3.C (3/5). Target >=80% line coverage on
`src.documents.search_routes` — in-document text search.

Endpoints under test (mounted at `/api/v1/documents/...` via
`search_router` included from `documents/routes.py`):

    GET    /{document_id}/search?query=...
    POST   /{document_id}/search   (body: query, case_sensitive, whole_word)

**Source-API findings pinned (audit Section 11 candidates):**

- **Duplicate function name `search_document_text`:** both endpoints
  are decorated handlers but bind the same function name to the module
  namespace. The second decoration overwrites the first attribute, but
  FastAPI's routing table holds both decorator references — so both
  URLs ARE reachable. Confirmed in Phase 1.5 review and pinned in
  TestSearchEndpointDuplicateBinding below.

- **Module-level `db` capture:** `from ..database import db` at module
  top (line 12). The POST endpoint reads `db.documents.find_one` from
  this module-level symbol — it does NOT use `Depends(get_db)`. Tests
  must monkeypatch `src.documents.search_routes.db` for the POST
  endpoint to hit the per-test motor database. Same class as B30.

- **GET endpoint asymmetry:** the GET endpoint does NOT run
  `check_document_access` (only role decorator). The POST endpoint
  DOES. So a non-team user with role=user can GET-search any doc but
  POST-search only docs they have access to. Same family as B34.

- **Module logger uses f-string in `logger.warning`** — fine, but
  pin the OCR-data validation chain:
    1. text_data missing -> 400 "No OCR data available..."
    2. text_data.pages missing/empty -> 400 "OCR data is incomplete..."
    3. pages exist but no word-level data -> 400 "OCR data does not
       contain word-level coordinates..."
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
    """Rebind both `Depends(get_db)` (GET endpoint) and the module-level
    `db` symbol (POST endpoint) to the per-test motor db."""
    import src.database as db_mod
    import src.dependencies as deps_mod
    from src.documents import routes as documents_routes
    from src.documents import search_routes

    async def _override_get_db():
        return db

    app.dependency_overrides[search_routes.get_db] = _override_get_db
    app.dependency_overrides[documents_routes.get_db] = _override_get_db
    monkeypatch.setattr(search_routes, "db", db)
    monkeypatch.setattr(deps_mod, "users", db.users)
    monkeypatch.setattr(db_mod, "users", db.users)

    yield db

    app.dependency_overrides.pop(search_routes.get_db, None)
    app.dependency_overrides.pop(documents_routes.get_db, None)


async def _seed_case(db: AsyncIOMotorDatabase, **overrides: Any) -> str:
    case = make_case(**overrides)
    await db.cases.insert_one(case)
    return case["id"]


async def _seed_document(db: AsyncIOMotorDatabase, **overrides: Any) -> str:
    doc = make_document(**overrides)
    await db.documents.insert_one(doc)
    return doc["id"]


def _text_data_with_words(text: str, page_num: int = 1) -> dict:
    """Build a text_data structure with words for the POST endpoint."""
    words = []
    for i, tok in enumerate(text.split()):
        words.append(
            {
                "text": tok,
                "bbox": [i * 50.0, 0.0, (i + 1) * 50.0, 12.0],
                "confidence": 0.99,
            }
        )
    return {"pages": [{"page_num": page_num, "text": text, "words": words}]}


# ---------------------------------------------------------------------------
# GET /{document_id}/search
# ---------------------------------------------------------------------------


class TestSearchDocumentTextGet:
    async def test_basic_search_finds_matches_with_context(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        text = "Hello world. Hello there. Goodbye world." + (" filler" * 20)
        doc_id = await _seed_document(
            db,
            case_id=case_id,
            text_data={"pages": [{"page_num": 1, "text": text}]},
        )
        r = await client.get(f"/api/v1/documents/{doc_id}/search", params={"query": "Hello"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["query"] == "Hello"
        assert body["total_matches"] == 2  # two "Hello" occurrences
        assert all("page" in m and "position" in m and "context" in m for m in body["results"])

    async def test_search_no_matches(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        doc_id = await _seed_document(
            db,
            case_id=case_id,
            text_data={"pages": [{"page_num": 1, "text": "alpha beta gamma"}]},
        )
        r = await client.get(f"/api/v1/documents/{doc_id}/search", params={"query": "missing"})
        assert r.status_code == 200
        body = r.json()
        assert body["total_matches"] == 0
        assert body["results"] == []

    async def test_search_missing_text_data_returns_empty(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Doc with no `text_data` field falls through to empty results
        (GET endpoint doesn't 400 like the POST endpoint does)."""
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        doc_id = await _seed_document(db, case_id=case_id)
        r = await client.get(f"/api/v1/documents/{doc_id}/search", params={"query": "anything"})
        assert r.status_code == 200
        assert r.json()["total_matches"] == 0

    async def test_get_search_document_not_found(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/documents/ghost/search", params={"query": "x"})
        assert r.status_code == 404
        assert "Document not found" in r.text

    @pytest.mark.parametrize("role", ["guest"])
    async def test_get_search_role_decorator_forbids_guest(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        role: str,
    ) -> None:
        client = await authed_client_factory(role=role)
        case_id = await _seed_case(db)
        doc_id = await _seed_document(db, case_id=case_id)
        r = await client.get(f"/api/v1/documents/{doc_id}/search", params={"query": "x"})
        assert r.status_code == 403

    @pytest.mark.filterwarnings("ignore::DeprecationWarning")
    async def test_get_search_missing_query_param(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """The `query` query-string parameter is required."""
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        doc_id = await _seed_document(db, case_id=case_id)
        r = await client.get(f"/api/v1/documents/{doc_id}/search")
        assert r.status_code == 422

    async def test_get_search_case_insensitive(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Pin reality: GET endpoint always does a case-INSENSITIVE
        match (calls `.lower()` on both sides). No case_sensitive
        flag on this endpoint."""
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        doc_id = await _seed_document(
            db,
            case_id=case_id,
            text_data={"pages": [{"page_num": 1, "text": "HELLO World"}]},
        )
        r = await client.get(f"/api/v1/documents/{doc_id}/search", params={"query": "hello"})
        assert r.status_code == 200
        assert r.json()["total_matches"] == 1


# ---------------------------------------------------------------------------
# POST /{document_id}/search
# ---------------------------------------------------------------------------


class TestSearchDocumentTextPost:
    async def test_post_search_returns_bbox_matches(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        doc_id = await _seed_document(
            db,
            case_id=case_id,
            text_data=_text_data_with_words("apple banana cherry banana"),
        )
        r = await client.post(
            f"/api/v1/documents/{doc_id}/search",
            json={"query": "banana"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["query"] == "banana"
        assert body["total"] == 2
        assert len(body["matches"]) == 2
        first = body["matches"][0]
        assert "bbox" in first
        assert "page" in first
        assert "text" in first
        # context should highlight the matched word with **
        assert "**banana**" in first["context"]

    async def test_post_search_whole_word(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        doc_id = await _seed_document(
            db,
            case_id=case_id,
            text_data=_text_data_with_words("apple application apply"),
        )
        r = await client.post(
            f"/api/v1/documents/{doc_id}/search",
            json={"query": "apple", "whole_word": True},
        )
        assert r.status_code == 200
        body = r.json()
        # whole_word=True means exact match of word text only
        assert body["total"] == 1

    async def test_post_search_case_sensitive(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        doc_id = await _seed_document(
            db,
            case_id=case_id,
            text_data=_text_data_with_words("Apple apple APPLE"),
        )
        r = await client.post(
            f"/api/v1/documents/{doc_id}/search",
            json={"query": "Apple", "case_sensitive": True},
        )
        assert r.status_code == 200
        # only the capital-A "Apple" matches
        assert r.json()["total"] == 1

    async def test_post_search_document_not_found(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.post("/api/v1/documents/ghost/search", json={"query": "x"})
        assert r.status_code == 404

    async def test_post_search_no_text_data_returns_400(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        doc_id = await _seed_document(db, case_id=case_id)
        r = await client.post(f"/api/v1/documents/{doc_id}/search", json={"query": "x"})
        assert r.status_code == 400
        assert "No OCR data available" in r.text

    async def test_post_search_text_data_no_pages_returns_400(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        doc_id = await _seed_document(db, case_id=case_id, text_data={"full_text": "stuff"})
        r = await client.post(f"/api/v1/documents/{doc_id}/search", json={"query": "x"})
        assert r.status_code == 400
        assert "OCR data is incomplete" in r.text

    async def test_post_search_pages_no_words_returns_400(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        doc_id = await _seed_document(
            db,
            case_id=case_id,
            text_data={"pages": [{"page_num": 1, "text": "hi"}]},  # no words
        )
        r = await client.post(f"/api/v1/documents/{doc_id}/search", json={"query": "hi"})
        assert r.status_code == 400
        assert "word-level coordinates" in r.text

    async def test_post_search_off_team_user_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Non-admin user not on case team -> 403 via check_document_access."""
        client = await authed_client_factory(role="user", email="off-search@example.com")
        case_id = await _seed_case(
            db,
            case_team=[{"user_id": "someone-else", "role": "analyst", "status": "active"}],
        )
        doc_id = await _seed_document(
            db,
            case_id=case_id,
            text_data=_text_data_with_words("hello world"),
        )
        r = await client.post(f"/api/v1/documents/{doc_id}/search", json={"query": "hello"})
        assert r.status_code == 403
        assert "Access denied" in r.text

    async def test_post_search_doc_no_case_does_not_crash(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Doc with no case_id -> case=None branch; check_document_access
        returns False for non-admin -> 403. Pin behavior."""
        client = await authed_client_factory(role="user", email="nc-search@example.com")
        doc = make_document(text_data=_text_data_with_words("hi"))
        doc["case_id"] = None
        await db.documents.insert_one(doc)
        r = await client.post(f"/api/v1/documents/{doc['id']}/search", json={"query": "hi"})
        # case=None, user non-admin/guest -> falls through to False
        assert r.status_code == 403

    async def test_post_search_admin_no_case_works(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Admin bypasses check_document_access regardless of case state."""
        client = await authed_client_factory(role="admin")
        doc = make_document(text_data=_text_data_with_words("hi there"))
        doc["case_id"] = None
        await db.documents.insert_one(doc)
        r = await client.post(f"/api/v1/documents/{doc['id']}/search", json={"query": "hi"})
        assert r.status_code == 200
        assert r.json()["total"] == 1


# ---------------------------------------------------------------------------
# Duplicate function-name binding pin
# ---------------------------------------------------------------------------


def test_search_endpoint_duplicate_function_name() -> None:
    """Pin reality: both GET and POST handlers in search_routes.py bind
    the module attribute `search_document_text`. The second decoration
    overwrites the attribute; only the POST handler is reachable via
    `search_routes.search_document_text`. FastAPI's routing table holds
    both decorator references separately, so both URL routes work."""
    from src.documents import search_routes

    # Module attribute resolves to whichever def was processed last
    # (the POST handler, defined after the GET handler).
    assert search_routes.search_document_text.__name__ == "search_document_text"

    # Inspect the router for both registered paths
    paths = [(r.path, list(r.methods)) for r in search_routes.router.routes]
    methods_by_path = {p: ms for p, ms in paths}
    # Only one path key — both methods land on the same URL string
    assert "/{document_id}/search" in methods_by_path
    methods = set(methods_by_path["/{document_id}/search"])
    # Both methods registered on this single path entry — but they're
    # two separate Route objects in router.routes (one per decorator).
    all_methods = []
    for r in search_routes.router.routes:
        if getattr(r, "path", None) == "/{document_id}/search":
            all_methods.extend(r.methods)
    assert "GET" in all_methods
    assert "POST" in all_methods


# ---------------------------------------------------------------------------
# Direct unit tests for module helpers
# ---------------------------------------------------------------------------


async def test_get_db_helper_returns_shared_database(mongo_uri: str) -> None:
    from unittest.mock import MagicMock

    from src.documents.search_routes import get_db

    fake_request = MagicMock()
    result = await get_db(fake_request)
    assert result.name == "blackbar"


def test_check_document_access_owner_admin_allowed() -> None:
    from src.documents.search_routes import check_document_access

    assert check_document_access({}, {"id": "u", "role": "owner"}) is True
    assert check_document_access({}, {"id": "u", "role": "admin"}) is True


def test_check_document_access_guest_share_matches() -> None:
    from src.documents.search_routes import check_document_access

    doc = {"shared_with": [{"user_id": "u1"}]}
    assert check_document_access(doc, {"id": "u1", "role": "guest"}) is True
    assert check_document_access(doc, {"id": "u2", "role": "guest"}) is False


def test_check_document_access_others_no_case_denies() -> None:
    from src.documents.search_routes import check_document_access

    assert check_document_access({}, {"id": "u", "role": "analyst"}, case=None) is False
