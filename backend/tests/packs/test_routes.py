"""Integration tests for `src.packs.routes` (jurisdiction pack API).

Phase 2.8 Batch A. Target >=80% line coverage on `src/packs/routes.py`.

Endpoint surface (13 endpoints, mounted at /api/v1/packs/...):
    GET    /                            -> list_packs (with active flag)
    GET    /active                      -> get_active_pack_info
    GET    /active/categories           -> active categories list
    GET    /active/sections             -> exemption sections (+optional ?q)
    GET    /{pack_id}                   -> full pack data
    GET    /{pack_id}/summary           -> summary subset
    GET    /{pack_id}/preview           -> preview slice (no activation)
    POST   /activate?pack_id=...        -> set active pack (admin/owner)
    POST   /validate                    -> validate without saving
    POST   /upload                      -> upload custom pack file (admin/owner)
    POST   /reload                      -> reload from FS (admin/owner)
    GET    /search?q=...                -> search packs
    GET    /country/{country_code}      -> filter by country

Reality pins:
- Every endpoint requires JWT (packs are NOT in the AuthMiddleware
  public allowlist).
- Admin-gated endpoints (`/activate`, `/upload`, `/reload`) use
  `check_role(["owner", "admin"])` from `src.dependencies`. Both `admin`
  and `owner` pass; analyst/user get 403.
- The check_role decorator uses `Depends(get_current_user)` which reads
  `users = db["users"]` from `src.database` at import time — tests must
  monkeypatch `src.dependencies.users` to redirect to the per-test motor
  collection. Same class as B16/B30/B37/B46.
- `_packs_directory` is captured at module load. Tests redirect it (and
  zero `_pack_cache` / `_active_pack`) via a fixture so the route
  handlers see a tmp pack catalog.
- **NEW finding B48 (route registration order bug, same class as B12 /
  B33):** `GET /search` and `GET /country/{country_code}` are registered
  AFTER `GET /{pack_id}` in `packs/routes.py`. FastAPI matches in
  declaration order, so `/api/v1/packs/search` matches the `/{pack_id}`
  handler with `pack_id="search"` and returns 404 "Pack 'search' not
  found". The `/search` and `/country/{country_code}` handlers are
  effectively dead code via the public URL.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorDatabase

import src.packs.loader as loader_mod
import src.packs.routes as routes_mod

# ---------------------------------------------------------------------------
# Helpers + fixtures
# ---------------------------------------------------------------------------


def _make_pack(pack_id: str = "test-pack-v1", **overrides) -> dict:
    base = {
        "pack_id": pack_id,
        "name": f"Pack {pack_id}",
        "version": "1.0.0",
        "description": "A test pack",
        "jurisdiction": {
            "country": "CA",
            "region": "BC",
            "legislation": "FIPPA",
            "legislation_short": "FIPPA",
        },
        "terminology": {"requester": "applicant"},
        "timelines": {"default_response_days": 30},
        "statuses": [{"value": "open", "label": "Open", "color": "#00ff00"}],
        "priorities": [{"value": "normal", "label": "Normal"}],
        "redaction_categories": [
            {
                "id": "s22",
                "code": "S.22",
                "name": "Personal privacy",
                "description": "x",
                "color": "#0066cc",
                "subsections": [
                    {"code": "S.22(1)", "name": "Sub 1", "description": "y"},
                ],
            }
        ],
        "templates": {"ack": "Hello"},
        "features": {"public_portal": True},
        "branding": {"primary_color": "#000"},
        "ai_prompts": {"summarize": "Sum"},
    }
    base.update(overrides)
    return base


def _write_pack_file(directory: Path, filename: str, data: dict | str) -> Path:
    path = directory / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def packs_fs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect loader's `_packs_directory` to a tmp dir and zero state."""
    monkeypatch.setattr(loader_mod, "_packs_directory", tmp_path)
    monkeypatch.setattr(loader_mod, "_pack_cache", {})
    monkeypatch.setattr(loader_mod, "_active_pack", None)
    return tmp_path


@pytest.fixture
def patch_routes_db(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase):
    """Route handlers don't touch Mongo directly, but admin-gated routes pull
    `current_user` via `check_role`, which goes through
    `src.dependencies.get_current_user` -> `users.find_one(...)`. We rebind
    that module's `users` symbol to the per-test collection so user lookup
    succeeds.
    """
    import src.dependencies as deps_mod

    monkeypatch.setattr(deps_mod, "users", db.users)
    return db


def _anon_client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------


