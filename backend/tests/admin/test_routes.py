"""Integration tests for `src.admin.routes` (GET /api/v1/admin/users/search).

Phase 2.7. Target >=80% line coverage on `src/admin/routes.py`.

Endpoint surface (1 endpoint, gated on `require_admin_access`):
    GET /api/v1/admin/users/search?q=...&role=...&limit=20

Reality pins:
- The route uses `require_admin_access` (NOT `check_role(["admin"])`) — see
  audit B42 / `src/core/dependencies.py:95`. Both `admin` and `owner` roles
  pass; analyst/user are rejected with 403.
- The module captures `users = db["users"]` at IMPORT TIME (line 9). Tests
  MUST monkeypatch `src.admin.routes.users` to redirect to the per-test
  motor collection — same pattern as B16 (team_routes), B30 (redaction
  suggestion), B37 (share/contest/search). This is a NEW finding for
  audit Section 11 (B46).
- The search query requires `q` length >= 2 to add regex conditions. Single
  character or empty `q` falls through to the unfiltered `{"status":
  "active"}` query.
- `q` is escaped via `re.escape()` before being injected into the regex
  filter — prevents regex injection.
- Results project away `password_hash` and `password` fields.
- The `username` field in the response is derived from
  `email.split("@")[0]` — there's no actual `username` column on the user
  document. This is a Phase-1.9a artifact.
- `role` filter is lowercased before matching.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorDatabase

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_routes_db(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase):
    """Point `src.admin.routes.users` at the per-test motor collection.

    The module does `users = db["users"]` at import time, capturing a
    handle to the global blackbar-DB users collection. Without this
    rebind, route handlers operate on a stale collection and our
    seeded users are invisible.
    """
    import src.admin.routes as _routes_mod

    monkeypatch.setattr(_routes_mod, "users", db["users"])
    return db


async def _seed_user(
    db: AsyncIOMotorDatabase,
    *,
    user_id: str,
    email: str,
    name: str = "Test User",
    role: str = "user",
    status: str = "active",
) -> None:
    """Direct collection insert — bypasses UserCreate to avoid the
    bcrypt cost of password hashing for fixture rows."""
    await db.users.insert_one(
        {
            "id": user_id,
            "email": email,
            "name": name,
            "role": role,
            "status": status,
            "password_hash": "x" * 60,  # placeholder; never matched
        }
    )


# ---------------------------------------------------------------------------
# RBAC: admin role passes
# ---------------------------------------------------------------------------


class TestAdminAccess:
    async def test_admin_can_search_users(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_user(db, user_id="u1", email="alice@example.com", name="Alice")
        await _seed_user(db, user_id="u2", email="bob@example.com", name="Bob")

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/admin/users/search")
        assert r.status_code == 200, r.text
        body = r.json()
        # The factory itself seeded a user too — assert >=2 of our seeds present
        emails = {u["email"] for u in body["users"]}
        assert "alice@example.com" in emails
        assert "bob@example.com" in emails

    async def test_analyst_is_forbidden(self, authed_client_factory, patch_routes_db) -> None:
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get("/api/v1/admin/users/search")
        assert r.status_code == 403

    async def test_default_user_is_forbidden(self, authed_client_factory, patch_routes_db) -> None:
        client: AsyncClient = await authed_client_factory(role="user")
        r = await client.get("/api/v1/admin/users/search")
        assert r.status_code == 403

    async def test_unauthenticated_request_is_rejected(self, client) -> None:
        """No JWT -> AuthMiddleware returns 401 before reaching the route."""
        r = client.get("/api/v1/admin/users/search")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Search query parameter `q`
# ---------------------------------------------------------------------------


class TestSearchQuery:
    async def test_q_matches_email_substring(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_user(db, user_id="u-1", email="alice@example.com", name="Alice")
        await _seed_user(db, user_id="u-2", email="bob@example.com", name="Bob")

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/admin/users/search?q=alice")
        assert r.status_code == 200
        emails = {u["email"] for u in r.json()["users"]}
        assert "alice@example.com" in emails
        assert "bob@example.com" not in emails

    async def test_q_matches_name_substring(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_user(db, user_id="u-x", email="x@example.com", name="Zelda Ng")

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/admin/users/search?q=Zelda")
        body = r.json()
        names = {u["name"] for u in body["users"]}
        assert "Zelda Ng" in names

    async def test_q_under_2_chars_is_ignored(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """q=`a` (length 1) is silently dropped — handler returns all active
        users instead of filtering. Pins the `len(q) >= 2` guard."""
        await _seed_user(db, user_id="u-q1", email="alice@example.com", name="Alice")
        await _seed_user(db, user_id="u-q2", email="bob@example.com", name="Bob")

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/admin/users/search?q=a")
        assert r.status_code == 200
        # Both rows returned (plus the factory's admin row)
        emails = {u["email"] for u in r.json()["users"]}
        assert "alice@example.com" in emails
        assert "bob@example.com" in emails

    async def test_q_is_regex_escaped(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Reality pin: `re.escape(q)` neutralizes regex metacharacters
        like `.+*[]()`. A query of `.*` matches literally — not as a
        wildcard — so it shouldn't return every user."""
        await _seed_user(db, user_id="u-rx1", email="alice@example.com", name="A")
        await _seed_user(db, user_id="u-rx2", email="bob@example.com", name="B")

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/admin/users/search?q=.*")
        assert r.status_code == 200
        # Literal `.*` substring is not present in any seeded email/name
        emails = {u["email"] for u in r.json()["users"]}
        assert "alice@example.com" not in emails
        assert "bob@example.com" not in emails


