"""Integration tests for clock endpoints in `src.workflow.routes`.

Phase 2.5 Batch B (1/3). Target >=80% coverage on the clock subset of
src.workflow.routes:
    POST /cases/{case_id}/clock/pause
    POST /cases/{case_id}/clock/resume
    GET  /cases/{case_id}/clock/history

All mounted at `/api/v1/cases/{case_id}/clock/...` (workflow router is
included on `/api/v1` directly).

Auth model:
- Endpoints depend on `get_current_user` from `src.dependencies`
  (4-tier system role). No explicit case-team role gating in the
  clock handlers — any authenticated user with a system role passes.

Patch points (mirroring tests/cases/test_queue_routes.py):
- `src.workflow.routes.get_db` override
- `src.dependencies.users` rebind
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
# POST /cases/{case_id}/clock/pause
# ---------------------------------------------------------------------------


class TestPauseClock:
    async def test_pause_happy_path(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db, clock_status="running")
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.post(
            f"/api/v1/cases/{case_id}/clock/pause",
            json={"event_type": "pause", "reason": "fee_pending", "notes": "x"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["event_type"] == "pause"
        assert body["reason"] == "fee_pending"
        # Side effects on case row
        case = await db.cases.find_one({"id": case_id})
        assert case["clock_status"] == "paused"
        # Audit log entry recorded
        assert any(entry.get("action") == "clock_paused" for entry in case.get("audit_log", []))

    async def test_pause_missing_case_returns_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.post(
            "/api/v1/cases/ghost/clock/pause",
            json={"event_type": "pause", "reason": "manual"},
        )
        assert r.status_code == 404

    async def test_pause_already_paused_returns_400(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db, clock_status="paused")
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.post(
            f"/api/v1/cases/{case_id}/clock/pause",
            json={"event_type": "pause", "reason": "manual"},
        )
        assert r.status_code == 400
        assert "already paused" in r.text.lower()

    async def test_pause_requires_reason(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """The handler raises 400 if `reason` is missing post-validation."""
        case_id = await _seed_case(db, clock_status="running")
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.post(
            f"/api/v1/cases/{case_id}/clock/pause",
            json={"event_type": "pause"},  # no reason
        )
        assert r.status_code == 400
        assert "reason" in r.text.lower()

    async def test_pause_unauthenticated_401(self, client) -> None:
        r = client.post(
            "/api/v1/cases/foo/clock/pause",
            json={"event_type": "pause", "reason": "manual"},
        )
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /cases/{case_id}/clock/resume
# ---------------------------------------------------------------------------


class TestResumeClock:
    async def test_resume_happy_path(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(
            db,
            clock_status="paused",
            clock_paused_at=datetime.utcnow() - timedelta(days=2),
            due_date=datetime.utcnow() + timedelta(days=10),
        )
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(f"/api/v1/cases/{case_id}/clock/resume")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["event_type"] == "resume"
        case = await db.cases.find_one({"id": case_id})
        assert case["clock_status"] == "running"
        assert any(entry.get("action") == "clock_resumed" for entry in case.get("audit_log", []))

    async def test_resume_missing_case_returns_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post("/api/v1/cases/ghost/clock/resume")
        assert r.status_code == 404

    async def test_resume_not_paused_returns_400(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db, clock_status="running")
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(f"/api/v1/cases/{case_id}/clock/resume")
        assert r.status_code == 400
        assert "not paused" in r.text.lower()

    async def test_resume_unauthenticated_401(self, client) -> None:
        r = client.post("/api/v1/cases/foo/clock/resume")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /cases/{case_id}/clock/history
# ---------------------------------------------------------------------------


class TestClockHistory:
    async def test_history_happy_path_empty(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db)
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get(f"/api/v1/cases/{case_id}/clock/history")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["case_id"] == case_id
        assert body["status"] == "running"
        assert body["events"] == []

    async def test_history_after_pause_lists_event(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case(db, clock_status="running")
        client: AsyncClient = await authed_client_factory(role="analyst")
        # Pause first
        await client.post(
            f"/api/v1/cases/{case_id}/clock/pause",
            json={"event_type": "pause", "reason": "manual"},
        )
        r = await client.get(f"/api/v1/cases/{case_id}/clock/history")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "paused"
        assert len(body["events"]) == 1
        assert body["events"][0]["event_type"] == "pause"

    async def test_history_missing_case_returns_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get("/api/v1/cases/ghost/clock/history")
        assert r.status_code == 404

    async def test_history_unauthenticated_401(self, client) -> None:
        r = client.get("/api/v1/cases/foo/clock/history")
        assert r.status_code == 401
