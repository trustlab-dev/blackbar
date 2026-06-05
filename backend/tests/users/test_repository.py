"""Integration tests for `src.users.repository.UsersRepository`.

Phase 2.8 Batch C. Target >=80% line coverage on `src/users/repository.py`.

Surface covered:
- `create(user_data, password_hash)` — generates UUID id, stores
  password_hash separately from UserCreate's `password` (excluded), sets
  `external_id=None`, `created_at`/`updated_at`.
- `get_by_id(user_id)` — drops `_id`, returns User model or None.
- `get_by_email(email)` — case-insensitive regex match with `re.escape`
  on the query, returns User or None.
- `get_by_external_id(external_id)` — exact match, returns User or None.
- `list_all(skip, limit)` — paginated list. Drops `_id` per result.
- `update(user_id, update_data, password_hash)` — drops `password` from
  UserUpdate, optionally sets `password_hash`. Returns None for no-op
  modifications and Falls through to `get_by_id` when update_dict is empty.
- `delete(user_id)` — returns True iff delete_count > 0.
- `create_indexes()` — idempotent, creates 4 indexes.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

from src.users.models import UserCreate, UserUpdate
from src.users.repository import UsersRepository

# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


class TestCreate:
    async def test_creates_user_with_uuid(self, db: AsyncIOMotorDatabase) -> None:
        repo = UsersRepository(db)
        user = await repo.create(
            UserCreate(email="alice@example.com", name="Alice", password="x"),
            password_hash="hashed-x",
        )
        assert user.id  # auto-generated UUID
        assert user.email == "alice@example.com"
        assert user.name == "Alice"
        assert user.password_hash == "hashed-x"
        assert user.external_id is None
        assert user.created_at is not None
        assert user.updated_at is not None

    async def test_password_excluded_from_storage(self, db: AsyncIOMotorDatabase) -> None:
        """The raw `password` field on UserCreate must NOT make it into the
        Mongo doc — only password_hash."""
        repo = UsersRepository(db)
        await repo.create(
            UserCreate(email="bob@example.com", name="Bob", password="raw-password"),
            password_hash="hashed-bob",
        )
        doc = await db.users.find_one({"email": "bob@example.com"})
        assert doc is not None
        assert "password" not in doc
        assert doc["password_hash"] == "hashed-bob"

    async def test_email_normalized_lowercase(self, db: AsyncIOMotorDatabase) -> None:
        repo = UsersRepository(db)
        user = await repo.create(
            UserCreate(email="Alice@Example.COM", name="A", password="x"),
            password_hash="h",
        )
        assert user.email == "alice@example.com"


# ---------------------------------------------------------------------------
# get_by_id
# ---------------------------------------------------------------------------


class TestGetById:
    async def test_finds_existing_user(self, db: AsyncIOMotorDatabase) -> None:
        repo = UsersRepository(db)
        created = await repo.create(
            UserCreate(email="x@example.com", name="X", password="p"),
            password_hash="h",
        )
        found = await repo.get_by_id(created.id)
        assert found is not None
        assert found.email == "x@example.com"

    async def test_returns_none_for_missing(self, db: AsyncIOMotorDatabase) -> None:
        repo = UsersRepository(db)
        assert await repo.get_by_id("nonexistent-id") is None

    async def test_drops_mongo_object_id(self, db: AsyncIOMotorDatabase) -> None:
        """Internal `_id` MUST NOT leak into the User model (which has no
        `_id` field — Pydantic would error)."""
        repo = UsersRepository(db)
        created = await repo.create(
            UserCreate(email="x@example.com", name="X", password="p"),
            password_hash="h",
        )
        user = await repo.get_by_id(created.id)
        # If `_id` had leaked, .id would be an ObjectId and we'd see
        # validation errors above. Sanity-check the field shape.
        assert user is not None
        assert user.id == created.id


# ---------------------------------------------------------------------------
# get_by_email
# ---------------------------------------------------------------------------


class TestGetByEmail:
    async def test_case_insensitive_match(self, db: AsyncIOMotorDatabase) -> None:
        repo = UsersRepository(db)
        await repo.create(
            UserCreate(email="alice@example.com", name="A", password="p"),
            password_hash="h",
        )
        # email normalization writes lowercase; lookup tries case-insensitive
        found = await repo.get_by_email("ALICE@EXAMPLE.COM")
        assert found is not None
        assert found.email == "alice@example.com"

    async def test_returns_none_for_unknown(self, db: AsyncIOMotorDatabase) -> None:
        repo = UsersRepository(db)
        assert await repo.get_by_email("nobody@example.com") is None

    async def test_regex_special_chars_escaped(self, db: AsyncIOMotorDatabase) -> None:
        """`re.escape` on the query prevents the literal `+` in
        `alice+tag@example.com` from being treated as a regex quantifier."""
        repo = UsersRepository(db)
        await repo.create(
            UserCreate(email="alice+tag@example.com", name="A", password="p"),
            password_hash="h",
        )
        found = await repo.get_by_email("alice+tag@example.com")
        assert found is not None


# ---------------------------------------------------------------------------
# get_by_external_id
# ---------------------------------------------------------------------------


class TestGetByExternalId:
    async def test_returns_user(self, db: AsyncIOMotorDatabase) -> None:
        repo = UsersRepository(db)
        created = await repo.create(
            UserCreate(email="a@example.com", name="A", password="p"),
            password_hash="h",
        )
        # Patch external_id after creation
        await db.users.update_one({"id": created.id}, {"$set": {"external_id": "ext-123"}})
        found = await repo.get_by_external_id("ext-123")
        assert found is not None
        assert found.id == created.id

    async def test_returns_none_when_missing(self, db: AsyncIOMotorDatabase) -> None:
        repo = UsersRepository(db)
        assert await repo.get_by_external_id("none") is None


# ---------------------------------------------------------------------------
# list_all
# ---------------------------------------------------------------------------


class TestListAll:
    async def test_returns_all_users(self, db: AsyncIOMotorDatabase) -> None:
        repo = UsersRepository(db)
        for i in range(3):
            await repo.create(
                UserCreate(email=f"u{i}@example.com", name=f"U{i}", password="p"),
                password_hash="h",
            )
        users = await repo.list_all()
        assert len(users) == 3

    async def test_pagination(self, db: AsyncIOMotorDatabase) -> None:
        repo = UsersRepository(db)
        for i in range(5):
            await repo.create(
                UserCreate(email=f"u{i}@example.com", name=f"U{i}", password="p"),
                password_hash="h",
            )
        page = await repo.list_all(skip=2, limit=2)
        assert len(page) == 2

    async def test_empty_when_no_users(self, db: AsyncIOMotorDatabase) -> None:
        repo = UsersRepository(db)
        users = await repo.list_all()
        assert users == []


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


class TestUpdate:
    async def test_updates_name(self, db: AsyncIOMotorDatabase) -> None:
        repo = UsersRepository(db)
        u = await repo.create(
            UserCreate(email="a@example.com", name="Old", password="p"),
            password_hash="h",
        )
        updated = await repo.update(u.id, UserUpdate(name="New"))
        assert updated is not None
        assert updated.name == "New"

    async def test_password_hash_optional_param_applied(self, db: AsyncIOMotorDatabase) -> None:
        repo = UsersRepository(db)
        u = await repo.create(
            UserCreate(email="a@example.com", name="A", password="p"),
            password_hash="old-h",
        )
        updated = await repo.update(u.id, UserUpdate(), password_hash="new-h")
        assert updated is not None
        assert updated.password_hash == "new-h"

    async def test_returns_get_by_id_when_no_changes(self, db: AsyncIOMotorDatabase) -> None:
        """update_dict empty (all None and no password_hash) -> short-circuits
        to get_by_id."""
        repo = UsersRepository(db)
        u = await repo.create(
            UserCreate(email="a@example.com", name="A", password="p"),
            password_hash="h",
        )
        result = await repo.update(u.id, UserUpdate())
        assert result is not None
        assert result.id == u.id

    async def test_returns_none_when_modified_count_zero(self, db: AsyncIOMotorDatabase) -> None:
        """An update for a nonexistent id returns None (modified_count=0)."""
        repo = UsersRepository(db)
        result = await repo.update("nonexistent", UserUpdate(name="X"))
        assert result is None

    async def test_password_field_not_persisted(self, db: AsyncIOMotorDatabase) -> None:
        """UserUpdate.password is excluded from the mongo $set; password_hash
        is the only credential path."""
        repo = UsersRepository(db)
        u = await repo.create(
            UserCreate(email="a@example.com", name="A", password="p"),
            password_hash="h",
        )
        await repo.update(u.id, UserUpdate(password="leak-me-into-mongo"))
        doc = await db.users.find_one({"id": u.id})
        assert doc is not None
        assert "password" not in doc


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


class TestDelete:
    async def test_returns_true_for_existing(self, db: AsyncIOMotorDatabase) -> None:
        repo = UsersRepository(db)
        u = await repo.create(
            UserCreate(email="a@example.com", name="A", password="p"),
            password_hash="h",
        )
        assert await repo.delete(u.id) is True
        assert await repo.get_by_id(u.id) is None

    async def test_returns_false_for_missing(self, db: AsyncIOMotorDatabase) -> None:
        repo = UsersRepository(db)
        assert await repo.delete("nonexistent") is False


# ---------------------------------------------------------------------------
# create_indexes
# ---------------------------------------------------------------------------


class TestCreateIndexes:
    async def test_creates_required_indexes(self, db: AsyncIOMotorDatabase) -> None:
        repo = UsersRepository(db)
        await repo.create_indexes()
        idx = await db.users.index_information()
        # Default _id index plus the 4 we requested
        names = set(idx.keys())
        # Index names follow mongo convention: <field>_<dir>
        assert any("id_" in n for n in names)
        assert any("email_" in n for n in names)
        assert any("external_id_" in n for n in names)
        assert any("status_" in n for n in names)

    async def test_idempotent(self, db: AsyncIOMotorDatabase) -> None:
        repo = UsersRepository(db)
        await repo.create_indexes()
        # Calling again must not raise
        await repo.create_indexes()
