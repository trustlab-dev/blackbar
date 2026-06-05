"""Integration tests for `src.cases.queue_routes` endpoints.

Phase 2.2.C (1/5). Target >=80% line coverage on src.cases.queue_routes.

Endpoints under test (all mounted at /api/v1/cases/...):
    GET    /{case_id}/deadline-info
    POST   /{case_id}/request-extension
    GET    /{case_id}/search-documents
    GET    /queue/my-cases
    GET    /queue/all
    GET    /stats/dashboard
    GET    /deadline-dashboard
    GET    /search
    GET    /search/advanced

Test infrastructure notes:
- `authed_client_factory` returns `httpx.AsyncClient` with a valid JWT.
- The routes inject `db` via `Depends(get_db)` where `get_db` calls
  `get_database_from_request()` which returns the hard-coded
  `client["blackbar"]` global. Per-test isolation requires overriding
  `get_db` on the FastAPI app with the test `db` fixture. We also
  monkeypatch `src.dependencies.users` so that `get_current_user`'s
  DB lookup (against `users.find_one`) hits the per-test db rather
  than the global one. Same idea for the lazy `from ..database import users`
  imports inside `queue_routes.get_my_cases` / `get_all_cases_queue` —
  we patch `src.database.users` too so the late-bound import sees the
  test db.

Reality pins surfaced while writing these tests:
- `GET /search` calls `search_documents(q, limit=limit)` and
  `search_cases(q, limit=limit)` and reads `.get("results", [])` from
  the result. But `search_documents`/`search_cases` from
  `src.utils.search_engine` return `{"query": ..., "limit": ..., "sort": ...}`
  with no `"results"` or `"total"` keys. The endpoint always returns
  empty lists with `0` totals regardless of DB state. Pinned as
  source-API surprise for audit Section 11.
- `GET /search/advanced` uses the SAME `search_documents` helper but
  calls it correctly: it accesses `doc_query["query"]` and runs a
  real mongo find. The endpoint works.
- `/deadline-dashboard` requires `created_at` to be a real datetime
  on every case row (else it substitutes `datetime.utcnow()` and
  proceeds). Cases without `sla_type` default to STANDARD.
- `request-extension` auto-approves and pushes the extension into
  `case.extensions` along with two `cases.update_one` writes that
  modify `deadline_info` then push an audit_log entry.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import pytest
from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorDatabase

from tests.factories import make_case

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_routes_db(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase, app):
    """Rebind cases-related DB injection to the per-test motor database.

    Several patch points are required:
    1. `app.dependency_overrides` for both `queue_routes.get_db` AND
       `cases.routes.get_db`. Each module defines its OWN `get_db`
       helper; they're distinct callables. The 1-segment URLs in
       `queue_routes` (`/search`, `/deadline-dashboard`) are shadowed
       by `cases.routes.get_case` (which uses `cases.routes.get_db`),
       so we need both overridden to avoid hitting the closed
       global motor client through the shadow path.
    2. `src.dependencies.users` — `get_current_user` looks up the
       user via `users.find_one({"id": ...})`; this `users` symbol
       was bound at module import time to `blackbar.users`.
    3. `src.database.users` — `get_my_cases` / `get_all_cases_queue`
       re-import `users` lazily inside the handler with
       `from ..database import users`; the bind-time value lives on
       `src.database`.
    """
    import src.database as db_mod
    import src.dependencies as deps_mod
    from src.cases import queue_routes
    from src.cases import routes as cases_routes

    async def _override_get_db():
        return db

    app.dependency_overrides[queue_routes.get_db] = _override_get_db
    app.dependency_overrides[cases_routes.get_db] = _override_get_db
    monkeypatch.setattr(deps_mod, "users", db.users)
    monkeypatch.setattr(db_mod, "users", db.users)

    yield db

    app.dependency_overrides.pop(queue_routes.get_db, None)
    app.dependency_overrides.pop(cases_routes.get_db, None)


async def _seed_case(db: AsyncIOMotorDatabase, **overrides: Any) -> str:
    """Seed a case row and return its id."""
    doc = make_case(**overrides)
    await db.cases.insert_one(doc)
    return doc["id"]


# ---------------------------------------------------------------------------
# GET /stats/dashboard
# ---------------------------------------------------------------------------


class TestStatsDashboard:
    async def test_admin_sees_stats_with_status_breakdown(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_case(db, status="new", priority="high")
        await _seed_case(db, status="completed", priority="medium")

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/cases/stats/dashboard")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total_cases"] == 2
        assert body["status_counts"]["new"] == 1
        assert body["status_counts"]["completed"] == 1
        assert body["priority_counts"]["high"] == 1
        assert body["priority_counts"]["medium"] == 1
        assert "overdue_count" in body
        assert "unassigned_count" in body

    async def test_analyst_forbidden_from_stats_dashboard(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Stats dashboard is gated to admin/owner only."""
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get("/api/v1/cases/stats/dashboard")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# GET /queue/my-cases
# ---------------------------------------------------------------------------


