"""Integration tests for `src.categories.routes` (redaction categories proxy).

Phase 2.8 Batch B. Target >=80% line coverage on `src/categories/routes.py`.

Endpoint surface (1 endpoint, mounted at /api/v1/categories):
    GET    /                            -> categories from active pack

Reality pins:
- Mounted at `/api/v1/categories` (singular path), trailing slash matters
  (FastAPI returns 307 redirect from `/categories` to `/categories/`).
- Requires JWT (not in public allowlist).
- Reshapes pack `redaction_categories` entries to the legacy frontend
  shape: `id` = `code` (backwards compat), explicit keys for code, name,
  description, section, color, legal_reference, guidance.
- When no active pack is set AND no `bc-fippa-v1` default is on disk,
  `get_pack_categories()` returns `[]` and the response is `{"categories": []}`.
- Each entry in the response uses `.get(...)` defaults — None when source
  category is missing the field.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

import src.packs.loader as loader_mod

# ---------------------------------------------------------------------------
# Helpers + fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def packs_fs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect loader directory + zero state."""
    monkeypatch.setattr(loader_mod, "_packs_directory", tmp_path)
    monkeypatch.setattr(loader_mod, "_pack_cache", {})
    monkeypatch.setattr(loader_mod, "_active_pack", None)
    return tmp_path


@pytest.fixture
def patch_routes_db(monkeypatch: pytest.MonkeyPatch, db):
    """Rebind `src.dependencies.users` so `get_current_user` resolves the
    seed user against the per-test database."""
    import src.dependencies as deps_mod

    monkeypatch.setattr(deps_mod, "users", db.users)
    return db


def _anon_client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


def _set_active(category_dicts: list) -> None:
    """Manually set the loader's active pack to a synthetic pack with the
    given categories."""
    loader_mod._active_pack = {
        "pack_id": "test",
        "redaction_categories": category_dicts,
    }


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------


class TestGetCategories:
    async def test_returns_categories_in_legacy_shape(
        self, packs_fs, authed_client_factory, patch_routes_db
    ) -> None:
        _set_active(
            [
                {
                    "code": "S.22",
                    "name": "Personal privacy",
                    "description": "PII",
                    "section": "22",
                    "color": "#0066cc",
                    "legal_reference": "FIPPA s.22",
                    "guidance": "Apply broadly",
                },
                {
                    "code": "S.13",
                    "name": "Policy advice",
                    "description": "advice",
                },
            ]
        )

        client = await authed_client_factory(role="user")
        r = await client.get("/api/v1/categories/")
        assert r.status_code == 200
        body = r.json()
        cats = body["categories"]
        assert len(cats) == 2
        first = cats[0]
        # Legacy shape: id == code
        assert first["id"] == "S.22"
        assert first["code"] == "S.22"
        assert first["name"] == "Personal privacy"
        assert first["description"] == "PII"
        assert first["color"] == "#0066cc"
        assert first["legal_reference"] == "FIPPA s.22"
        assert first["guidance"] == "Apply broadly"

    async def test_missing_optional_fields_become_none(
        self, packs_fs, authed_client_factory, patch_routes_db
    ) -> None:
        _set_active([{"code": "X", "name": "X"}])
        client = await authed_client_factory(role="user")
        r = await client.get("/api/v1/categories/")
        assert r.status_code == 200
        cat = r.json()["categories"][0]
        assert cat["section"] is None
        assert cat["color"] is None
        assert cat["legal_reference"] is None
        assert cat["guidance"] is None
        assert cat["description"] is None

    async def test_no_active_pack_returns_empty(
        self, packs_fs, authed_client_factory, patch_routes_db
    ) -> None:
        # `_active_pack` is None and `bc-fippa-v1` not on disk
        client = await authed_client_factory(role="user")
        r = await client.get("/api/v1/categories/")
        assert r.status_code == 200
        assert r.json() == {"categories": []}

    async def test_unauthenticated_rejected(self, packs_fs, app) -> None:
        async with _anon_client(app) as c:
            r = await c.get("/api/v1/categories/")
            assert r.status_code == 401

    async def test_admin_allowed(self, packs_fs, authed_client_factory, patch_routes_db) -> None:
        _set_active([{"code": "X", "name": "X"}])
        client = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/categories/")
        assert r.status_code == 200

    async def test_analyst_allowed(self, packs_fs, authed_client_factory, patch_routes_db) -> None:
        _set_active([{"code": "X", "name": "X"}])
        client = await authed_client_factory(role="analyst")
        r = await client.get("/api/v1/categories/")
        assert r.status_code == 200
