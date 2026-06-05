"""Tests for `src.core.database` — Motor connection helpers + index creation.

Covers all public functions:
- `get_mongodb_client()` — caches a singleton; idempotent
- `get_shared_database()` — returns the blackbar database handle
- `get_database()` — thin wrapper over get_shared_database
- `get_database_from_request(request)` — FastAPI dependency wrapper
- `create_indexes(db)` — runs all index creation calls idempotently

Strategy: use the per-test `db` fixture (real testcontainer Mongo) for
end-to-end index creation. The singleton-cache test resets the module's
`_client` to None to exercise the "create new" branch deterministically.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

# ---------------------------------------------------------------------------
# Module-level helpers (singleton + accessors)
# ---------------------------------------------------------------------------


class TestModuleAccessors:
    def test_get_mongodb_client_caches_singleton(
        self, monkeypatch: pytest.MonkeyPatch, mongo_uri: str
    ):
        """First call creates and caches the client; subsequent calls return
        the same instance. Pin both branches of the `if _client is None`."""
        from src.core import database as db_mod

        # Force cold-start so we exercise the creation branch.
        monkeypatch.setattr(db_mod, "_client", None)

        first = db_mod.get_mongodb_client()
        assert isinstance(first, AsyncIOMotorClient)

        # Second call returns the SAME object (skips creation).
        second = db_mod.get_mongodb_client()
        assert first is second

    def test_get_shared_database_returns_blackbar_handle(
        self, monkeypatch: pytest.MonkeyPatch, mongo_uri: str
    ):
        from src.core import database as db_mod

        monkeypatch.setattr(db_mod, "_client", None)
        database = db_mod.get_shared_database()
        assert isinstance(database, AsyncIOMotorDatabase)
        # Source hardcodes the DB name to "blackbar" (B17 in audit).
        assert database.name == "blackbar"

    def test_get_database_aliases_shared_database(
        self, monkeypatch: pytest.MonkeyPatch, mongo_uri: str
    ):
        from src.core import database as db_mod

        monkeypatch.setattr(db_mod, "_client", None)
        a = db_mod.get_database()
        b = db_mod.get_shared_database()
        assert a.name == b.name == "blackbar"


# ---------------------------------------------------------------------------
# get_database_from_request — FastAPI dependency wrapper
# ---------------------------------------------------------------------------


class TestGetDatabaseFromRequest:
    async def test_returns_blackbar_database(self, monkeypatch: pytest.MonkeyPatch, mongo_uri: str):
        from src.core import database as db_mod

        monkeypatch.setattr(db_mod, "_client", None)
        # Request body is not used by the dependency; pass a stub.
        request_stub = SimpleNamespace()
        result = await db_mod.get_database_from_request(request_stub)
        assert isinstance(result, AsyncIOMotorDatabase)
        assert result.name == "blackbar"


# ---------------------------------------------------------------------------
# create_indexes — runs against the per-test Mongo (testcontainer)
# ---------------------------------------------------------------------------


class TestCreateIndexes:
    async def test_creates_expected_indexes_on_collections(self, db: AsyncIOMotorDatabase):
        """End-to-end: pass the live per-test DB and verify the index map."""
        from src.core.database import create_indexes

        await create_indexes(db)

        # cases: id (unique), tracking_number (unique), status, created_at, compound
        cases_indexes = await db.cases.index_information()
        assert "id_1" in cases_indexes
        assert cases_indexes["id_1"].get("unique") is True
        assert "tracking_number_1" in cases_indexes
        assert cases_indexes["tracking_number_1"].get("unique") is True
        assert "status_1" in cases_indexes
        assert "created_at_1" in cases_indexes
        assert "status_1_created_at_-1" in cases_indexes

        # documents
        docs_indexes = await db.documents.index_information()
        assert "id_1" in docs_indexes
        assert docs_indexes["id_1"].get("unique") is True
        assert "case_id_1" in docs_indexes
        assert "file_hash_1" in docs_indexes
        assert "is_duplicate_1" in docs_indexes
        assert "case_id_1_is_duplicate_1" in docs_indexes
        assert "case_id_1_file_hash_1" in docs_indexes

        # templates
        templates_indexes = await db.templates.index_information()
        assert "id_1" in templates_indexes
        assert templates_indexes["id_1"].get("unique") is True
        assert "category_1" in templates_indexes
        assert "is_active_1" in templates_indexes

    async def test_create_indexes_is_idempotent(self, db: AsyncIOMotorDatabase):
        """Run twice — second call must not crash (Mongo accepts identical
        index specs as a no-op)."""
        from src.core.database import create_indexes

        await create_indexes(db)
        await create_indexes(db)  # should not raise

        # Indexes still there with same shape.
        cases_indexes = await db.cases.index_information()
        assert "id_1" in cases_indexes

    async def test_create_indexes_default_db_uses_shared(
        self, monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase
    ):
        """When `db=None`, create_indexes falls back to get_shared_database().
        Monkeypatch get_shared_database to return the per-test DB so we don't
        pollute the real 'blackbar' database with test indexes."""
        from src.core import database as db_mod

        monkeypatch.setattr(db_mod, "get_shared_database", lambda: db)
        await db_mod.create_indexes()  # default db=None branch

        # Verify by checking a known index landed on the test DB.
        cases_indexes = await db.cases.index_information()
        assert "id_1" in cases_indexes
