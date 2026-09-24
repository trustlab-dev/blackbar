"""Integration tests for `src.teams.routes` (AUTH-04 regression focus)."""

from __future__ import annotations

import uuid

import httpx
import pytest
from httpx import ASGITransport
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.auth.auth_service import AuthService
from src.users.repository import UsersRepository


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase, app):
    import src.dependencies as deps_mod
    import src.teams.routes as teams_routes

    async def _db_override():
        return db

    monkeypatch.setattr(deps_mod, "users", db.users)
    monkeypatch.setattr(teams_routes, "users", db.users)
    app.dependency_overrides[teams_routes.get_db] = _db_override
    yield db
    app.dependency_overrides.pop(teams_routes.get_db, None)


async def _seed(db: AsyncIOMotorDatabase, role: str) -> str:
    uid = str(uuid.uuid4())
    await db.users.insert_one(
        {
            "id": uid,
            "email": f"{role}-{uid[:8]}@example.com",
            "name": role,
            "role": role,
            "status": "active",
            "password_hash": AuthService.hash_password("correct-horse-battery"),
            "activation_token": "$2b$12$abcdefghijklmnopqrstuuActivationTokenHashValue000",
            "external_id": "idp-123",
        }
    )
    return uid


async def _client(app, db: AsyncIOMotorDatabase, user_id: str) -> httpx.AsyncClient:
    repo = UsersRepository(db)
    user = await repo.get_by_id(user_id)
    assert user is not None
    token = await AuthService(repo).issue_token(user)
    return httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {token}"},
    )


class TestGetTeamMembers:
    async def test_member_details_are_allowlisted(
        self, app, db: AsyncIOMotorDatabase, patched
    ) -> None:
        admin_id = await _seed(db, "admin")
        analyst_id = await _seed(db, "analyst")
        team_id = str(uuid.uuid4())
        await db.teams.insert_one(
            {"id": team_id, "name": "T", "manager_id": admin_id, "member_ids": [admin_id]}
        )

        async with await _client(app, db, analyst_id) as c:
            r = await c.get(f"/api/v1/teams/{team_id}")

        assert r.status_code == 200, r.text
        members = r.json()["members"]
        assert len(members) == 1
        assert set(members[0]) <= {
            "id",
            "email",
            "name",
            "role",
            "status",
            "created_at",
            "updated_at",
        }
        assert "password_hash" not in r.text
        assert "activation_token" not in r.text
        assert "external_id" not in r.text

    async def test_guest_cannot_read_team(self, app, db: AsyncIOMotorDatabase, patched) -> None:
        guest_id = await _seed(db, "guest")
        team_id = str(uuid.uuid4())
        await db.teams.insert_one({"id": team_id, "name": "T", "member_ids": []})
        async with await _client(app, db, guest_id) as c:
            r = await c.get(f"/api/v1/teams/{team_id}")
        assert r.status_code == 403
