"""AUTH-04: no API response may carry a password or activation-token hash.

Seeds users whose documents hold bcrypt `password_hash` and
`activation_token` values, then drives every endpoint that serialises user
records and asserts, grep-style over the raw JSON, that neither the field
name nor any `$2b$` hash appears.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from httpx import ASGITransport
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.auth.auth_service import AuthService
from src.users.repository import UsersRepository

FORBIDDEN = ("password_hash", "$2b$", "activation_token")


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase, app):
    import src.admin.routes as admin_routes
    import src.auth.routes as auth_routes
    import src.cases.team_routes as case_team_routes
    import src.dependencies as deps_mod
    import src.teams.routes as teams_routes

    async def _db_override():
        return db

    monkeypatch.setattr(deps_mod, "users", db.users)
    monkeypatch.setattr(auth_routes, "db", db)
    monkeypatch.setattr(admin_routes, "users", db.users)
    monkeypatch.setattr(teams_routes, "users", db.users)
    monkeypatch.setattr(case_team_routes, "users", db.users)
    app.dependency_overrides[teams_routes.get_db] = _db_override
    app.dependency_overrides[case_team_routes.get_db] = _db_override
    yield db
    app.dependency_overrides.pop(teams_routes.get_db, None)
    app.dependency_overrides.pop(case_team_routes.get_db, None)


async def _seed(db: AsyncIOMotorDatabase, role: str) -> str:
    uid = str(uuid.uuid4())
    await db.users.insert_one(
        {
            "id": uid,
            "email": f"{role}-{uid[:8]}@example.com",
            "name": f"{role} person",
            "role": role,
            "status": "active",
            "password_hash": AuthService.hash_password("correct-horse-battery"),
            "activation_token": AuthService.hash_password("invite-token-value"),
            "activation_token_expires_at": datetime.now(UTC),
            "external_id": None,
            "created_at": datetime.now(UTC),
        }
    )
    return uid


def _assert_clean(r: httpx.Response) -> None:
    assert r.status_code < 400, f"{r.request.method} {r.request.url} -> {r.status_code} {r.text}"
    for needle in FORBIDDEN:
        assert needle not in r.text, f"{r.request.url} leaked {needle!r}: {r.text[:500]}"


async def test_no_endpoint_leaks_password_or_token_hashes(
    app, db: AsyncIOMotorDatabase, patched
) -> None:
    admin_id = await _seed(db, "admin")
    analyst_id = await _seed(db, "analyst")
    guest_id = await _seed(db, "guest")
    user_id = await _seed(db, "user")

    repo = UsersRepository(db)
    admin = await repo.get_by_id(admin_id)
    assert admin is not None
    token = await AuthService(repo).issue_token(admin)

    case_id = str(uuid.uuid4())
    await db.cases.insert_one(
        {
            "id": case_id,
            "title": "c",
            "case_team": [
                {"user_id": analyst_id, "role": "analyst", "status": "active"},
                {"user_id": guest_id, "role": "third_party", "status": "active"},
            ],
        }
    )

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        created = await c.post(
            "/api/v1/teams/",
            json={"name": "Team A", "manager_id": analyst_id, "member_ids": [admin_id, analyst_id]},
        )
        _assert_clean(created)
        team_id = created.json()["id"]

        responses = [
            await c.get(f"/api/v1/teams/{team_id}"),
            await c.get("/api/v1/teams/"),
            await c.put(f"/api/v1/teams/{team_id}", json={"member_ids": [admin_id, user_id]}),
            await c.post(f"/api/v1/teams/{team_id}/members/{guest_id}"),
            await c.get("/api/v1/auth/users"),
            await c.get("/api/v1/auth/users/search"),
            await c.get("/api/v1/auth/users/assignable"),
            await c.get("/api/v1/auth/users/guests"),
            await c.get("/api/v1/auth/me"),
            await c.get("/api/v1/admin/users/search"),
            await c.get(f"/api/v1/cases/{case_id}/team"),
            await c.post(
                "/api/v1/auth/users",
                json={
                    "email": "new-person@example.com",
                    "full_name": "New Person",
                    "password": "a-long-enough-passphrase",
                    "role": "analyst",
                },
            ),
            await c.put(f"/api/v1/auth/users/{user_id}", json={"full_name": "Renamed"}),
        ]

    for r in responses:
        _assert_clean(r)
