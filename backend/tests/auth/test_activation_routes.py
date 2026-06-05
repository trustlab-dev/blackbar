"""Integration tests for `src.auth.activation_routes`.

Phase 2.1.C. Target ≥80% line coverage.

Reality calibration:
- Only ONE endpoint: POST /api/v1/auth/activate-owner
- The route reads `db` from `src.database` at import time -> tests
  monkeypatch `src.auth.activation_routes.db` AND
  `src.auth.activation_service` lazy import (the service does
  `from src.database import db` inside activate_account()) so the
  $unset cleanup write lands in the per-test database.
- The activation flow needs a pending-activation user record with an
  activation_token (hashed) + activation_token_expires_at field.
- `/auth/activate-owner` IS in the AuthMiddleware public allowlist
  (added 2026-05-12 to fix audit finding B9 — pre-fix the middleware
  rejected all activation requests with 401 before the handler ran).
  The route docstring says "No authentication required - uses
  activation token for verification". Tests now exercise the full
  HTTP surface.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.auth.auth_service import AuthService
from src.users.models import UserCreate
from src.users.repository import UsersRepository

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_activation_route_db(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase):
    """Re-bind src.auth.activation_routes.db AND src.database.db to the
    per-test motor database.

    The route module does `from src.database import db` at import time
    -> we monkeypatch the route module's `db` symbol. The activation
    SERVICE does a lazy `from src.database import db` inside
    activate_account() — we monkeypatch the underlying module too."""
    import src.auth.activation_routes as _routes_mod
    import src.database as _db_mod

    monkeypatch.setattr(_routes_mod, "db", db)
    monkeypatch.setattr(_db_mod, "db", db)
    return db


async def _seed_pending_user(
    db: AsyncIOMotorDatabase,
    *,
    email: str,
    token_plaintext: str = "valid-activation-token-987654",
    expires_at: datetime | None = None,
) -> str:
    """Seed a pending_activation user with hashed activation token. Returns
    user id."""
    if expires_at is None:
        expires_at = datetime.utcnow() + timedelta(hours=24)
    token_hash = bcrypt.hashpw(token_plaintext.encode(), bcrypt.gensalt()).decode()

    repo = UsersRepository(db)
    user = await repo.create(
        UserCreate(email=email, name="Pending Owner", password="placeholder"),
        AuthService.hash_password("placeholder"),
    )
    await db.users.update_one(
        {"id": user.id},
        {
            "$set": {
                "status": "pending_activation",
                "activation_token": token_hash,
                "activation_token_expires_at": expires_at,
            }
        },
    )
    return user.id


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


# ---------------------------------------------------------------------------
# POST /auth/activate-owner
# ---------------------------------------------------------------------------


# Strong password that satisfies the route validator (upper/lower/digit/special)
GOOD_PWD = "Strong-Pwd-99!"


class TestActivateOwner:
    async def test_activate_with_valid_token_returns_user(
        self, app, db: AsyncIOMotorDatabase, patch_activation_route_db
    ) -> None:
        """Happy path: a pending user with a fresh token activates with the
        plaintext token from the welcome email + a strong password."""
        token = "fresh-tok-7891011"
        user_id = await _seed_pending_user(db, email="owner@example.com", token_plaintext=token)

        async with _client(app) as c:
            r = await c.post(
                "/api/v1/auth/activate-owner",
                json={
                    "email": "owner@example.com",
                    "token": token,
                    "password": GOOD_PWD,
                },
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["user_id"] == user_id
        assert body["email"] == "owner@example.com"
        # User status flipped from pending_activation to active
        doc = await db.users.find_one({"id": user_id})
        assert doc is not None
        assert doc["status"] == "active"

    async def test_activate_invalid_token_returns_400(
        self, app, db: AsyncIOMotorDatabase, patch_activation_route_db
    ) -> None:
        """A wrong activation token reaches the handler and gets a clean
        400 from `raise HTTPException(400, "Invalid or expired activation
        token")`."""
        await _seed_pending_user(db, email="owner2@example.com")

        async with _client(app) as c:
            r = await c.post(
                "/api/v1/auth/activate-owner",
                json={
                    "email": "owner2@example.com",
                    "token": "wrong-token-xyz",
                    "password": GOOD_PWD,
                },
            )
        assert r.status_code == 400, r.text

    async def test_activate_missing_password_returns_422(
        self, app, db: AsyncIOMotorDatabase, patch_activation_route_db
    ) -> None:
        """A request body missing required fields fails Pydantic validation
        with a 422. Now reachable because the route is in the public
        allowlist. Phase 4 Batch 4.4 (audit B7) fixed the deprecated
        `HTTP_422_UNPROCESSABLE_ENTITY` constant; per-test filterwarnings
        no longer required."""
        async with _client(app) as c:
            r = await c.post(
                "/api/v1/auth/activate-owner",
                json={"email": "owner@example.com"},
            )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Unit-level invocation of the activation route function
#
# The middleware gate means HTTP-level happy/error testing isn't reachable
# without a token (and the route isn't designed to require one). To still
# pin the route's BODY logic we invoke the handler function directly with
# fabricated inputs. This covers the route function's lines that the HTTP
# tests cannot.
# ---------------------------------------------------------------------------


class TestActivateOwnerDirectInvocation:
    """Direct-call tests for the route handler body. Bypasses middleware."""

    async def test_handler_success_returns_response_model(
        self, db: AsyncIOMotorDatabase, patch_activation_route_db
    ) -> None:
        """Calling the route function with valid args returns an
        ActivateAccountResponse. Pins lines 47-87 of activation_routes.py."""
        from types import SimpleNamespace

        from src.auth.activation_routes import (
            ActivateAccountRequest,
            activate_owner_account,
        )

        token = "good-token-direct"
        await _seed_pending_user(db, email="direct@example.com", token_plaintext=token)

        # Fake request with a state for correlation_id helper.
        request = SimpleNamespace(state=SimpleNamespace(correlation_id="test-cid"))

        response = await activate_owner_account(
            request=request,  # type: ignore[arg-type]
            activation_data=ActivateAccountRequest(
                email="direct@example.com",
                token=token,
                password=GOOD_PWD,
            ),
        )

        assert response.email == "direct@example.com"
        assert "activated successfully" in response.message.lower()

    async def test_handler_invalid_token_raises_400(
        self, db: AsyncIOMotorDatabase, patch_activation_route_db
    ) -> None:
        """Direct-call: invalid token -> 400 'Invalid or expired activation
        token'. Pins lines 69-77."""
        from types import SimpleNamespace

        from fastapi import HTTPException

        from src.auth.activation_routes import (
            ActivateAccountRequest,
            activate_owner_account,
        )

        await _seed_pending_user(db, email="bad@example.com")

        request = SimpleNamespace(state=SimpleNamespace(correlation_id="test-cid"))

        with pytest.raises(HTTPException) as exc_info:
            await activate_owner_account(
                request=request,  # type: ignore[arg-type]
                activation_data=ActivateAccountRequest(
                    email="bad@example.com",
                    token="not-the-real-token-1234567",
                    password=GOOD_PWD,
                ),
            )
        assert exc_info.value.status_code == 400
        assert "Invalid or expired" in exc_info.value.detail

    async def test_handler_unknown_email_raises_400(
        self, db: AsyncIOMotorDatabase, patch_activation_route_db
    ) -> None:
        """Unknown email -> ActivationService returns None -> route raises
        400. Pins the None-return code path."""
        from types import SimpleNamespace

        from fastapi import HTTPException

        from src.auth.activation_routes import (
            ActivateAccountRequest,
            activate_owner_account,
        )

        request = SimpleNamespace(state=SimpleNamespace(correlation_id="test-cid"))

        with pytest.raises(HTTPException) as exc_info:
            await activate_owner_account(
                request=request,  # type: ignore[arg-type]
                activation_data=ActivateAccountRequest(
                    email="nobody@example.com",
                    token="some-token-7891011",
                    password=GOOD_PWD,
                ),
            )
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Password-validator behavior on the Pydantic model
# ---------------------------------------------------------------------------


