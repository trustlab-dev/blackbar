"""Integration tests for `src.cases.release_routes` endpoints.

Phase 2.2.C (3/5). Target >=80% line coverage on src.cases.release_routes.

Endpoints under test (all mounted at /api/v1/cases/...):
    POST   /{case_id}/release-package/generate
    GET    /{case_id}/release-packages
    GET    /{case_id}/release-package/{package_id}
    GET    /{case_id}/release-package/{package_id}/download
    POST   /{case_id}/release-package/{package_id}/release
    DELETE /{case_id}/release-package/{package_id}

These tests focus on the ROUTE LAYER — service-layer logic is covered
separately in tests/cases/test_release_package_service.py. We stub
out heavy service calls (`process_package_generation`,
`download_draft_package`'s GridFS read) and exercise the HTTP-shape
side: status codes, response envelope, role gating, audit log writes.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.cases.release_package_models import ReleasePackageDB, ReleasePackageStatus
from tests.factories import make_case

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_routes_db(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase, app):
    import src.database as db_mod
    import src.dependencies as deps_mod
    from src.cases import release_routes
    from src.cases import routes as cases_routes

    async def _override_get_db():
        return db

    app.dependency_overrides[release_routes.get_db] = _override_get_db
    app.dependency_overrides[cases_routes.get_db] = _override_get_db
    monkeypatch.setattr(deps_mod, "users", db.users)
    monkeypatch.setattr(db_mod, "users", db.users)

    yield db

    app.dependency_overrides.pop(release_routes.get_db, None)
    app.dependency_overrides.pop(cases_routes.get_db, None)


async def _seed_case_id(db: AsyncIOMotorDatabase, **overrides) -> str:
    doc = make_case(**overrides)
    await db.cases.insert_one(doc)
    return doc["id"]


def _make_package_doc(
    case_id: str,
    status: ReleasePackageStatus = ReleasePackageStatus.DRAFT,
    **overrides,
) -> dict:
    pkg = ReleasePackageDB(
        id=str(uuid.uuid4()),
        case_id=case_id,
        filename="rel.zip",
        access_token="acc-" + uuid.uuid4().hex[:8],
        created_at=datetime.utcnow(),
        created_by="creator",
        created_by_name="Creator",
        status=status,
        size_bytes=100,
        document_count=1,
    )
    doc = pkg.model_dump()
    doc.update(overrides)
    return doc


# ---------------------------------------------------------------------------
# POST /{case_id}/release-package/generate
# ---------------------------------------------------------------------------


class TestGenerateReleasePackage:
    async def test_admin_can_start_generation(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        case_id = await _seed_case_id(db)

        # Stub the background processing function — we only care about
        # the HTTP response of start_package_generation.
        from src.cases import release_package_service as rps_mod

        async def _stub_process(*args, **kwargs):
            return None

        monkeypatch.setattr(rps_mod, "process_package_generation", _stub_process)

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            f"/api/v1/cases/{case_id}/release-package/generate",
            json={"include_cover_letter": True},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "package_id" in body
        assert body["status"] == ReleasePackageStatus.GENERATING.value

        # Audit log entry was added
        case = await db.cases.find_one({"id": case_id})
        assert any(
            e.get("action") == "release_package_generation_started"
            for e in case.get("audit_log", [])
        )

    async def test_generate_missing_case_returns_400(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """The service raises ValueError('Case not found'); the route
        wraps that in HTTP 400 (per its except ValueError block)."""
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post("/api/v1/cases/ghost-id/release-package/generate", json={})
        assert r.status_code == 400

    async def test_user_role_cannot_generate(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case_id(db)
        client: AsyncClient = await authed_client_factory(role="user")
        r = await client.post(f"/api/v1/cases/{case_id}/release-package/generate", json={})
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# GET /{case_id}/release-packages — current state
# ---------------------------------------------------------------------------


class TestGetReleasePackagesState:
    async def test_returns_current_state_with_draft(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case_id(db)
        draft = _make_package_doc(case_id, ReleasePackageStatus.DRAFT)
        await db.release_packages.insert_one(draft)

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get(f"/api/v1/cases/{case_id}/release-packages")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["current_draft"] is not None
        assert body["current_draft"]["id"] == draft["id"]
        assert body["current_release"] is None

    async def test_returns_current_state_with_release(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case_id(db)
        released = _make_package_doc(case_id, ReleasePackageStatus.RELEASED)
        await db.release_packages.insert_one(released)

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get(f"/api/v1/cases/{case_id}/release-packages")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["current_release"] is not None
        assert body["current_release"]["id"] == released["id"]
        # download_url / public_url populated only when RELEASED
        assert body["current_release"]["download_url"] is not None

    async def test_packages_state_user_role_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case_id(db)
        client: AsyncClient = await authed_client_factory(role="user")
        r = await client.get(f"/api/v1/cases/{case_id}/release-packages")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# GET /{case_id}/release-package/{package_id}
# ---------------------------------------------------------------------------


class TestGetReleasePackage:
    async def test_get_package_happy_path(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case_id(db)
        pkg = _make_package_doc(case_id)
        await db.release_packages.insert_one(pkg)

        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get(f"/api/v1/cases/{case_id}/release-package/{pkg['id']}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["id"] == pkg["id"]
        assert body["case_id"] == case_id

    async def test_get_package_unknown_id_404(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case_id(db)
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get(f"/api/v1/cases/{case_id}/release-package/no-such-id")
        assert r.status_code == 404

    async def test_get_package_wrong_case_id_404(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Pin the `package.case_id != case_id` guard."""
        case_id = await _seed_case_id(db)
        other_case_id = await _seed_case_id(db)
        pkg = _make_package_doc(case_id)
        await db.release_packages.insert_one(pkg)

        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get(f"/api/v1/cases/{other_case_id}/release-package/{pkg['id']}")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /{case_id}/release-package/{package_id}/download