class TestListPacks:
    async def test_lists_packs_with_active_marker(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        _write_pack_file(packs_fs, "alpha.json", _make_pack("alpha"))
        _write_pack_file(packs_fs, "beta.json", _make_pack("beta"))
        loader_mod.set_active_pack("alpha")

        client = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/packs/")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "packs" in body
        assert body["active_pack_id"] == "alpha"
        active_flags = {p["pack_id"]: p["is_active"] for p in body["packs"]}
        assert active_flags["alpha"] is True
        assert active_flags["beta"] is False

    async def test_lists_empty_when_no_packs(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        client = await authed_client_factory(role="user")
        r = await client.get("/api/v1/packs/")
        assert r.status_code == 200
        body = r.json()
        assert body["packs"] == []
        assert body["active_pack_id"] is None

    async def test_unauth_rejected(self, packs_fs, app) -> None:
        async with _anon_client(app) as c:
            r = await c.get("/api/v1/packs/")
            assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /active
# ---------------------------------------------------------------------------


class TestGetActivePack:
    async def test_returns_active_pack_data(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        _write_pack_file(packs_fs, "alpha.json", _make_pack("alpha"))
        loader_mod.set_active_pack("alpha")

        client = await authed_client_factory(role="user")
        r = await client.get("/api/v1/packs/active")
        assert r.status_code == 200
        body = r.json()
        assert body["pack_id"] == "alpha"

    async def test_returns_404_when_no_active_pack(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        client = await authed_client_factory(role="user")
        r = await client.get("/api/v1/packs/active")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /active/categories
# ---------------------------------------------------------------------------


class TestGetActiveCategories:
    async def test_returns_categories(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        _write_pack_file(packs_fs, "alpha.json", _make_pack("alpha"))
        loader_mod.set_active_pack("alpha")

        client = await authed_client_factory(role="user")
        r = await client.get("/api/v1/packs/active/categories")
        assert r.status_code == 200
        body = r.json()
        assert body["pack_id"] == "alpha"
        assert len(body["categories"]) == 1
        assert body["categories"][0]["code"] == "S.22"

    async def test_404_when_no_active_pack(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        client = await authed_client_factory(role="user")
        r = await client.get("/api/v1/packs/active/categories")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /active/sections
# ---------------------------------------------------------------------------


class TestGetActiveSections:
    async def test_returns_sections_including_subsections(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        _write_pack_file(packs_fs, "alpha.json", _make_pack("alpha"))
        loader_mod.set_active_pack("alpha")

        client = await authed_client_factory(role="user")
        r = await client.get("/api/v1/packs/active/sections")
        assert r.status_code == 200
        body = r.json()
        # 1 category + 1 subsection
        assert body["count"] == 2
        codes = [s["code"] for s in body["sections"]]
        assert "S.22" in codes
        assert "S.22(1)" in codes

    async def test_filters_by_query(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        _write_pack_file(packs_fs, "alpha.json", _make_pack("alpha"))
        loader_mod.set_active_pack("alpha")

        client = await authed_client_factory(role="user")
        r = await client.get("/api/v1/packs/active/sections?q=22(1)")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1
        assert body["sections"][0]["code"] == "S.22(1)"

    async def test_404_when_no_active_pack(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        client = await authed_client_factory(role="user")
        r = await client.get("/api/v1/packs/active/sections")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /{pack_id} and friends
# ---------------------------------------------------------------------------


class TestGetPackDetails:
    async def test_returns_pack_data(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        _write_pack_file(packs_fs, "alpha.json", _make_pack("alpha"))

        client = await authed_client_factory(role="user")
        r = await client.get("/api/v1/packs/alpha")
        assert r.status_code == 200
        body = r.json()
        assert body["pack_id"] == "alpha"

    async def test_404_for_unknown_pack(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        client = await authed_client_factory(role="user")
        r = await client.get("/api/v1/packs/missing-pack")
        assert r.status_code == 404


class TestGetPackSummary:
    async def test_returns_summary(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        _write_pack_file(packs_fs, "alpha.json", _make_pack("alpha"))
        client = await authed_client_factory(role="user")
        r = await client.get("/api/v1/packs/alpha/summary")
        assert r.status_code == 200
        body = r.json()
        assert body["pack_id"] == "alpha"
        assert body["category_count"] == 1

    async def test_404_for_unknown(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        client = await authed_client_factory(role="user")
        r = await client.get("/api/v1/packs/missing/summary")
        assert r.status_code == 404


class TestPreviewPack:
    async def test_returns_preview_slice(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        _write_pack_file(packs_fs, "alpha.json", _make_pack("alpha"))
        client = await authed_client_factory(role="user")
        r = await client.get("/api/v1/packs/alpha/preview")
        assert r.status_code == 200
        body = r.json()
        assert body["pack_id"] == "alpha"
        # `templates` is the list of template keys, not values
        assert body["templates"] == ["ack"]

    async def test_404_for_unknown(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        client = await authed_client_factory(role="user")
        r = await client.get("/api/v1/packs/missing/preview")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /activate
# ---------------------------------------------------------------------------


class TestActivatePack:
    async def test_admin_can_activate(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        _write_pack_file(packs_fs, "alpha.json", _make_pack("alpha"))
        client = await authed_client_factory(role="admin")
        r = await client.post("/api/v1/packs/activate?pack_id=alpha")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["active_pack"] == "alpha"
        active = loader_mod.get_active_pack()
        assert active is not None
        assert active["pack_id"] == "alpha"

    async def test_owner_can_activate(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        _write_pack_file(packs_fs, "alpha.json", _make_pack("alpha"))
        client = await authed_client_factory(role="owner")
        r = await client.post("/api/v1/packs/activate?pack_id=alpha")
        assert r.status_code == 200

    async def test_404_for_unknown_pack(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.post("/api/v1/packs/activate?pack_id=missing")
        assert r.status_code == 404

    async def test_user_role_forbidden(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        client = await authed_client_factory(role="user")
        r = await client.post("/api/v1/packs/activate?pack_id=alpha")
        assert r.status_code == 403

    async def test_analyst_role_forbidden(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        client = await authed_client_factory(role="analyst")
        r = await client.post("/api/v1/packs/activate?pack_id=alpha")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# POST /validate
# ---------------------------------------------------------------------------


class TestValidatePack:
    async def test_validates_valid_pack(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        client = await authed_client_factory(role="user")
        r = await client.post("/api/v1/packs/validate", json=_make_pack("alpha"))
        assert r.status_code == 200
        body = r.json()
        assert body["valid"] is True

    async def test_invalid_pack_returns_errors(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        client = await authed_client_factory(role="user")
        r = await client.post("/api/v1/packs/validate", json={"pack_id": "x"})
        assert r.status_code == 200
        body = r.json()
        assert body["valid"] is False
        assert len(body["errors"]) > 0

    async def test_internal_exception_returns_payload(
        self,
        packs_fs: Path,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If validate_pack raises, the route returns a structured payload
        (not 500) with valid=False, errors=[str(e)]."""

        def _raise(_data: dict) -> dict:
            raise RuntimeError("boom")

        monkeypatch.setattr(routes_mod, "validate_pack", _raise)

        client = await authed_client_factory(role="user")
        r = await client.post("/api/v1/packs/validate", json=_make_pack("alpha"))
        assert r.status_code == 200
        body = r.json()
        assert body["valid"] is False
        assert body["errors"] == ["boom"]


# ---------------------------------------------------------------------------
# POST /upload
# ---------------------------------------------------------------------------


class TestUploadPack:
    async def test_admin_can_upload_valid_pack(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        pack = _make_pack("uploaded-v1")
        data = json.dumps(pack).encode()

        client = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/packs/upload",
            files={"file": ("uploaded.json", io.BytesIO(data), "application/json")},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["pack_id"] == "uploaded-v1"
        # File written to custom/ dir
        assert (packs_fs / "custom" / "uploaded-v1.json").exists()

    async def test_rejects_non_json_filename(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/packs/upload",
            files={"file": ("uploaded.txt", io.BytesIO(b"x"), "text/plain")},
        )
        assert r.status_code == 400

    async def test_rejects_invalid_json(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/packs/upload",
            files={"file": ("bad.json", io.BytesIO(b"{not json"), "application/json")},
        )
        assert r.status_code == 400

    async def test_validation_failure_returns_payload(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        client = await authed_client_factory(role="admin")
        # Missing required fields => validation fails
        bad = {"pack_id": "x"}
        r = await client.post(
            "/api/v1/packs/upload",
            files={"file": ("x.json", io.BytesIO(json.dumps(bad).encode()), "application/json")},
        )
        # 200 with success=False (validation failure, not HTTP error)
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is False
        assert len(body["errors"]) > 0

    async def test_user_role_forbidden(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        client = await authed_client_factory(role="user")
        r = await client.post(
            "/api/v1/packs/upload",
            files={"file": ("x.json", io.BytesIO(b"{}"), "application/json")},
        )
        assert r.status_code == 403

    async def test_internal_exception_returns_500(
        self,
        packs_fs: Path,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If something blows up inside the upload handler past validation,
        it surfaces as 500."""

        # Make `validate_pack` succeed, then make `open` writing the file
        # raise an unexpected error to hit the broad except branch.
        real_open = open

        def explode_open(path, *args, **kwargs):
            if "custom" in str(path) and str(path).endswith(".json"):
                raise OSError("disk full")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr("builtins.open", explode_open)

        client = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/packs/upload",
            files={
                "file": (
                    "uploaded.json",
                    io.BytesIO(json.dumps(_make_pack("u1")).encode()),
                    "application/json",
                )
            },
        )
        assert r.status_code == 500


# ---------------------------------------------------------------------------
# POST /reload
# ---------------------------------------------------------------------------


class TestReloadPacks:
    async def test_admin_can_reload(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        _write_pack_file(packs_fs, "a.json", _make_pack("a"))
        client = await authed_client_factory(role="admin")
        r = await client.post("/api/v1/packs/reload")
        assert r.status_code == 200
        body = r.json()
        assert body["pack_count"] == 1

    async def test_user_role_forbidden(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        client = await authed_client_factory(role="user")
        r = await client.post("/api/v1/packs/reload")
        assert r.status_code == 403

    async def test_internal_exception_returns_500(
        self,
        packs_fs: Path,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _raise() -> None:
            raise RuntimeError("nope")

        monkeypatch.setattr(routes_mod, "reload_packs", _raise)
        client = await authed_client_factory(role="admin")
        r = await client.post("/api/v1/packs/reload")
        assert r.status_code == 500


# ---------------------------------------------------------------------------
# GET /search — NEW FINDING B48 (route order bug, dead-code endpoint)
# ---------------------------------------------------------------------------


class TestSearchPacksRouteOrder:
    async def test_search_url_resolves_to_search_handler(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        """Phase 4 Batch 4.4 (audit B48): `GET /api/v1/packs/search?q=...`
        is now registered BEFORE the `/{pack_id}` catch-all, so FastAPI's
        first-match rule resolves it to the search handler. Test flipped
        from the prior "shadowed by /{pack_id}" characterization."""
        _write_pack_file(packs_fs, "alpha.json", _make_pack("alpha", name="Alpha pack"))
        client = await authed_client_factory(role="user")
        r = await client.get("/api/v1/packs/search?q=alpha")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["query"] == "alpha"
        assert body["count"] == 1

    async def test_search_handler_works_via_direct_call(self, packs_fs: Path) -> None:
        """Direct-call test retained for coverage of the handler body
        when called outside the HTTP stack."""
        _write_pack_file(packs_fs, "alpha.json", _make_pack("alpha", name="Alpha pack"))

        result = await routes_mod.search_packs(q="alpha")
        assert result["query"] == "alpha"
        assert result["count"] == 1

    async def test_search_handler_exception_returns_500_when_called_directly(
        self, packs_fs: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastapi import HTTPException

        from src.packs.registry import PackRegistry

        def _raise(_q: str) -> list:
            raise RuntimeError("boom")

        monkeypatch.setattr(PackRegistry, "search_packs", staticmethod(_raise))

        with pytest.raises(HTTPException) as exc:
            await routes_mod.search_packs(q="x")
        assert exc.value.status_code == 500


# ---------------------------------------------------------------------------
# GET /country/{country_code}
# ---------------------------------------------------------------------------


class TestPacksByCountry:
    async def test_returns_packs_for_country(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        """`/country/{country_code}` is two segments — not shadowed by the
        single-segment `/{pack_id}` route, so the URL is reachable."""
        _write_pack_file(
            packs_fs,
            "a.json",
            _make_pack("a", jurisdiction={"country": "CA", "region": "BC", "legislation": "FIPPA"}),
        )
        _write_pack_file(
            packs_fs,
            "b.json",
            _make_pack("b", jurisdiction={"country": "US", "region": "NY", "legislation": "FOIL"}),
        )

        client = await authed_client_factory(role="user")
        r = await client.get("/api/v1/packs/country/CA")
        assert r.status_code == 200
        body = r.json()
        assert body["country"] == "CA"
        assert body["count"] == 1

    async def test_returns_empty_for_unknown_country(
        self, packs_fs: Path, authed_client_factory, patch_routes_db
    ) -> None:
        client = await authed_client_factory(role="user")
        r = await client.get("/api/v1/packs/country/ZZ")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 0

    async def test_internal_exception_returns_500(
        self,
        packs_fs: Path,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from src.packs.registry import PackRegistry

        def _raise(_cc: str) -> list:
            raise RuntimeError("boom")

        monkeypatch.setattr(PackRegistry, "get_packs_by_country", staticmethod(_raise))

        client = await authed_client_factory(role="user")
        r = await client.get("/api/v1/packs/country/CA")
        assert r.status_code == 500


# ---------------------------------------------------------------------------
# Coverage edge: GET / handler internal exception
# ---------------------------------------------------------------------------


class TestListPacksException:
    async def test_internal_exception_returns_500(
        self,
        packs_fs: Path,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from src.packs.registry import PackRegistry

        def _raise() -> list:
            raise RuntimeError("boom")

        monkeypatch.setattr(PackRegistry, "list_packs", staticmethod(_raise))
        client = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/packs/")
        assert r.status_code == 500
