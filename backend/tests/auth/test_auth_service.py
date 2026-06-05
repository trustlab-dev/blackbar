"""Service-level tests for `src.auth.auth_service`.

Phase 2.1.B. Covers:
- TokenPayload model defaults / shape
- AuthService.hash_password / verify_password (instance-free static helpers)
- AuthService.authenticate_local with a real Mongo testcontainer + seeded user
- AuthService.issue_token across all 4 production roles (admin / analyst /
  user / guest) — pins the post-Phase-1.7 realm literal "org"
  (admin role maps to realm "admin"; everything else maps to "org")
- AuthService.validate_token across happy + expired + wrong-secret +
  malformed + legacy-roles-list + missing-role paths

Reality calibration vs. the plan:
- The plan originally pinned `TokenPayload.realm` as a plain `str` that
  accepted any value (legacy "tenant" included). Phase 4 Batch 4.4
  tightened the field to `Literal["public", "org", "admin"]` (audit
  B2), so the legacy-string acceptance test was flipped to assert
  that unknown realms now raise `ValidationError`.
- The plan called the validator method `decode_token`; the actual
  method is `validate_token`. Tests use the real name.
- AuthService uses `bcrypt` directly, not the `passlib` CryptContext
  that lives in `src.auth.security`. Both produce $2b$ hashes that
  cross-verify, but the implementations are separate.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import jwt
import pytest
from freezegun import freeze_time
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.auth.auth_service import AuthService, TokenPayload
from src.config import ACCESS_TOKEN_EXPIRE_MINUTES, ALGORITHM, JWT_SECRET
from src.users.models import User, UserCreate
from src.users.repository import UsersRepository

# ---------------------------------------------------------------------------
# TokenPayload model
# ---------------------------------------------------------------------------


class TestTokenPayload:
    """Pin the Pydantic TokenPayload shape post-Phase-1.7."""

    def test_token_payload_defaults_realm_to_org(self) -> None:
        """Phase 1.7 cutover: default realm is 'org' (not 'tenant')."""
        payload = TokenPayload(sub="user-1", role="user", exp=9999999999)
        assert payload.realm == "org"

    def test_token_payload_accepts_explicit_org_realm(self) -> None:
        payload = TokenPayload(sub="user-1", role="user", exp=9999999999, realm="org")
        assert payload.realm == "org"

    def test_token_payload_accepts_known_realms(self) -> None:
        """Phase 4 Batch 4.4 (audit B2): `realm` is now
        `Literal["public", "org", "admin"]`. Only the three production
        values are accepted at the model layer."""
        for realm in ["public", "org", "admin"]:
            payload = TokenPayload(sub="u", role="user", exp=1, realm=realm)
            assert payload.realm == realm

    def test_token_payload_rejects_unknown_realm(self) -> None:
        """Phase 4 Batch 4.4 (audit B2): legacy or arbitrary realm
        strings (e.g. 'tenant') now raise ValidationError. Replaces
        the prior characterization test that pinned the plain-str
        behaviour."""
        from pydantic import ValidationError

        for realm in ["tenant", "anything", "ORG", ""]:
            with pytest.raises(ValidationError):
                TokenPayload(sub="u", role="user", exp=1, realm=realm)

    def test_token_payload_requires_sub_role_exp(self) -> None:
        """sub, role, and exp are required (no defaults)."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            TokenPayload(role="user", exp=1)  # type: ignore[call-arg]
        with pytest.raises(ValidationError):
            TokenPayload(sub="u", exp=1)  # type: ignore[call-arg]
        with pytest.raises(ValidationError):
            TokenPayload(sub="u", role="user")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# AuthService static password helpers
# ---------------------------------------------------------------------------


class TestPasswordHelpers:
    def test_hash_password_returns_bcrypt_string(self) -> None:
        h = AuthService.hash_password("hunter2")
        assert isinstance(h, str)
        assert h.startswith("$2")
        assert h != "hunter2"

    def test_hash_password_uses_random_salt(self) -> None:
        a = AuthService.hash_password("same")
        b = AuthService.hash_password("same")
        assert a != b

    def test_verify_password_round_trip(self) -> None:
        h = AuthService.hash_password("correct-horse-battery-staple")
        assert AuthService.verify_password("correct-horse-battery-staple", h) is True
        assert AuthService.verify_password("wrong-one", h) is False


# ---------------------------------------------------------------------------
# AuthService.authenticate_local (full DB roundtrip)
# ---------------------------------------------------------------------------


