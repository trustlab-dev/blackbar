"""Integration tests for `src.templates.routes` (CRUD + rendering).

Phase 2.8 Batch B. Target >=80% line coverage on `src/templates/routes.py`.

Endpoint surface (7 endpoints, mounted at /api/v1/templates/...):
    GET    /                            -> list (admin/analyst/owner only)
    POST   /                            -> create (admin/owner only)
    GET    /{template_id}               -> get one (any authed)
    PUT    /{template_id}               -> update (admin/owner only)
    DELETE /{template_id}               -> delete (admin/owner only)
    POST   /{template_id}/render?case_id=... -> render with case data
    GET    /available-variables/list    -> available {var} placeholders

Reality pins:
- Routes use `Depends(get_database_from_request)` from `src.core.database`.
  Tests override the FastAPI dependency to redirect to the per-test motor
  database.
- `check_role(["owner","admin","analyst"])` on `list_templates` blocks role
  `user`. Get-one / render-by-case / available-variables have no role
  decorator and accept any authed user.
- `render_template(...)` is the workhorse string-replacer. Supports
  datetime and ISO-8601 string `received_date` / `due_date`; falls back
  to raw str when ISO parsing throws.
- `created_at`/`updated_at` use naive `datetime.utcnow()` — pinned but not
  asserted on timezone.
- `created_by` is read from `current_user["id"]`; tests verify it matches
  the seed user's ID (via the authed_client_factory).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorDatabase

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_routes_db(monkeypatch: pytest.MonkeyPatch, app, db: AsyncIOMotorDatabase):
    """Override `get_database_from_request` so route handlers see the
    per-test motor database. Also rebinds `src.dependencies.users` because
    `get_current_user` reads the global module-level `users` collection."""
    import src.dependencies as deps_mod
    from src.core import database as core_db

    async def _override_db(request=None):
        return db

    app.dependency_overrides[core_db.get_database_from_request] = _override_db
    monkeypatch.setattr(deps_mod, "users", db.users)
    yield db
    app.dependency_overrides.pop(core_db.get_database_from_request, None)


def _anon_client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


async def _seed_template(
    db: AsyncIOMotorDatabase,
    *,
    template_id: str,
    name: str = "Ack",
    content: str = "Hello {requester_name}",
    category: str = "general",
    is_active: bool = True,
    created_by: str = "seed",
) -> None:
    now = datetime.utcnow()
    await db.templates.insert_one(
        {
            "id": template_id,
            "name": name,
            "description": "test",
            "content": content,
            "category": category,
            "is_active": is_active,
            "created_at": now,
            "updated_at": now,
            "created_by": created_by,
        }
    )


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------


class TestListTemplates:
    async def test_admin_lists_active_templates(
        self, db, authed_client_factory, patch_routes_db
    ) -> None:
        await _seed_template(db, template_id="t1", name="A")
        await _seed_template(db, template_id="t2", name="B", is_active=False)
        client = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/templates/")
        assert r.status_code == 200
        names = [t["name"] for t in r.json()]
        assert "A" in names
        assert "B" not in names  # active_only default True

    async def test_can_disable_active_only(
        self, db, authed_client_factory, patch_routes_db
    ) -> None:
        await _seed_template(db, template_id="t1", name="A")
        await _seed_template(db, template_id="t2", name="B", is_active=False)
        client = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/templates/?active_only=false")
        assert r.status_code == 200
        names = {t["name"] for t in r.json()}
        assert {"A", "B"} <= names

    async def test_filters_by_category(self, db, authed_client_factory, patch_routes_db) -> None:
        await _seed_template(db, template_id="t1", name="Ack", category="response_letter")
        await _seed_template(db, template_id="t2", name="Status", category="status_update")
        client = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/templates/?category=response_letter")
        assert r.status_code == 200
        names = [t["name"] for t in r.json()]
        assert names == ["Ack"]

    async def test_analyst_can_list(self, db, authed_client_factory, patch_routes_db) -> None:
        client = await authed_client_factory(role="analyst")
        r = await client.get("/api/v1/templates/")
        assert r.status_code == 200

    async def test_user_role_forbidden(self, db, authed_client_factory, patch_routes_db) -> None:
        client = await authed_client_factory(role="user")
        r = await client.get("/api/v1/templates/")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# POST /
# ---------------------------------------------------------------------------


class TestCreateTemplate:
    async def test_admin_can_create(self, db, authed_client_factory, patch_routes_db) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/templates/",
            json={
                "name": "Welcome",
                "description": "x",
                "content": "Hi {user_name}",
                "category": "general",
                "is_active": True,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == "Welcome"
        assert "id" in body and body["id"]
        # Persisted
        doc = await db.templates.find_one({"id": body["id"]})
        assert doc is not None

    async def test_user_forbidden(self, db, authed_client_factory, patch_routes_db) -> None:
        client = await authed_client_factory(role="user")
        r = await client.post(
            "/api/v1/templates/",
            json={"name": "X", "content": "y"},
        )
        assert r.status_code == 403

    async def test_analyst_forbidden(self, db, authed_client_factory, patch_routes_db) -> None:
        # Create is admin/owner only (not analyst)
        client = await authed_client_factory(role="analyst")
        r = await client.post(
            "/api/v1/templates/",
            json={"name": "X", "content": "y"},
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# GET /{template_id}
# ---------------------------------------------------------------------------


class TestGetTemplate:
    async def test_returns_template(self, db, authed_client_factory, patch_routes_db) -> None:
        await _seed_template(db, template_id="t1", name="X")
        client = await authed_client_factory(role="user")
        r = await client.get("/api/v1/templates/t1")
        assert r.status_code == 200
        assert r.json()["name"] == "X"

    async def test_404_when_missing(self, db, authed_client_factory, patch_routes_db) -> None:
        client = await authed_client_factory(role="user")
        r = await client.get("/api/v1/templates/missing")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# PUT /{template_id}
# ---------------------------------------------------------------------------


class TestUpdateTemplate:
    async def test_admin_can_update(self, db, authed_client_factory, patch_routes_db) -> None:
        await _seed_template(db, template_id="t1", name="Old")
        client = await authed_client_factory(role="admin")
        r = await client.put(
            "/api/v1/templates/t1",
            json={"name": "New", "content": "Updated"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "New"
        assert body["content"] == "Updated"

    async def test_404_when_missing(self, db, authed_client_factory, patch_routes_db) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.put("/api/v1/templates/missing", json={"name": "X"})
        assert r.status_code == 404

    async def test_user_forbidden(self, db, authed_client_factory, patch_routes_db) -> None:
        await _seed_template(db, template_id="t1")
        client = await authed_client_factory(role="user")
        r = await client.put("/api/v1/templates/t1", json={"name": "X"})
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /{template_id}
# ---------------------------------------------------------------------------


class TestDeleteTemplate:
    async def test_admin_can_delete(self, db, authed_client_factory, patch_routes_db) -> None:
        await _seed_template(db, template_id="t1")
        client = await authed_client_factory(role="admin")
        r = await client.delete("/api/v1/templates/t1")
        assert r.status_code == 200
        assert await db.templates.find_one({"id": "t1"}) is None

    async def test_404_when_missing(self, db, authed_client_factory, patch_routes_db) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.delete("/api/v1/templates/missing")
        assert r.status_code == 404

    async def test_user_forbidden(self, db, authed_client_factory, patch_routes_db) -> None:
        await _seed_template(db, template_id="t1")
        client = await authed_client_factory(role="user")
        r = await client.delete("/api/v1/templates/t1")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# POST /{template_id}/render
# ---------------------------------------------------------------------------


class TestRenderTemplateForCase:
    async def test_renders_basic_substitutions(
        self, db, authed_client_factory, patch_routes_db
    ) -> None:
        await _seed_template(
            db,
            template_id="t1",
            name="Ack",
            content="Hello {requester_name}, case #{case_number}",
        )
        await db.cases.insert_one(
            {
                "id": "case-1",
                "tracking_number": "FOI-2026-001",
                "title": "Test case",
                "requester": {"name": "Alice", "email": "a@x.test"},
            }
        )

        client = await authed_client_factory(role="user")
        r = await client.post("/api/v1/templates/t1/render?case_id=case-1")
        assert r.status_code == 200
        body = r.json()
        assert "Alice" in body["rendered_content"]
        assert "FOI-2026-001" in body["rendered_content"]

    async def test_template_not_found(self, db, authed_client_factory, patch_routes_db) -> None:
        client = await authed_client_factory(role="user")
        r = await client.post("/api/v1/templates/missing/render?case_id=x")
        assert r.status_code == 404

    async def test_case_not_found(self, db, authed_client_factory, patch_routes_db) -> None:
        await _seed_template(db, template_id="t1")
        client = await authed_client_factory(role="user")
        r = await client.post("/api/v1/templates/t1/render?case_id=missing")
        assert r.status_code == 404

    async def test_document_count_placeholder_replaced(
        self, db, authed_client_factory, patch_routes_db
    ) -> None:
        await _seed_template(
            db,
            template_id="t1",
            content="Docs: {document_count}",
        )
        await db.cases.insert_one({"id": "case-1", "tracking_number": "T1"})
        await db.documents.insert_one({"id": "d1", "case_id": "case-1"})
        await db.documents.insert_one({"id": "d2", "case_id": "case-1"})

        client = await authed_client_factory(role="user")
        r = await client.post("/api/v1/templates/t1/render?case_id=case-1")
        assert r.status_code == 200
        assert "Docs: 2" in r.json()["rendered_content"]

    async def test_received_date_as_datetime_formatted(
        self, db, authed_client_factory, patch_routes_db
    ) -> None:
        await _seed_template(db, template_id="t1", content="Received: {received_date}")
        await db.cases.insert_one(
            {
                "id": "case-1",
                "tracking_number": "T1",
                "received_date": datetime(2026, 5, 1, 12, 0, 0),
            }
        )
        client = await authed_client_factory(role="user")
        r = await client.post("/api/v1/templates/t1/render?case_id=case-1")
        assert r.status_code == 200
        assert "May 01, 2026" in r.json()["rendered_content"]

    async def test_received_date_as_iso_string_with_z(
        self, db, authed_client_factory, patch_routes_db
    ) -> None:
        await _seed_template(db, template_id="t1", content="On {received_date}")
        await db.cases.insert_one(
            {
                "id": "case-1",
                "tracking_number": "T1",
                "received_date": "2026-05-01T12:00:00Z",
            }
        )
        client = await authed_client_factory(role="user")
        r = await client.post("/api/v1/templates/t1/render?case_id=case-1")
        assert r.status_code == 200
        assert "May 01, 2026" in r.json()["rendered_content"]

    async def test_received_date_unparseable_falls_back(
        self, db, authed_client_factory, patch_routes_db
    ) -> None:
        await _seed_template(db, template_id="t1", content="When: {received_date}")
        await db.cases.insert_one(
            {
                "id": "case-1",
                "tracking_number": "T1",
                "received_date": "yesterday",
            }
        )
        client = await authed_client_factory(role="user")
        r = await client.post("/api/v1/templates/t1/render?case_id=case-1")
        assert r.status_code == 200
        assert "When: yesterday" in r.json()["rendered_content"]

    async def test_due_date_datetime(self, db, authed_client_factory, patch_routes_db) -> None:
        await _seed_template(db, template_id="t1", content="Due: {due_date}")
        await db.cases.insert_one(
            {
                "id": "case-1",
                "tracking_number": "T1",
                "due_date": datetime(2026, 6, 1),
            }
        )
        client = await authed_client_factory(role="user")
        r = await client.post("/api/v1/templates/t1/render?case_id=case-1")
        assert "June 01, 2026" in r.json()["rendered_content"]

    async def test_due_date_iso_string(self, db, authed_client_factory, patch_routes_db) -> None:
        await _seed_template(db, template_id="t1", content="Due: {due_date}")
        await db.cases.insert_one(
            {
                "id": "case-1",
                "tracking_number": "T1",
                "due_date": "2026-06-01T00:00:00Z",
            }
        )
        client = await authed_client_factory(role="user")
        r = await client.post("/api/v1/templates/t1/render?case_id=case-1")
        assert "June 01, 2026" in r.json()["rendered_content"]

    async def test_due_date_unparseable_falls_back(
        self, db, authed_client_factory, patch_routes_db
    ) -> None:
        await _seed_template(db, template_id="t1", content="Due: {due_date}")
        await db.cases.insert_one(
            {
                "id": "case-1",
                "tracking_number": "T1",
                "due_date": "next-week",
            }
        )
        client = await authed_client_factory(role="user")
        r = await client.post("/api/v1/templates/t1/render?case_id=case-1")
        assert "Due: next-week" in r.json()["rendered_content"]


# ---------------------------------------------------------------------------
# GET /available-variables/list
# ---------------------------------------------------------------------------


class TestAvailableVariables:
    async def test_returns_list_of_variables(
        self, db, authed_client_factory, patch_routes_db
    ) -> None:
        client = await authed_client_factory(role="user")
        r = await client.get("/api/v1/templates/available-variables/list")
        assert r.status_code == 200
        body = r.json()
        names = [v["name"] for v in body["variables"]]
        assert "{case_number}" in names
        assert "{requester_name}" in names


# ---------------------------------------------------------------------------
# render_template unit tests (no HTTP)
# ---------------------------------------------------------------------------


class TestRenderTemplateFunction:
    def test_uses_created_at_when_received_date_missing(self) -> None:
        from src.templates.routes import render_template

        case = {
            "tracking_number": "T1",
            "created_at": datetime(2026, 4, 15, 9, 0, 0),
        }
        out = render_template("On {received_date}", case)
        assert "April 15, 2026" in out

    def test_user_title_replaced(self) -> None:
        from src.templates.routes import render_template

        case = {"tracking_number": "T1"}
        user = {"name": "Bob", "title": "Director"}
        out = render_template("{user_name}, {user_title}", case, user)
        assert "Bob" in out
        assert "Director" in out

    def test_user_name_falls_back_to_username(self) -> None:
        from src.templates.routes import render_template

        case = {"tracking_number": "T1"}
        user = {"username": "alice@example.com"}  # no `name`
        out = render_template("Hello {user_name}", case, user)
        assert "alice@example.com" in out

    def test_organization_placeholder_default(self) -> None:
        from src.templates.routes import render_template

        out = render_template("From {organization}", {"tracking_number": "T1"})
        assert "[Organization Name]" in out

    def test_no_user_data_skips_user_block(self) -> None:
        from src.templates.routes import render_template

        out = render_template("Hello {user_name}", {"tracking_number": "T1"})
        # Without user_data the placeholder is left as-is (not replaced)
        assert "{user_name}" in out