# ---------------------------------------------------------------------------
# Role filter
# ---------------------------------------------------------------------------


class TestRoleFilter:
    async def test_role_filter_restricts_results(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_user(db, user_id="ana-1", email="ana@example.com", name="Ana", role="analyst")
        await _seed_user(db, user_id="usr-1", email="usr@example.com", name="Usr", role="user")

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/admin/users/search?role=analyst")
        assert r.status_code == 200
        roles = {u["role"] for u in r.json()["users"]}
        assert "analyst" in roles
        # No user-role rows allowed
        assert "user" not in roles

    async def test_role_filter_is_lowercased(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_user(db, user_id="ana-2", email="ana2@example.com", name="Ana", role="analyst")
        client: AsyncClient = await authed_client_factory(role="admin")
        # Case-insensitive role filter
        r = await client.get("/api/v1/admin/users/search?role=ANALYST")
        assert r.status_code == 200
        emails = {u["email"] for u in r.json()["users"]}
        assert "ana2@example.com" in emails


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------


class TestResponseShape:
    async def test_password_fields_never_returned(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_user(db, user_id="u-pw", email="pw@example.com", name="PW")

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/admin/users/search?q=pw")
        assert r.status_code == 200
        for user_record in r.json()["users"]:
            assert "password_hash" not in user_record
            assert "password" not in user_record

    async def test_username_derived_from_email_prefix(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Pins Phase-1.9a artifact: the `username` field in the response
        is `email.split('@')[0]`, not a real DB column."""
        await _seed_user(
            db,
            user_id="u-un",
            email="prefix.name@example.com",
            name="Prefix Name",
        )

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/admin/users/search?q=prefix")
        body = r.json()
        records = [u for u in body["users"] if u["email"] == "prefix.name@example.com"]
        assert records
        assert records[0]["username"] == "prefix.name"

    async def test_inactive_users_excluded(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """The base query pins `status=active`."""
        await _seed_user(db, user_id="u-inact", email="gone@example.com", status="deleted")

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/admin/users/search?q=gone")
        emails = {u["email"] for u in r.json()["users"]}
        assert "gone@example.com" not in emails

    async def test_limit_is_respected(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        for i in range(5):
            await _seed_user(db, user_id=f"bulk-{i}", email=f"u{i}@example.com", name=f"B{i}")

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/admin/users/search?limit=2")
        assert r.status_code == 200
        # Note: factory's admin user counts too; the limit applies to the cursor
        # returned by Mongo, capped at 2.
        assert len(r.json()["users"]) <= 2
