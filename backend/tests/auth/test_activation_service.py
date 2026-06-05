"""Service-level tests for `src.auth.activation_service`.

Phase 2.1.B. Covers 100% of src.auth.activation_service.ActivationService.

Reality calibration vs. the plan:
- The plan's test list assumed a richer API with `create_activation_token`,
  `activate`, and `resend` methods. Reality (101 LoC): the service has
  ONE public method, `activate_account(email, token, password)`. Token
  creation lives elsewhere — most likely in the routes layer or
  `WelcomeEmailService.generate_activation_token` — and is covered in
  Batch 2.1.C (route tests). The `resend` flow is also a routes-layer
  concern.

- The plan called out a "create_activation_token includes expiry" test.
  The expiry-on-the-user-record is set by whatever code populates
  `user.activation_token_expires_at`; ActivationService only READS that
  field. Tests therefore pin the consumption side: expired token ->
  None, missing-expires_at -> None, valid-not-yet-expired -> success.

- The plan's "activate triggers welcome email" test: the activation
  service does NOT send any email. WelcomeEmailService is constructed
  with `None` for email_service (line 22) and only its `verify_token`
  method is used. No SendGrid mock is therefore needed for these
  tests; the welcome-email send path is exercised in welcome-email
  service tests / route tests.

- Line 89 (`from src.database import db`) is a lazy import that uses
  the module-level `db` handle. The conftest's `_mongo_container`
  fixture binds `src.config.MONGODB_URI` to the live testcontainer
  URI, but `src.database.db` is bound at `src.database` import time —
  potentially before that URI rebind. Tests patch
  `src.database.db` to point at the per-test database to ensure the
  $unset cleanup write lands in the right place.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import bcrypt
import pytest
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.auth.activation_service import ActivationService
from src.auth.auth_service import AuthService
from src.users.models import UserCreate
from src.users.repository import UsersRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hash_activation_token(token: str) -> str:
    """bcrypt-hash an activation token. Matches WelcomeEmailService.hash_token."""
    return bcrypt.hashpw(token.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


async def _seed_pending_user(
    db: AsyncIOMotorDatabase,
    *,
    email: str,
    activation_token_plaintext: str | None = "valid-activation-token",
    activation_token_expires_at: datetime | None = None,
    status: str = "pending_activation",
    activation_token_hash: str | None = None,
) -> dict[str, Any]:
    """Insert a pending_activation user record directly so we control
    every field (UserCreate doesn't expose activation_token / status).

    Returns the inserted document for inspection."""
    if activation_token_expires_at is None:
        activation_token_expires_at = datetime.utcnow() + timedelta(hours=24)

    # Generate a hash if a plaintext was supplied and no explicit hash was given.
    if activation_token_hash is None and activation_token_plaintext is not None:
        activation_token_hash = _hash_activation_token(activation_token_plaintext)

    # Use the repo for canonical create() then patch the activation fields.
    repo = UsersRepository(db)
    user_create = UserCreate(email=email, name="Pending Owner", password="placeholder-pwd")
    user = await repo.create(user_create, AuthService.hash_password("placeholder-pwd"))

    patch: dict[str, Any] = {"status": status}
    if activation_token_hash is not None:
        patch["activation_token"] = activation_token_hash
    if activation_token_expires_at is not None:
        patch["activation_token_expires_at"] = activation_token_expires_at
    await db.users.update_one({"id": user.id}, {"$set": patch})

    doc = await db.users.find_one({"id": user.id})
    assert doc is not None
    return doc


@pytest.fixture
def patch_db_module(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase):
    """Point `src.database.db` at the per-test motor database.

    activation_service.py does `from src.database import db` lazily
    inside `activate_account` (line 89) to issue an $unset cleanup.
    The conftest's `_mongo_container` fixture rebinds `src.config.MONGODB_URI`
    after the testcontainer starts, but `src.database.db` is module-level
    state captured at first import — so it may point at the placeholder
    URI's database. Patching here makes the $unset land in the right
    place for the test."""
    import src.database as _db_mod

    monkeypatch.setattr(_db_mod, "db", db)
    return db


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_service_constructed_with_repo_and_welcome_service(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        """ActivationService(repo) wires up an internal WelcomeEmailService
        with email_service=None (line 22). Pins the constructor contract."""
        service = ActivationService(UsersRepository(db))
        assert service.users_repo is not None
        assert service.welcome_service is not None


# ---------------------------------------------------------------------------
# activate_account — happy path
# ---------------------------------------------------------------------------


class TestActivateHappyPath:
    async def test_activate_valid_token_marks_user_active(
        self, db: AsyncIOMotorDatabase, patch_db_module: AsyncIOMotorDatabase
    ) -> None:
        token = "valid-activation-token-123"
        await _seed_pending_user(db, email="owner@example.com", activation_token_plaintext=token)
        service = ActivationService(UsersRepository(db))

        result = await service.activate_account(
            email="owner@example.com", token=token, password="new-pwd-456"
        )

        assert result is not None
        assert result.status.value == "active"

        # The activation_token + activation_token_expires_at fields were
        # $unset from the DB record.
        doc = await db.users.find_one({"email": "owner@example.com"})
        assert doc is not None
        assert "activation_token" not in doc
        assert "activation_token_expires_at" not in doc

        # New password verifies.
        assert doc["password_hash"] != "placeholder-pwd"
        assert AuthService.verify_password("new-pwd-456", doc["password_hash"]) is True


# ---------------------------------------------------------------------------
# activate_account — error paths
# ---------------------------------------------------------------------------


class TestActivateErrorPaths:
    async def test_activate_unknown_email_returns_none(self, db: AsyncIOMotorDatabase) -> None:
        """No user with this email -> None. Pins lines 42-46."""
        service = ActivationService(UsersRepository(db))
        result = await service.activate_account(
            email="nobody@example.com", token="any", password="any"
        )
        assert result is None

    async def test_activate_already_active_user_returns_none(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        """status != 'pending_activation' -> None. Pins lines 49-52."""
        # Seed an active (not pending) user.
        repo = UsersRepository(db)
        user = await repo.create(
            UserCreate(email="already@example.com", name="Already", password="pwd"),
            AuthService.hash_password("pwd"),
        )
        # Default status is 'active'.
        service = ActivationService(UsersRepository(db))

        result = await service.activate_account(
            email="already@example.com", token="any", password="newpwd"
        )
        assert result is None
        # Ensure password wasn't rotated.
        doc = await db.users.find_one({"id": user.id})
        assert doc is not None
        assert AuthService.verify_password("pwd", doc["password_hash"]) is True

    async def test_activate_missing_token_field_returns_none(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        """status=pending_activation but no activation_token set -> None.
        Pins lines 55-58 (the `not user.activation_token` branch)."""
        # Insert a pending user with NO activation_token.
        repo = UsersRepository(db)
        user = await repo.create(
            UserCreate(email="notok@example.com", name="NoToken", password="pwd"),
            AuthService.hash_password("pwd"),
        )
        await db.users.update_one({"id": user.id}, {"$set": {"status": "pending_activation"}})

        service = ActivationService(UsersRepository(db))
        result = await service.activate_account(
            email="notok@example.com", token="any", password="newpwd"
        )
        assert result is None

    async def test_activate_missing_expires_at_returns_none(self, db: AsyncIOMotorDatabase) -> None:
        """activation_token is set but expires_at is missing -> None.
        Pins the second clause of the `or` on line 55."""
        repo = UsersRepository(db)
        user = await repo.create(
            UserCreate(email="noexp@example.com", name="NoExp", password="pwd"),
            AuthService.hash_password("pwd"),
        )
        await db.users.update_one(
            {"id": user.id},
            {
                "$set": {
                    "status": "pending_activation",
                    "activation_token": _hash_activation_token("token"),
                    # NO activation_token_expires_at
                }
            },
        )

        service = ActivationService(UsersRepository(db))
        result = await service.activate_account(
            email="noexp@example.com", token="token", password="newpwd"
        )
        assert result is None

    async def test_activate_expired_token_returns_none(self, db: AsyncIOMotorDatabase) -> None:
        """activation_token_expires_at in the past -> None. Pins lines 61-64."""
        token = "expired-tok"
        await _seed_pending_user(
            db,
            email="exp@example.com",
            activation_token_plaintext=token,
            activation_token_expires_at=datetime.utcnow() - timedelta(hours=1),
        )

        service = ActivationService(UsersRepository(db))
        result = await service.activate_account(
            email="exp@example.com", token=token, password="newpwd"
        )
        assert result is None

    async def test_activate_invalid_token_returns_none(self, db: AsyncIOMotorDatabase) -> None:
        """A token that doesn't bcrypt-verify against the stored hash -> None.
        Pins lines 67-70."""
        await _seed_pending_user(
            db,
            email="wrongtok@example.com",
            activation_token_plaintext="real-token",
        )

        service = ActivationService(UsersRepository(db))
        result = await service.activate_account(
            email="wrongtok@example.com", token="wrong-token", password="newpwd"
        )
        assert result is None

    async def test_activate_repo_update_returns_none_propagates(
        self,
        db: AsyncIOMotorDatabase,
        patch_db_module: AsyncIOMotorDatabase,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If `users_repo.update(...)` returns None (no document matched),
        the service returns None. Pins lines 83-86."""
        token = "tok-for-failure"
        await _seed_pending_user(
            db, email="failupdate@example.com", activation_token_plaintext=token
        )

        # Force the repo's update to return None (simulating a race / lost user).
        repo = UsersRepository(db)

        async def _fake_update(*_args: Any, **_kwargs: Any) -> None:
            return None

        monkeypatch.setattr(repo, "update", _fake_update)
        service = ActivationService(repo)

        result = await service.activate_account(
            email="failupdate@example.com", token=token, password="newpwd"
        )
        assert result is None


# ---------------------------------------------------------------------------
# Idempotency / re-use semantics — characterization tests
# ---------------------------------------------------------------------------


class TestActivateReuse:
    async def test_activate_twice_second_attempt_fails(
        self, db: AsyncIOMotorDatabase, patch_db_module: AsyncIOMotorDatabase
    ) -> None:
        """Once an account is activated, the user's status becomes 'active'
        and the activation_token is $unset. A second activate_account call
        fails at the status check (returns None) — pinning the single-use
        guarantee. This is the documented production behavior."""
        token = "single-use-token"
        await _seed_pending_user(db, email="once@example.com", activation_token_plaintext=token)
        service = ActivationService(UsersRepository(db))

        # First call: success.
        first = await service.activate_account(
            email="once@example.com", token=token, password="first-pwd"
        )
        assert first is not None

        # Second call with the same token: blocked by status check.
        second = await service.activate_account(
            email="once@example.com", token=token, password="second-pwd"
        )
        assert second is None

        # The password from the first attempt is what's stored — not the second.
        doc = await db.users.find_one({"email": "once@example.com"})
        assert doc is not None
        assert AuthService.verify_password("first-pwd", doc["password_hash"]) is True
        assert AuthService.verify_password("second-pwd", doc["password_hash"]) is False
