"""Integration tests for `src.public_users.repository`.

Phase 2.8 Batch C. Target >=80% line coverage on
`src/public_users/repository.py` (RFC-007 magic-link public-user flow).

Surface covered:

**PublicUsersRepository:**
- `create(user_create)` — UUID `_id`, `email_verified=True` (verified via
  magic link), `status="active"`, empty `request_ids`, no last_login.
- `get_by_id(user_id)` / `get_by_email(email)` — translate `_id` back to
  `id` on the model. Email is lowercased before query.
- `update_last_login(user_id)` — sets `last_login_at` AND `updated_at`,
  returns True iff modified_count > 0.
- `update(user_id, user_update)` — drops None values from the patch and
  returns False when nothing to set; otherwise returns modified_count > 0.

**MagicLinkTokensRepository:**
- `create_token(email, token_hash, expires_at, ip, ua)` — UUID `_id`,
  email lowercased, `used=False`, created_at stamped, optional ip/ua.
- `get_by_email(email)` — returns most recent unexpired UNUSED token
  for that email; returns None when nothing matches.
- `mark_as_used(token_id)` — flips `used` to True, returns bool.
- `count_recent_requests(email, since)` — count of tokens created at or
  after `since` for the email (rate limiting).
- `cleanup_expired()` — bulk delete expired tokens, returns deleted_count.

Reality pins:
- The collection uses Mongo's primary key as `_id` (not a separate `id`
  field). Repos translate on read.
- Email is stored lowercased always (write path) and lowercased in queries
  (read path) — case-insensitivity by convention rather than regex.
- `update` returns False when the patch is empty (all None); does NOT
  short-circuit to `get_by_id` like the users repo does.
- `get_by_email` token lookup ignores used tokens AND tokens whose
  `expires_at` is <= now.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from motor.motor_asyncio import AsyncIOMotorDatabase

from src.public_users.models import (
    PublicUserCreate,
    PublicUserStatus,
    PublicUserUpdate,
)
from src.public_users.repository import (
    MagicLinkTokensRepository,
    PublicUsersRepository,
)

# ===========================================================================
# PublicUsersRepository
# ===========================================================================


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


class TestCreatePublicUser:
    async def test_creates_user_with_defaults(self, db: AsyncIOMotorDatabase) -> None:
        repo = PublicUsersRepository(db)
        user = await repo.create(PublicUserCreate(email="alice@example.com", name="Alice"))
        assert user.id
        assert user.email == "alice@example.com"
        assert user.email_verified is True
        assert user.status == PublicUserStatus.ACTIVE
        assert user.last_login_at is None
        assert user.request_ids == []

    async def test_email_lowercased_on_storage(self, db: AsyncIOMotorDatabase) -> None:
        repo = PublicUsersRepository(db)
        user = await repo.create(PublicUserCreate(email="Alice@Example.COM", name="Alice"))
        assert user.email == "alice@example.com"

    async def test_name_optional(self, db: AsyncIOMotorDatabase) -> None:
        repo = PublicUsersRepository(db)
        user = await repo.create(PublicUserCreate(email="a@example.com"))
        assert user.name is None


# ---------------------------------------------------------------------------
# get_by_id / get_by_email
# ---------------------------------------------------------------------------


class TestGetPublicUser:
    async def test_get_by_id_returns_user(self, db: AsyncIOMotorDatabase) -> None:
        repo = PublicUsersRepository(db)
        created = await repo.create(PublicUserCreate(email="a@example.com", name="A"))
        found = await repo.get_by_id(created.id)
        assert found is not None
        assert found.id == created.id
        assert found.email == "a@example.com"

    async def test_get_by_id_returns_none_for_missing(self, db: AsyncIOMotorDatabase) -> None:
        repo = PublicUsersRepository(db)
        assert await repo.get_by_id("missing") is None

    async def test_get_by_email_case_insensitive(self, db: AsyncIOMotorDatabase) -> None:
        repo = PublicUsersRepository(db)
        await repo.create(PublicUserCreate(email="alice@example.com", name="A"))
        found = await repo.get_by_email("ALICE@EXAMPLE.COM")
        assert found is not None
        assert found.email == "alice@example.com"

    async def test_get_by_email_returns_none(self, db: AsyncIOMotorDatabase) -> None:
        repo = PublicUsersRepository(db)
        assert await repo.get_by_email("nobody@example.com") is None

    async def test_get_by_id_preserves_request_ids(self, db: AsyncIOMotorDatabase) -> None:
        repo = PublicUsersRepository(db)
        created = await repo.create(PublicUserCreate(email="a@example.com"))
        await db.public_users.update_one(
            {"_id": created.id}, {"$set": {"request_ids": ["case-1", "case-2"]}}
        )
        found = await repo.get_by_id(created.id)
        assert found is not None
        assert found.request_ids == ["case-1", "case-2"]


# ---------------------------------------------------------------------------
# update_last_login
# ---------------------------------------------------------------------------


class TestUpdateLastLogin:
    async def test_updates_timestamp(self, db: AsyncIOMotorDatabase) -> None:
        repo = PublicUsersRepository(db)
        u = await repo.create(PublicUserCreate(email="a@example.com"))
        result = await repo.update_last_login(u.id)
        assert result is True
        doc = await db.public_users.find_one({"_id": u.id})
        assert doc is not None
        assert doc["last_login_at"] is not None

    async def test_returns_false_for_missing(self, db: AsyncIOMotorDatabase) -> None:
        repo = PublicUsersRepository(db)
        assert await repo.update_last_login("missing") is False


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


class TestUpdatePublicUser:
    async def test_updates_name(self, db: AsyncIOMotorDatabase) -> None:
        repo = PublicUsersRepository(db)
        u = await repo.create(PublicUserCreate(email="a@example.com", name="Old"))
        result = await repo.update(u.id, PublicUserUpdate(name="New"))
        assert result is True
        found = await repo.get_by_id(u.id)
        assert found is not None
        assert found.name == "New"

    async def test_updates_status(self, db: AsyncIOMotorDatabase) -> None:
        repo = PublicUsersRepository(db)
        u = await repo.create(PublicUserCreate(email="a@example.com"))
        result = await repo.update(u.id, PublicUserUpdate(status=PublicUserStatus.SUSPENDED))
        assert result is True
        found = await repo.get_by_id(u.id)
        assert found is not None
        assert found.status == PublicUserStatus.SUSPENDED

    async def test_returns_false_when_nothing_to_set(self, db: AsyncIOMotorDatabase) -> None:
        repo = PublicUsersRepository(db)
        u = await repo.create(PublicUserCreate(email="a@example.com"))
        result = await repo.update(u.id, PublicUserUpdate())
        assert result is False

    async def test_returns_false_for_missing_user(self, db: AsyncIOMotorDatabase) -> None:
        repo = PublicUsersRepository(db)
        result = await repo.update("missing", PublicUserUpdate(name="X"))
        assert result is False


# ===========================================================================
# MagicLinkTokensRepository
# ===========================================================================


# ---------------------------------------------------------------------------
# create_token
# ---------------------------------------------------------------------------


class TestCreateToken:
    async def test_creates_token_with_uuid(self, db: AsyncIOMotorDatabase) -> None:
        repo = MagicLinkTokensRepository(db)
        expires = datetime.utcnow() + timedelta(minutes=15)
        token = await repo.create_token(
            email="alice@example.com",
            token_hash="h",
            expires_at=expires,
        )
        assert token.id
        assert token.email == "alice@example.com"
        assert token.token_hash == "h"
        assert token.used is False
        assert token.ip_address is None
        assert token.user_agent is None

    async def test_email_lowercased(self, db: AsyncIOMotorDatabase) -> None:
        repo = MagicLinkTokensRepository(db)
        token = await repo.create_token(
            email="Alice@Example.COM",
            token_hash="h",
            expires_at=datetime.utcnow() + timedelta(minutes=15),
        )
        assert token.email == "alice@example.com"

    async def test_ip_and_user_agent_stored(self, db: AsyncIOMotorDatabase) -> None:
        repo = MagicLinkTokensRepository(db)
        token = await repo.create_token(
            email="a@example.com",
            token_hash="h",
            expires_at=datetime.utcnow() + timedelta(minutes=15),
            ip_address="1.2.3.4",
            user_agent="Mozilla/5.0",
        )
        assert token.ip_address == "1.2.3.4"
        assert token.user_agent == "Mozilla/5.0"


# ---------------------------------------------------------------------------
# get_by_email (token lookup)
# ---------------------------------------------------------------------------


class TestGetTokenByEmail:
    async def test_returns_most_recent_unused_unexpired(self, db: AsyncIOMotorDatabase) -> None:
        repo = MagicLinkTokensRepository(db)
        # Create three tokens; only the newest should come back
        expires = datetime.utcnow() + timedelta(minutes=15)
        t1 = await repo.create_token(email="a@example.com", token_hash="h1", expires_at=expires)
        t2 = await repo.create_token(email="a@example.com", token_hash="h2", expires_at=expires)
        t3 = await repo.create_token(email="a@example.com", token_hash="h3", expires_at=expires)

        # Confirm IDs are distinct
        assert len({t1.id, t2.id, t3.id}) == 3

        found = await repo.get_by_email("a@example.com")
        assert found is not None
        # Most recent created_at == t3 (last inserted)
        assert found.token_hash == "h3"

    async def test_ignores_used_tokens(self, db: AsyncIOMotorDatabase) -> None:
        repo = MagicLinkTokensRepository(db)
        expires = datetime.utcnow() + timedelta(minutes=15)
        t = await repo.create_token(email="a@example.com", token_hash="h", expires_at=expires)
        await repo.mark_as_used(t.id)
        assert await repo.get_by_email("a@example.com") is None

    async def test_ignores_expired_tokens(self, db: AsyncIOMotorDatabase) -> None:
        repo = MagicLinkTokensRepository(db)
        expired = datetime.utcnow() - timedelta(minutes=1)
        await repo.create_token(email="a@example.com", token_hash="h", expires_at=expired)
        assert await repo.get_by_email("a@example.com") is None

    async def test_case_insensitive_email(self, db: AsyncIOMotorDatabase) -> None:
        repo = MagicLinkTokensRepository(db)
        await repo.create_token(
            email="alice@example.com",
            token_hash="h",
            expires_at=datetime.utcnow() + timedelta(minutes=15),
        )
        found = await repo.get_by_email("ALICE@EXAMPLE.COM")
        assert found is not None


# ---------------------------------------------------------------------------
# mark_as_used
# ---------------------------------------------------------------------------


class TestMarkAsUsed:
    async def test_marks_token_used(self, db: AsyncIOMotorDatabase) -> None:
        repo = MagicLinkTokensRepository(db)
        t = await repo.create_token(
            email="a@example.com",
            token_hash="h",
            expires_at=datetime.utcnow() + timedelta(minutes=15),
        )
        result = await repo.mark_as_used(t.id)
        assert result is True
        doc = await db.magic_link_tokens.find_one({"_id": t.id})
        assert doc is not None
        assert doc["used"] is True

    async def test_returns_false_for_missing(self, db: AsyncIOMotorDatabase) -> None:
        repo = MagicLinkTokensRepository(db)
        assert await repo.mark_as_used("missing") is False


# ---------------------------------------------------------------------------
# count_recent_requests
# ---------------------------------------------------------------------------


class TestCountRecentRequests:
    async def test_counts_recent_tokens_for_email(self, db: AsyncIOMotorDatabase) -> None:
        repo = MagicLinkTokensRepository(db)
        # Create three tokens for the email
        for _ in range(3):
            await repo.create_token(
                email="a@example.com",
                token_hash="h",
                expires_at=datetime.utcnow() + timedelta(minutes=15),
            )
        count = await repo.count_recent_requests(
            "a@example.com", since=datetime.utcnow() - timedelta(hours=1)
        )
        assert count == 3

    async def test_ignores_tokens_for_other_emails(self, db: AsyncIOMotorDatabase) -> None:
        repo = MagicLinkTokensRepository(db)
        await repo.create_token(
            email="a@example.com",
            token_hash="h",
            expires_at=datetime.utcnow() + timedelta(minutes=15),
        )
        await repo.create_token(
            email="b@example.com",
            token_hash="h",
            expires_at=datetime.utcnow() + timedelta(minutes=15),
        )
        count = await repo.count_recent_requests(
            "a@example.com", since=datetime.utcnow() - timedelta(hours=1)
        )
        assert count == 1

    async def test_zero_when_no_tokens(self, db: AsyncIOMotorDatabase) -> None:
        repo = MagicLinkTokensRepository(db)
        count = await repo.count_recent_requests(
            "nobody@example.com", since=datetime.utcnow() - timedelta(hours=1)
        )
        assert count == 0


# ---------------------------------------------------------------------------
# cleanup_expired
# ---------------------------------------------------------------------------


class TestCleanupExpired:
    async def test_deletes_only_expired_tokens(self, db: AsyncIOMotorDatabase) -> None:
        repo = MagicLinkTokensRepository(db)
        # 2 expired, 1 active
        expired = datetime.utcnow() - timedelta(minutes=1)
        active = datetime.utcnow() + timedelta(minutes=15)
        await repo.create_token(email="a@x.com", token_hash="h1", expires_at=expired)
        await repo.create_token(email="b@x.com", token_hash="h2", expires_at=expired)
        await repo.create_token(email="c@x.com", token_hash="h3", expires_at=active)

        deleted = await repo.cleanup_expired()
        assert deleted == 2
        remaining = await db.magic_link_tokens.count_documents({})
        assert remaining == 1

    async def test_zero_when_none_expired(self, db: AsyncIOMotorDatabase) -> None:
        repo = MagicLinkTokensRepository(db)
        await repo.create_token(
            email="a@x.com",
            token_hash="h",
            expires_at=datetime.utcnow() + timedelta(minutes=15),
        )
        assert await repo.cleanup_expired() == 0