class TestMyCases:
    async def test_user_sees_only_their_assigned_cases(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="analyst", email="me@example.com")
        me = await db.users.find_one({"email": "me@example.com"})
        my_id = me["id"]

        await _seed_case(db, assignee=my_id, title="Mine")
        await _seed_case(db, assignee="someone-else", title="Theirs")

        r = await client.get("/api/v1/cases/queue/my-cases")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 1
        assert body["cases"][0]["title"] == "Mine"

    async def test_my_cases_filter_by_status(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="user", email="filt@example.com")
        me = await db.users.find_one({"email": "filt@example.com"})
        my_id = me["id"]

        await _seed_case(db, assignee=my_id, status="new")
        await _seed_case(db, assignee=my_id, status="closed")

        r = await client.get("/api/v1/cases/queue/my-cases?status=new")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["cases"][0]["status"] == "new"

    async def test_my_cases_unauthenticated_returns_401(self, client) -> None:
        """No bearer token => AuthMiddleware rejects."""
        r = client.get("/api/v1/cases/queue/my-cases")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /queue/all
# ---------------------------------------------------------------------------


class TestQueueAll:
    async def test_admin_sees_all_cases(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_case(db, title="A", status="new")
        await _seed_case(db, title="B", status="closed")

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/cases/queue/all")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 2
        assert len(body["cases"]) == 2

    async def test_queue_all_search_filter_by_title(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Pin the search filter: matches against title/description/
        tracking_number via case-insensitive regex."""
        await _seed_case(db, title="Important matter")
        await _seed_case(db, title="Routine thing")

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/cases/queue/all?search=important")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert "Important" in body["cases"][0]["title"]

    async def test_queue_all_tags_filter(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_case(db, tags=["foo", "bar"])
        await _seed_case(db, tags=["baz"])

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/cases/queue/all?tags=foo,xyz")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1

    async def test_queue_all_user_role_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Plain users can't see all cases."""
        client: AsyncClient = await authed_client_factory(role="user")
        r = await client.get("/api/v1/cases/queue/all")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# GET /deadline-dashboard
# ---------------------------------------------------------------------------


class TestDeadlineDashboard:
    """`GET /api/v1/cases/deadline-dashboard` reachability (B12 fix, 2026-05-12).

    Before the B12 fix, this URL was SHADOWED by `GET /{case_id}` (the
    `/{case_id}` decorator in `cases/routes.py` registered before
    `include_router(queue_router)`). FastAPI matched single-segment
    URLs against the catch-all first, returning 404. The fix moves
    `include_router` calls above any `@router.<verb>(...)` decorator,
    so sub-router routes register first and `/deadline-dashboard` is
    reachable as designed.
    """

    async def test_deadline_dashboard_is_reachable_for_analyst(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_case(db, status="new")
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get("/api/v1/cases/deadline-dashboard")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "summary" in body
        assert "attention_required" in body
        assert "all_cases" in body

    async def test_deadline_dashboard_guest_role_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """The `/deadline-dashboard` handler gates on
        owner/admin/analyst — guest must be 403 (not the old
        `/{case_id}`-shadow 403)."""
        client: AsyncClient = await authed_client_factory(role="guest")
        r = await client.get("/api/v1/cases/deadline-dashboard")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# GET /search
# ---------------------------------------------------------------------------


class TestSearch:
    """`GET /api/v1/cases/search` reachability (B12 fix, 2026-05-12).

    Before the B12 fix this URL was shadowed by `GET /{case_id}` (same
    cause as `/deadline-dashboard`). Now reachable.

    The handler still has a separate B13 helper-shape bug: it calls
    `search_documents(q, limit=limit)` and reads `.get("results", [])`
    / `.get("total", 0)` from the result, but
    `src.utils.search_engine.search_documents` returns
    `{"query": ..., "limit": ..., "sort": ...}` with no `"results"`/
    `"total"` keys. So the response is well-formed but empty. B13 is
    out of scope for this sprint; tracked in audit Section 11.
    """

    async def test_search_is_reachable_for_analyst(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_case(db, title="Findable matter")
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get("/api/v1/cases/search?q=Findable")
        assert r.status_code == 200, r.text
        body = r.json()
        # B13: helper-shape bug — empty results regardless of DB state.
        assert body["documents"] == []
        assert body["cases"] == []
        assert body["documents_total"] == 0
        assert body["cases_total"] == 0

    async def test_search_requires_authenticated_user(self, client) -> None:
        r = client.get("/api/v1/cases/search?q=foo")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /search/advanced
# ---------------------------------------------------------------------------


class TestAdvancedSearch:
    async def test_advanced_search_short_query_returns_400(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get("/api/v1/cases/search/advanced?q=a")
        assert r.status_code == 400

    async def test_advanced_search_happy_path_returns_results_shape(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_case(db, title="ContractReviewItem", description="lorem")

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/cases/search/advanced?q=ContractReviewItem")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "documents" in body
        assert "cases" in body
        assert "filters" in body
        # The query string is echoed back
        assert body["query"] == "ContractReviewItem"

    async def test_advanced_search_user_role_forbidden(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="user")
        r = await client.get("/api/v1/cases/search/advanced?q=foo")
        assert r.status_code == 403

    async def test_advanced_search_with_all_filters(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Pin the filter-building branches in advanced search:
        document_status, case_status, submitter regex, date_from/date_to.
        Exercises lines 515-535."""
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get(
            "/api/v1/cases/search/advanced"
            "?q=foobar"
            "&document_status=draft"
            "&case_status=new"
            "&submitter=alice@example.com"
            "&date_from=2024-01-01"
            "&date_to=2025-12-31"
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["filters"]["document_status"] == "draft"
        assert body["filters"]["case_status"] == "new"
        assert body["filters"]["submitter"] == "alice@example.com"
        assert body["filters"]["date_from"] == "2024-01-01"
        assert body["filters"]["date_to"] == "2025-12-31"


# ---------------------------------------------------------------------------
# GET /{case_id}/deadline-info
# ---------------------------------------------------------------------------


class TestCaseDeadlineInfo:
    async def test_deadline_info_happy_path(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get(f"/api/v1/cases/{case_id}/deadline-info")
        assert r.status_code == 200, r.text
        body = r.json()
        # deadline_info dict shape from deadline_tracker
        assert "deadline" in body or "status" in body

    async def test_deadline_info_missing_case_returns_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get("/api/v1/cases/ghost-case/deadline-info")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /{case_id}/request-extension
# ---------------------------------------------------------------------------


class TestRequestExtension:
    async def test_admin_can_request_extension(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            f"/api/v1/cases/{case_id}/request-extension",
            json={"extension_days": 30, "reason": "Complex case"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert "extension" in body
        assert "new_deadline_info" in body

        # Verify the extension was persisted
        case = await db.cases.find_one({"id": case_id})
        assert len(case.get("extensions", [])) == 1
        # Audit log gained an entry
        assert any(e.get("action") == "extension_requested" for e in case.get("audit_log", []))

    async def test_request_extension_missing_case_returns_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/cases/ghost/request-extension",
            json={"extension_days": 14, "reason": "x"},
        )
        assert r.status_code == 404

    async def test_request_extension_user_role_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        client: AsyncClient = await authed_client_factory(role="user")
        r = await client.post(
            f"/api/v1/cases/{case_id}/request-extension",
            json={"extension_days": 7, "reason": "x"},
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# GET /{case_id}/search-documents
# ---------------------------------------------------------------------------


class TestSearchCaseDocuments:
    async def test_search_case_documents_short_query_400(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get(f"/api/v1/cases/{case_id}/search-documents?q=a")
        assert r.status_code == 400

    async def test_search_case_documents_missing_case_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get("/api/v1/cases/ghost/search-documents?q=findme")
        assert r.status_code == 404

    async def test_search_case_documents_happy_path(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        # Seed a document for this case
        doc_id = str(uuid.uuid4())
        await db.documents.insert_one(
            {
                "id": doc_id,
                "case_id": case_id,
                "filename": "uniquequeryword.pdf",
                "uploaded_at": datetime.utcnow(),
                "extracted_text": "uniquequeryword content",
            }
        )

        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get(f"/api/v1/cases/{case_id}/search-documents?q=uniquequeryword")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["case_id"] == case_id
        assert "results" in body
        assert "total_results" in body


# ---------------------------------------------------------------------------
# Branch coverage for /search and /deadline-dashboard (now reachable post-B12)
# ---------------------------------------------------------------------------
#
# The B12 fix (2026-05-12) moved `include_router(queue_router)` above the
# `/{case_id}` decorator in `cases/routes.py`, so `/search` and
# `/deadline-dashboard` are now reachable through the real URL surface.
# Pre-fix these tests mounted `queue_routes.router` standalone via an
# isolated FastAPI app — that workaround is dropped; they now drive the
# real `/api/v1/cases/...` URLs.


class TestSearchAndDeadlineDashboardBranches:
    """Branch coverage for handlers previously unreachable by URL."""

    async def test_deadline_dashboard_filters_closed_and_cancelled(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """The handler's `$nin: [closed, cancelled]` filter excludes those
        statuses from `all_cases`."""
        await _seed_case(db, status="new")
        await _seed_case(db, status="closed")  # excluded

        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get("/api/v1/cases/deadline-dashboard")
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["all_cases"]) == 1

    async def test_search_documents_only_branch(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """The `search_type=documents` branch returns no `cases` key."""
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get("/api/v1/cases/search?q=foo&search_type=documents")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "documents" in body
        assert "cases" not in body

    async def test_search_cases_only_branch(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """The `search_type=cases` branch returns no `documents` key."""
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get("/api/v1/cases/search?q=foo&search_type=cases")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "cases" in body
        assert "documents" not in body
