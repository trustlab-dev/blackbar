"""Tests for `src.llm.repository`.

Phase 2.6. Target >=80% line coverage on src.llm.repository.

Reality pins:
- `create()` strips the plaintext `api_key` from the model dump via
  `exclude={"api_key"}`, then stores `api_key_encrypted` via `encrypt_api_key`.
- `create()` stamps id, created_at, updated_at, created_by.
- `get_by_id()` pops the Mongo `_id` BSON ObjectId before instantiating LLMConfig.
- `list_all()` returns all configs by default; `enabled_only=True` filters to enabled.
- `update()` with no fields (all None) returns the existing config unchanged
  (early-return path).
- `update()` re-encrypts when `api_key` is provided in the update payload.
- `update()` returns None if Mongo's `modified_count` is 0 (no-op write).
- `delete()` returns True on success, False if no document was matched.
- `create_indexes()` creates three indexes: id (unique), name, enabled.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

from src.llm.encryption import decrypt_api_key
from src.llm.models import (
    LLMConfigCreate,
    LLMConfigUpdate,
    LLMSettings,
    RequestFormat,
)
from src.llm.repository import LLMRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_create_payload(
    *,
    name: str = "OpenAI Prod",
    enabled: bool = True,
    request_format: RequestFormat = RequestFormat.OPENAI,
    api_key: str = "sk-test-1234",
) -> LLMConfigCreate:
    return LLMConfigCreate(
        name=name,
        enabled=enabled,
        api_endpoint="https://api.openai.com/v1/chat/completions",
        model_name="gpt-4o-mini",
        request_format=request_format,
        api_key=api_key,
        default_settings=LLMSettings(),
    )


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


class TestCreate:
    async def test_create_stores_encrypted_key_and_metadata(self, db: AsyncIOMotorDatabase) -> None:
        repo = LLMRepository(db)
        payload = _make_create_payload(api_key="sk-real-key-9876")

        cfg = await repo.create(payload, created_by="admin-1")

        assert cfg.id  # UUID assigned
        assert cfg.name == "OpenAI Prod"
        assert cfg.created_by == "admin-1"
        assert cfg.created_at is not None
        assert cfg.updated_at is not None
        # Encrypted key is not the plaintext
        assert cfg.api_key_encrypted != "sk-real-key-9876"
        # But decrypts back to it
        assert decrypt_api_key(cfg.api_key_encrypted) == "sk-real-key-9876"

    async def test_create_does_not_persist_plaintext_api_key(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        """Audit guarantee: the `api_key` plaintext field must NOT be written
        to Mongo. Only `api_key_encrypted` is stored."""
        repo = LLMRepository(db)
        cfg = await repo.create(_make_create_payload(api_key="plaintext-secret"), "u")

        raw_doc = await db.llm_configs.find_one({"id": cfg.id})
        assert raw_doc is not None
        assert "api_key" not in raw_doc
        assert "api_key_encrypted" in raw_doc
        assert raw_doc["api_key_encrypted"] != "plaintext-secret"


# ---------------------------------------------------------------------------
# get_by_id
# ---------------------------------------------------------------------------


class TestGetById:
    async def test_returns_config_when_found(self, db: AsyncIOMotorDatabase) -> None:
        repo = LLMRepository(db)
        created = await repo.create(_make_create_payload(), "u")

        fetched = await repo.get_by_id(created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.name == created.name

    async def test_returns_none_when_missing(self, db: AsyncIOMotorDatabase) -> None:
        repo = LLMRepository(db)
        assert await repo.get_by_id("nonexistent-id") is None


# ---------------------------------------------------------------------------
# list_all
# ---------------------------------------------------------------------------


class TestListAll:
    async def test_lists_all_configs_when_no_filter(self, db: AsyncIOMotorDatabase) -> None:
        repo = LLMRepository(db)
        await repo.create(_make_create_payload(name="A", enabled=True), "u")
        await repo.create(_make_create_payload(name="B", enabled=False), "u")
        await repo.create(_make_create_payload(name="C", enabled=True), "u")

        results = await repo.list_all()
        assert {r.name for r in results} == {"A", "B", "C"}

    async def test_enabled_only_filters_disabled(self, db: AsyncIOMotorDatabase) -> None:
        repo = LLMRepository(db)
        await repo.create(_make_create_payload(name="ON", enabled=True), "u")
        await repo.create(_make_create_payload(name="OFF", enabled=False), "u")

        results = await repo.list_all(enabled_only=True)
        names = {r.name for r in results}
        assert names == {"ON"}

    async def test_empty_db_returns_empty_list(self, db: AsyncIOMotorDatabase) -> None:
        repo = LLMRepository(db)
        assert await repo.list_all() == []


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


class TestUpdate:
    async def test_update_modifies_existing_fields(self, db: AsyncIOMotorDatabase) -> None:
        repo = LLMRepository(db)
        cfg = await repo.create(_make_create_payload(name="Old"), "u")

        updated = await repo.update(cfg.id, LLMConfigUpdate(name="New", enabled=False))
        assert updated is not None
        assert updated.name == "New"
        assert updated.enabled is False

    async def test_update_with_no_fields_returns_existing(self, db: AsyncIOMotorDatabase) -> None:
        """All-None update payload triggers the early-return branch:
        `if not update_dict: return await self.get_by_id(config_id)`."""
        repo = LLMRepository(db)
        cfg = await repo.create(_make_create_payload(name="Stable"), "u")

        result = await repo.update(cfg.id, LLMConfigUpdate())
        assert result is not None
        assert result.id == cfg.id
        assert result.name == "Stable"

    async def test_update_api_key_reencrypts(self, db: AsyncIOMotorDatabase) -> None:
        repo = LLMRepository(db)
        cfg = await repo.create(_make_create_payload(api_key="old-key"), "u")
        old_encrypted = cfg.api_key_encrypted

        updated = await repo.update(cfg.id, LLMConfigUpdate(api_key="new-rotated-key"))

        assert updated is not None
        assert updated.api_key_encrypted != old_encrypted
        assert decrypt_api_key(updated.api_key_encrypted) == "new-rotated-key"

    async def test_update_missing_config_returns_none(self, db: AsyncIOMotorDatabase) -> None:
        """No matching document => modified_count is 0 => returns None."""
        repo = LLMRepository(db)
        result = await repo.update("nonexistent-id", LLMConfigUpdate(name="new"))
        assert result is None


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


class TestDelete:
    async def test_delete_returns_true_on_success(self, db: AsyncIOMotorDatabase) -> None:
        repo = LLMRepository(db)
        cfg = await repo.create(_make_create_payload(), "u")

        assert await repo.delete(cfg.id) is True
        assert await repo.get_by_id(cfg.id) is None

    async def test_delete_returns_false_when_missing(self, db: AsyncIOMotorDatabase) -> None:
        repo = LLMRepository(db)
        assert await repo.delete("nonexistent-id") is False


# ---------------------------------------------------------------------------
# create_indexes
# ---------------------------------------------------------------------------


class TestCreateIndexes:
    async def test_creates_three_indexes(self, db: AsyncIOMotorDatabase) -> None:
        repo = LLMRepository(db)
        await repo.create_indexes()

        indexes = await db.llm_configs.index_information()
        # Default `_id_` index plus our three (id, name, enabled)
        assert "_id_" in indexes
        # Each named index is prefixed by `<field>_<direction>` by default
        named = [k for k in indexes if k != "_id_"]
        # id is unique
        id_idx = [k for k in named if k.startswith("id_")]
        assert id_idx, f"expected an id_* index, got {named}"
        assert indexes[id_idx[0]].get("unique") is True

        assert any(k.startswith("name_") for k in named)
        assert any(k.startswith("enabled_") for k in named)