# ---------------------------------------------------------------------------


class TestDownloadPackage:
    async def test_download_generating_package_returns_400(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case_id(db)
        pkg = _make_package_doc(case_id, ReleasePackageStatus.GENERATING)
        await db.release_packages.insert_one(pkg)

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get(f"/api/v1/cases/{case_id}/release-package/{pkg['id']}/download")
        assert r.status_code == 400
        assert "still generating" in r.json()["error"]["message"]

    async def test_download_revoked_package_returns_400(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Pin the `status not in [DRAFT, RELEASED]` guard."""
        case_id = await _seed_case_id(db)
        pkg = _make_package_doc(case_id, ReleasePackageStatus.REVOKED)
        await db.release_packages.insert_one(pkg)

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get(f"/api/v1/cases/{case_id}/release-package/{pkg['id']}/download")
        assert r.status_code == 400

    async def test_download_happy_path(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        case_id = await _seed_case_id(db)
        pkg = _make_package_doc(case_id, ReleasePackageStatus.DRAFT)
        await db.release_packages.insert_one(pkg)

        # Stub download_draft_package to avoid GridFS
        from src.cases import release_package_service as rps_mod

        async def _stub_dl(package, db, downloaded_by=None, **kw):
            return b"FAKE_ZIP_BYTES", "fake-DRAFT.zip"

        monkeypatch.setattr(rps_mod, "download_draft_package", _stub_dl)

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get(f"/api/v1/cases/{case_id}/release-package/{pkg['id']}/download")
        assert r.status_code == 200, r.text
        assert r.content == b"FAKE_ZIP_BYTES"
        assert r.headers["content-type"] == "application/zip"
        assert 'filename="fake-DRAFT.zip"' in r.headers["content-disposition"]

    async def test_download_missing_package_returns_404(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case_id(db)
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get(f"/api/v1/cases/{case_id}/release-package/ghost/download")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /{case_id}/release-package/{package_id}/release
# ---------------------------------------------------------------------------


class TestReleasePackage:
    async def test_release_happy_path(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case_id(db)
        pkg = _make_package_doc(case_id, ReleasePackageStatus.DRAFT)
        await db.release_packages.insert_one(pkg)

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            f"/api/v1/cases/{case_id}/release-package/{pkg['id']}/release",
            json={"notify_requester": False},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == ReleasePackageStatus.RELEASED.value
        assert body["id"] == pkg["id"]
        assert body["public_url"].startswith("/api/v1/cases/public/release/")

        # Verify audit log
        case = await db.cases.find_one({"id": case_id})
        assert any(e.get("action") == "release_package_released" for e in case.get("audit_log", []))

    async def test_double_release_returns_400(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """A package that is already RELEASED cannot be released again
        (service raises ValueError on non-DRAFT status, route wraps
        in 400)."""
        case_id = await _seed_case_id(db)
        pkg = _make_package_doc(case_id, ReleasePackageStatus.RELEASED)
        await db.release_packages.insert_one(pkg)

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            f"/api/v1/cases/{case_id}/release-package/{pkg['id']}/release",
            json={},
        )
        assert r.status_code == 400
        assert "draft" in r.json()["error"]["message"].lower()

    async def test_release_missing_package_404(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case_id(db)
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            f"/api/v1/cases/{case_id}/release-package/ghost/release",
            json={},
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /{case_id}/release-package/{package_id}
# ---------------------------------------------------------------------------


class TestRevokeReleasePackage:
    async def test_admin_can_revoke(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case_id(db)
        pkg = _make_package_doc(case_id, ReleasePackageStatus.RELEASED)
        await db.release_packages.insert_one(pkg)

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.delete(f"/api/v1/cases/{case_id}/release-package/{pkg['id']}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "revoked"

        # Verify audit log
        case = await db.cases.find_one({"id": case_id})
        assert any(e.get("action") == "release_package_revoked" for e in case.get("audit_log", []))

    async def test_revoke_missing_package_404(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        case_id = await _seed_case_id(db)
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.delete(f"/api/v1/cases/{case_id}/release-package/ghost")
        assert r.status_code == 404

    async def test_analyst_cannot_revoke(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Revoke is gated to owner/admin only (not analyst)."""
        case_id = await _seed_case_id(db)
        pkg = _make_package_doc(case_id, ReleasePackageStatus.RELEASED)
        await db.release_packages.insert_one(pkg)

        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.delete(f"/api/v1/cases/{case_id}/release-package/{pkg['id']}")
        assert r.status_code == 403