async def _seed_user(
    db: AsyncIOMotorDatabase,
    *,
    email: str,
    password: str,
    status: str = "active",
    role: str = "user",
    with_password: bool = True,
) -> User:
    """Seed an active user via UsersRepository.create() + role/status patch.

    Mirrors the conftest's authed_client_factory seeding pattern.
    """
    repo = UsersRepository(db)
    password_hash = AuthService.hash_password(password) if with_password else None
    user_create = UserCreate(email=email, name="Seeded", password=password)
    user = await repo.create(user_create, password_hash or "")
    # Patch role/status (UserCreate has no role field; status defaults to "active").
    patch: dict[str, Any] = {}
    if role != "user":
        patch["role"] = role
    if status != "active":
        patch["status"] = status
    if not with_password:
        patch["password_hash"] = None
    if patch:
        await db.users.update_one({"id": user.id}, {"$set": patch})
        # Refresh
        refreshed = await repo.get_by_id(user.id)
        assert refreshed is not None
        return refreshed
    return user


class TestAuthenticateLocal:
    """Full-DB roundtrip for credential check."""

    async def test_authenticate_correct_credentials(self, db: AsyncIOMotorDatabase) -> None:
        await _seed_user(db, email="alice@example.com", password="s3cret-pwd")
        service = AuthService(UsersRepository(db))

        user = await service.authenticate_local("alice@example.com", "s3cret-pwd")

        assert user is not None
        assert user.email == "alice@example.com"

    async def test_authenticate_wrong_password(self, db: AsyncIOMotorDatabase) -> None:
        await _seed_user(db, email="bob@example.com", password="real-pwd")
        service = AuthService(UsersRepository(db))

        user = await service.authenticate_local("bob@example.com", "WRONG")
        assert user is None

    async def test_authenticate_unknown_email(self, db: AsyncIOMotorDatabase) -> None:
        service = AuthService(UsersRepository(db))
        user = await service.authenticate_local("nobody@example.com", "anything")
        assert user is None

    async def test_authenticate_inactive_user(self, db: AsyncIOMotorDatabase) -> None:
        await _seed_user(db, email="frozen@example.com", password="pwd", status="disabled")
        service = AuthService(UsersRepository(db))

        user = await service.authenticate_local("frozen@example.com", "pwd")
        assert user is None

    async def test_authenticate_user_without_password(self, db: AsyncIOMotorDatabase) -> None:
        """SSO-only user (no password_hash) cannot log in via local auth.

        Pins the `if not user.password_hash` branch (line 72-74).
        """
        await _seed_user(
            db,
            email="sso@example.com",
            password="placeholder",
            with_password=False,
        )
        service = AuthService(UsersRepository(db))

        user = await service.authenticate_local("sso@example.com", "anything")
        assert user is None


# ---------------------------------------------------------------------------
# AuthService.issue_token
# ---------------------------------------------------------------------------


def _build_user(role: str = "user", user_id: str = "u-1") -> User:
    return User(
        id=user_id,
        email=f"{role}@example.test",
        name=f"Test {role.title()}",
        role=role,
        status="active",
        password_hash="$2b$12$placeholder",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


def _decode(token: str) -> dict[str, Any]:
    return jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])


class TestIssueToken:
    """Token issuance per role.

    Phase 1.7 cutover: realm is 'admin' if role=='admin', otherwise 'org'.
    The 4-tier role model (admin/analyst/user/guest) per src.auth.roles
    is the canonical set — the plan's 5-tier reference to 'owner' is
    obsolete.
    """

    @pytest.mark.parametrize("role", ["admin", "analyst", "user", "guest"])
    async def test_issue_token_per_role_has_role_in_payload(
        self, db: AsyncIOMotorDatabase, role: str
    ) -> None:
        service = AuthService(UsersRepository(db))
        user = _build_user(role=role, user_id=f"u-{role}")

        token = await service.issue_token(user)

        decoded = _decode(token)
        assert decoded["role"] == role
        assert decoded["sub"] == f"u-{role}"

    async def test_issue_token_admin_role_uses_admin_realm(self, db: AsyncIOMotorDatabase) -> None:
        service = AuthService(UsersRepository(db))
        token = await service.issue_token(_build_user(role="admin"))
        decoded = _decode(token)
        assert decoded["realm"] == "admin"

    @pytest.mark.parametrize("role", ["analyst", "user", "guest"])
    async def test_issue_token_non_admin_uses_org_realm(
        self, db: AsyncIOMotorDatabase, role: str
    ) -> None:
        """Pins the post-Phase-1.7 realm literal 'org' for non-admin roles."""
        service = AuthService(UsersRepository(db))
        token = await service.issue_token(_build_user(role=role))
        decoded = _decode(token)
        assert decoded["realm"] == "org"

    @freeze_time("2026-05-11 12:00:00")
    async def test_issue_token_default_expiration(self, db: AsyncIOMotorDatabase) -> None:
        """Default expiration = ACCESS_TOKEN_EXPIRE_MINUTES (60 min)
        from src.config — not from any env var override."""
        service = AuthService(UsersRepository(db))
        token = await service.issue_token(_build_user())
        decoded = _decode(token)

        expected = int(
            (
                datetime(2026, 5, 11, 12, 0, 0) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
            ).timestamp()
        )
        assert decoded["exp"] == expected