class TestActivateRequestValidation:
    """Cover the ActivateAccountRequest password-complexity validator
    directly (it's part of activation_routes.py and contributes to its
    line count). Each branch covered."""

    OK_EMAIL = "alice@example.com"

    def test_missing_uppercase_raises(self) -> None:
        from pydantic import ValidationError

        from src.auth.activation_routes import ActivateAccountRequest

        with pytest.raises(ValidationError, match="uppercase"):
            ActivateAccountRequest(email=self.OK_EMAIL, token="x", password="lower-only-no-caps-1!")

    def test_missing_lowercase_raises(self) -> None:
        from pydantic import ValidationError

        from src.auth.activation_routes import ActivateAccountRequest

        with pytest.raises(ValidationError, match="lowercase"):
            ActivateAccountRequest(
                email=self.OK_EMAIL, token="x", password="UPPER-ONLY-NO-LOWER-1!"
            )

    def test_missing_digit_raises(self) -> None:
        from pydantic import ValidationError

        from src.auth.activation_routes import ActivateAccountRequest

        with pytest.raises(ValidationError, match="digit"):
            ActivateAccountRequest(email=self.OK_EMAIL, token="x", password="No-Digits-Here!")

    def test_missing_special_char_raises(self) -> None:
        from pydantic import ValidationError

        from src.auth.activation_routes import ActivateAccountRequest

        with pytest.raises(ValidationError, match="special"):
            ActivateAccountRequest(email=self.OK_EMAIL, token="x", password="NoSpecialChars1")

    def test_valid_password_passes(self) -> None:
        from src.auth.activation_routes import ActivateAccountRequest

        req = ActivateAccountRequest(email=self.OK_EMAIL, token="x", password=GOOD_PWD)
        assert req.password == GOOD_PWD
