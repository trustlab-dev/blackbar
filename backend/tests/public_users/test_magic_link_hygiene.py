"""AUTH-28: magic-link hygiene, against a real MongoDB.

- verify is atomic single-use (two concurrent verifies: one wins);
- suspended public users can neither verify nor use an existing session;
- `public_users.email` is unique and `magic_link_tokens` expire via TTL;
- the most-recent-token lookup is deterministic even for same-millisecond
  inserts.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from src.auth.magic_link_service import MagicLinkService
from src.public_users.models import PublicUserCreate
from src.public_users.repository import MagicLinkTokensRepository, PublicUsersRepository


def _service(db: AsyncIOMotorDatabase) -> MagicLinkService:
    return MagicLinkService(
        users_repo=PublicUsersRepository(db), tokens_repo=MagicLinkTokensRepository(db)
    )


class TestAtomicVerify:
    async def test_consume_succeeds_once(self, db: AsyncIOMotorDatabase) -> None:
        repo = MagicLinkTokensRepository(db)
        t = await repo.create_token(
            email="a@example.org",
            token_hash="h",
            expires_at=datetime.utcnow() + timedelta(minutes=15),
        )
        assert await repo.consume(t.id) is True
        assert await repo.consume(t.id) is False

    async def test_consume_refuses_expired_token(self, db: AsyncIOMotorDatabase) -> None:
        repo = MagicLinkTokensRepository(db)
        t = await repo.create_token(
            email="a@example.org",
            token_hash="h",
            expires_at=datetime.utcnow() - timedelta(seconds=1),
        )
        assert await repo.consume(t.id) is False

    async def test_concurrent_verifies_issue_one_session(self, db: AsyncIOMotorDatabase) -> None:
        service = _service(db)
        token, _ = await service.request_magic_link("race@example.org")
        results = await asyncio.gather(
            service.verify_magic_link(token, "race@example.org"),
            service.verify_magic_link(token, "race@example.org"),
        )
        assert sum(r is not None for r in results) == 1


class TestSuspension:
    async def test_suspended_user_cannot_verify(self, db: AsyncIOMotorDatabase) -> None:
        service = _service(db)
        token, _ = await service.request_magic_link("sus@example.org")
        await db.public_users.update_one(
            {"email": "sus@example.org"}, {"$set": {"status": "suspended"}}
        )
        assert await service.verify_magic_link(token, "sus@example.org") is None

    async def test_suspended_user_session_is_refused(self, db: AsyncIOMotorDatabase) -> None:
        from src.auth.dependencies import get_active_public_user

        user = await PublicUsersRepository(db).create(PublicUserCreate(email="s2@example.org"))
        principal = {"user_id": user.id, "email": user.email, "user_type": "public"}
        assert await get_active_public_user(principal, db) == principal

        await db.public_users.update_one({"_id": user.id}, {"$set": {"status": "suspended"}})
        with pytest.raises(HTTPException) as exc:
            await get_active_public_user(principal, db)
        assert exc.value.status_code == 403

    async def test_unknown_public_user_session_is_refused(self, db: AsyncIOMotorDatabase) -> None:
        from src.auth.dependencies import get_active_public_user

        principal = {"user_id": "gone", "email": "gone@example.org", "user_type": "public"}
        with pytest.raises(HTTPException) as exc:
            await get_active_public_user(principal, db)
        assert exc.value.status_code == 401


class TestIndexes:
    async def test_public_user_email_is_unique(self, db: AsyncIOMotorDatabase) -> None:
        from src.core.database import create_indexes

        await create_indexes(db)
        repo = PublicUsersRepository(db)
        await repo.create(PublicUserCreate(email="dup@example.org"))
        with pytest.raises(DuplicateKeyError):
            await repo.create(PublicUserCreate(email="dup@example.org"))

    async def test_magic_link_tokens_have_ttl(self, db: AsyncIOMotorDatabase) -> None:
        from src.core.database import create_indexes

        await create_indexes(db)
        info = await db.magic_link_tokens.index_information()
        ttl = [i for i in info.values() if i.get("expireAfterSeconds") is not None]
        assert ttl and ttl[0]["key"] == [("expires_at", 1)]

    async def test_concurrent_first_requests_create_one_user(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        from src.core.database import create_indexes

        await create_indexes(db)
        service = _service(db)
        await asyncio.gather(
            service.request_magic_link("first@example.org"),
            service.request_magic_link("first@example.org"),
        )
        assert await db.public_users.count_documents({"email": "first@example.org"}) == 1


class TestDeterministicOrdering:
    async def test_same_millisecond_tokens_resolve_to_last_inserted(
        self, db: AsyncIOMotorDatabase, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression for the flaky most-recent-token test: Mongo stores
        datetimes at millisecond precision, so rapid inserts tie on
        created_at. Freeze the clock to force the tie."""
        import src.public_users.repository as repo_mod

        frozen = datetime(2026, 9, 24, 12, 0, 0, tzinfo=UTC).replace(tzinfo=None)

        class _FrozenDatetime(datetime):
            @classmethod
            def utcnow(cls):  # type: ignore[override]
                return frozen

        monkeypatch.setattr(repo_mod, "datetime", _FrozenDatetime)
        repo = MagicLinkTokensRepository(db)
        expires = frozen + timedelta(minutes=15)
        for h in ("h1", "h2", "h3"):
            await repo.create_token(email="t@example.org", token_hash=h, expires_at=expires)
        found = await repo.get_by_email("t@example.org")
        assert found is not None and found.token_hash == "h3"