# ---------------------------------------------------------------------------
# AuthService.validate_token
# ---------------------------------------------------------------------------


def _make_jwt(payload: dict[str, Any], secret: str = JWT_SECRET) -> str:
    """Helper: encode a dict directly so tests can produce malformed shapes."""
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


class TestValidateToken:
    """validate_token returns TokenPayload | None.

    The method is called `validate_token` in the source — the plan referred
    to it as `decode_token`, which doesn't exist.
    """

    def test_validate_token_valid_returns_payload(self) -> None:
        future = int((datetime.utcnow() + timedelta(minutes=10)).timestamp())
        token = _make_jwt({"sub": "u-1", "role": "analyst", "realm": "org", "exp": future})

        payload = AuthService.validate_token(token)

        assert payload is not None
        assert payload.sub == "u-1"
        assert payload.role == "analyst"
        assert payload.realm == "org"
        assert payload.exp == future

    def test_validate_token_expired_returns_none(self) -> None:
        """An exp claim in the real past returns None.

        Uses ``time.time()`` (real UTC, matching PyJWT's internal clock)
        to compute a reliably-past ``exp`` in any host timezone. The B1
        TZ bug in ``create_access_token`` was fixed 2026-05-12 — source
        now uses ``time.time()`` directly and the workaround note that
        used to live here is obsolete.
        """
        import time

        past = int(time.time() - 600)
        token = _make_jwt({"sub": "u-1", "role": "user", "exp": past})

        assert AuthService.validate_token(token) is None

    def test_validate_token_wrong_secret_returns_none(self) -> None:
        future = int((datetime.utcnow() + timedelta(minutes=10)).timestamp())
        token = _make_jwt(
            {"sub": "u-1", "role": "user", "exp": future},
            secret="some-other-secret-padded-to-32-chars-long",
        )
        assert AuthService.validate_token(token) is None

    def test_validate_token_malformed_returns_none(self) -> None:
        assert AuthService.validate_token("not.a.jwt") is None
        assert AuthService.validate_token("garbage") is None

    def test_validate_token_legacy_roles_list_uses_first(self) -> None:
        """Backward-compat: tokens minted before the role-string cutover
        carry `roles: [...]` instead of `role: '...'`. validate_token
        normalizes by taking the first element. Pins lines 128-131."""
        future = int((datetime.utcnow() + timedelta(minutes=10)).timestamp())
        token = _make_jwt({"sub": "u-legacy", "roles": ["admin", "analyst"], "exp": future})

        payload = AuthService.validate_token(token)
        assert payload is not None
        assert payload.role == "admin"

    def test_validate_token_legacy_empty_roles_list_falls_back_to_user(self) -> None:
        """If `roles` is present but empty, fallback role is 'user'.
        Pins line 131 (the else branch of the ternary)."""
        future = int((datetime.utcnow() + timedelta(minutes=10)).timestamp())
        token = _make_jwt({"sub": "u-legacy", "roles": [], "exp": future})

        payload = AuthService.validate_token(token)
        assert payload is not None
        assert payload.role == "user"

    def test_validate_token_missing_role_defaults_to_user(self) -> None:
        """A token with NO role and NO roles -> role defaults to 'user'.
        Pins line 132-133."""
        future = int((datetime.utcnow() + timedelta(minutes=10)).timestamp())
        token = _make_jwt({"sub": "u-noroles", "exp": future})

        payload = AuthService.validate_token(token)
        assert payload is not None
        assert payload.role == "user"

    def test_validate_token_missing_sub_defaults_to_empty(self) -> None:
        """A token with no `sub` claim gets sub=''. Pins line 135."""
        future = int((datetime.utcnow() + timedelta(minutes=10)).timestamp())
        token = _make_jwt({"role": "user", "exp": future})

        payload = AuthService.validate_token(token)
        assert payload is not None
        assert payload.sub == ""

    def test_validate_token_missing_realm_defaults_to_org(self) -> None:
        """No `realm` claim -> default 'org'. Pins line 138."""
        future = int((datetime.utcnow() + timedelta(minutes=10)).timestamp())
        token = _make_jwt({"sub": "u-1", "role": "user", "exp": future})

        payload = AuthService.validate_token(token)
        assert payload is not None
        assert payload.realm == "org"

    def test_validate_token_unknown_realm_returns_none(self) -> None:
        """Phase 4 Batch 4.4 (audit B2): a token carrying an unknown
        realm value (e.g. legacy 'tenant') is rejected gracefully by
        validate_token rather than crashing the caller."""
        future = int((datetime.utcnow() + timedelta(minutes=10)).timestamp())
        token = _make_jwt({"sub": "u-1", "role": "user", "realm": "tenant", "exp": future})

        assert AuthService.validate_token(token) is None
