"""AUTH-24: auth and user-admin events land in the `audit_logs` collection."""

from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.auth.auth_service import AuthService
from src.users.models import UserCreate
from src.users.repository import UsersRepository


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase):
    import src.auth.routes as auth_routes
    import src.dependencies as deps_mod

    monkeypatch.setattr(deps_mod, "users", db.users)
    monkeypatch.setattr(auth_routes, "db", db)
    return db


def _client(app, token: str | None = None) -> httpx.AsyncClient:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver", headers=headers
    )


async def _admin_token(db: AsyncIOMotorDatabase) -> tuple[str, str]:
    repo = UsersRepository(db)
    user = await repo.create(
        UserCreate(email="audit-admin@example.com", name="A", password="x"),
        AuthService.hash_password("correct-horse-battery"),
    )
    await db.users.update_one({"id": user.id}, {"$set": {"role": "admin"}})
    user.role = "admin"
    return user.id, await AuthService(repo).issue_token(user)


async def test_failed_and_successful_logins_are_audited(app, db, patched) -> None:
    await _admin_token(db)
    async with _client(app) as c:
        await c.post(
            "/api/v1/auth/login",
            json={"email": "audit-admin@example.com", "password": "wrong-password"},
        )
        ok = await c.post(
            "/api/v1/auth/login",
            json={"email": "audit-admin@example.com", "password": "correct-horse-battery"},
        )
        assert ok.status_code == 200, ok.text

    events = await db.audit_logs.find({"category": "auth"}).to_list(None)
    actions = [e["action"] for e in events]
    assert actions == ["login_failed", "login_succeeded"]
    failed = events[0]
    assert failed["success"] is False
    assert "email_hash" in failed["details"]
    # Never the raw email.
    assert "audit-admin@example.com" not in repr(failed)
    assert failed["ip_address"]


async def test_user_admin_events_are_audited(app, db, patched) -> None:
    admin_id, token = await _admin_token(db)
    async with _client(app, token) as c:
        created = await c.post(
            "/api/v1/auth/users",
            json={
                "email": "target@example.com",
                "full_name": "T",
                "password": "a-long-enough-passphrase",
                "role": "user",
            },
        )
        target_id = created.json()["id"]
        await c.put(f"/api/v1/auth/users/{target_id}", json={"role": "analyst"})
        await c.delete(f"/api/v1/auth/users/{target_id}")
        await c.post("/api/v1/auth/logout")

    events = await db.audit_logs.find({"category": "auth"}).sort("timestamp", 1).to_list(None)
    assert [e["action"] for e in events] == [
        "user_created",
        "user_updated",
        "user_deleted",
        "logout",
    ]
    updated = events[1]
    assert updated["actor_id"] == admin_id
    assert updated["target_id"] == target_id
    assert updated["details"]["role_before"] == "user"
    assert updated["details"]["role_after"] == "analyst"


class TestRoleAndPasswordValidation:
    """AUTH-25: role strings and admin-set passwords are validated."""

    @pytest.mark.parametrize("role", ["superadmin", "Admin ", "root", ""])
    async def test_unknown_role_rejected(self, app, db, patched, role: str) -> None:
        _, token = await _admin_token(db)
        async with _client(app, token) as c:
            r = await c.post(
                "/api/v1/auth/users",
                json={"email": "r@example.com", "full_name": "R", "role": role},
            )
        # "Admin " normalises to a valid role; everything else is a 422.
        if role.strip().lower() in {"admin"}:
            assert r.status_code == 200, r.text
        else:
            assert r.status_code == 422, r.text

    async def test_short_password_rejected(self, app, db, patched) -> None:
        _, token = await _admin_token(db)
        async with _client(app, token) as c:
            r = await c.post(
                "/api/v1/auth/users",
                json={"email": "p@example.com", "full_name": "P", "role": "user", "password": "a"},
            )
        assert r.status_code == 422, r.text

    async def test_over_72_byte_password_rejected_on_set_and_login(self, app, db, patched) -> None:
        _, token = await _admin_token(db)
        async with _client(app, token) as c:
            r = await c.post(
                "/api/v1/auth/users",
                json={
                    "email": "long@example.com",
                    "full_name": "L",
                    "role": "user",
                    "password": "a" * 73,
                },
            )
            assert r.status_code == 422, r.text
            login = await c.post(
                "/api/v1/auth/login",
                json={"email": "audit-admin@example.com", "password": "b" * 100},
            )
        assert login.status_code == 422, login.text

    async def test_admin_cannot_grant_owner(self, app, db, patched) -> None:
        _, token = await _admin_token(db)
        async with _client(app, token) as c:
            r = await c.post(
                "/api/v1/auth/users",
                json={"email": "o@example.com", "full_name": "O", "role": "owner"},
            )
        assert r.status_code == 403, r.text
