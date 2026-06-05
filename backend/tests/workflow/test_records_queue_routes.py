"""Integration tests for records-confirmation + priority-queue endpoints
in `src.workflow.routes`.

Phase 2.5 Batch B (3/3). Covers:
    POST   /cases/{case_id}/records-confirmation
    GET    /cases/{case_id}/records-confirmation
    DELETE /cases/{case_id}/records-confirmation
    GET    /queue/prioritized
    GET    /queue/workload/{analyst_id}
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorDatabase

from tests.factories import make_case


@pytest.fixture
def patch_routes_db(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase, app):
    import src.database as db_mod
    import src.dependencies as deps_mod
    from src.workflow import routes as workflow_routes

    async def _override_get_db():
        return db

    app.dependency_overrides[workflow_routes.get_db] = _override_get_db
    monkeypatch.setattr(deps_mod, "users", db.users)
    monkeypatch.setattr(db_mod, "users", db.users)

    yield db

    app.dependency_overrides.pop(workflow_routes.get_db, None)


async def _seed_case(db: AsyncIOMotorDatabase, **overrides) -> str:
    case = make_case(**overrides)
    await db.cases.insert_one(case)
    return case["id"]


# ---------------------------------------------------------------------------
# POST /cases/{case_id}/records-confirmation
# ---------------------------------------------------------------------------


class TestConfirmAllRecordsUploaded:
    async def test_confirm_happy_path_persists(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db, all_records_uploaded=False)
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.post(
            f"/api/v1/cases/{case_id}/records-confirmation",
            json={"notes": "all done"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["confirmed"] is True
        assert body["notes"] == "all done"
        # Case row was updated
        case = await db.cases.find_one({"id": case_id})
        assert case["all_records_uploaded"] is True
        assert case["all_records_confirmation_notes"] == "all done"

    async def test_confirm_missing_case_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.post(
            "/api/v1/cases/ghost/records-confirmation",
            json={"notes": "x"},
        )
        assert r.status_code == 404

    async def test_confirm_unauthenticated_401(self, client) -> None:
        r = client.post("/api/v1/cases/foo/records-confirmation", json={"notes": "x"})
        assert r.status_code == 401

    async def test_confirm_without_notes(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            f"/api/v1/cases/{case_id}/records-confirmation",
            json={},
        )
        assert r.status_code == 200
        assert r.json()["notes"] is None


# ---------------------------------------------------------------------------
# GET /cases/{case_id}/records-confirmation
# ---------------------------------------------------------------------------


class TestGetRecordsConfirmation:
    async def test_get_unconfirmed_default(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db, all_records_uploaded=False)
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get(f"/api/v1/cases/{case_id}/records-confirmation")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["confirmed"] is False

    async def test_get_confirmed_returns_metadata(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(
            db,
            all_records_uploaded=True,
            all_records_confirmed_by="u-9",
            all_records_confirmed_by_name="Bob",
            all_records_confirmed_at=datetime.utcnow(),
            all_records_confirmation_notes="all here",
        )
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get(f"/api/v1/cases/{case_id}/records-confirmation")
        assert r.status_code == 200
        body = r.json()
        assert body["confirmed"] is True
        assert body["confirmed_by"] == "u-9"
        assert body["confirmed_by_name"] == "Bob"
        assert body["notes"] == "all here"

    async def test_get_missing_case_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get("/api/v1/cases/ghost/records-confirmation")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /cases/{case_id}/records-confirmation
# ---------------------------------------------------------------------------


class TestRevokeRecordsConfirmation:
    async def test_revoke_happy_path(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(
            db,
            all_records_uploaded=True,
            all_records_confirmed_by="u",
            all_records_confirmed_by_name="N",
            all_records_confirmed_at=datetime.utcnow(),
            all_records_confirmation_notes="notes",
        )
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.delete(f"/api/v1/cases/{case_id}/records-confirmation")
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True
        case = await db.cases.find_one({"id": case_id})
        assert case["all_records_uploaded"] is False
        assert case["all_records_confirmed_by"] is None
        assert case["all_records_confirmation_notes"] is None

    async def test_revoke_missing_case_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.delete("/api/v1/cases/ghost/records-confirmation")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /queue/prioritized
# ---------------------------------------------------------------------------


class TestQueuePrioritized:
    async def test_prioritized_returns_cases_sorted_by_score(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_case(
            db,
            title="OVERDUE",
            due_date=datetime.utcnow() - timedelta(days=10),
        )
        await _seed_case(
            db,
            title="LATER",
            due_date=datetime.utcnow() + timedelta(days=30),
        )
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get("/api/v1/queue/prioritized")
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body) == 2
        assert body[0]["title"] == "OVERDUE"

    async def test_prioritized_filter_by_workflow_stage(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_case(db, workflow_stage="review")
        await _seed_case(db, workflow_stage="intake")
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get("/api/v1/queue/prioritized?workflow_stage=review")
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 1
        assert body[0]["workflow_stage"] == "review"

    async def test_prioritized_filter_by_clock_status(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_case(db, clock_status="paused")
        await _seed_case(db, clock_status="running")
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get("/api/v1/queue/prioritized?clock_status=paused")
        assert r.status_code == 200
        body = r.json()
        assert all(c["clock_status"] == "paused" for c in body)

    async def test_prioritized_filter_include_closed_flag(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_case(db, status="new")
        await _seed_case(db, status="closed")
        client: AsyncClient = await authed_client_factory(role="analyst")
        # Default excludes closed
        r = await client.get("/api/v1/queue/prioritized")
        assert len(r.json()) == 1
        # include_closed=true shows both
        r = await client.get("/api/v1/queue/prioritized?include_closed=true")
        assert len(r.json()) == 2

    async def test_prioritized_limit_caps_at_200(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """The handler clamps `limit` to <=200 via `min(limit, 200)`.
        Pin that requesting 500 doesn't raise — it's clamped before the
        QueueFilter validation (`le=200`)."""
        await _seed_case(db)
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get("/api/v1/queue/prioritized?limit=500")
        assert r.status_code == 200

    async def test_prioritized_unauthenticated_401(self, client) -> None:
        r = client.get("/api/v1/queue/prioritized")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /queue/workload/{analyst_id}
# ---------------------------------------------------------------------------


class TestQueueWorkload:
    async def test_workload_returns_analysts_cases(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_case(db, assignee="alice", title="A")
        await _seed_case(db, assigned_user_ids=["alice"], title="B")
        await _seed_case(db, assignee="bob", title="C")
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/queue/workload/alice")
        assert r.status_code == 200, r.text
        body = r.json()
        titles = {c["title"] for c in body}
        assert titles == {"A", "B"}

    async def test_workload_unauthenticated_401(self, client) -> None:
        r = client.get("/api/v1/queue/workload/alice")
        assert r.status_code == 401

    async def test_workload_unknown_analyst_returns_empty(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_case(db, assignee="bob")
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/queue/workload/ghost")
        assert r.status_code == 200
        assert r.json() == []
