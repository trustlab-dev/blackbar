"""Tests for Magic Link Authentication Service (RFC-007).

Phase 2.1.B service-level tests. Covers all branches of
src.auth.magic_link_service.MagicLinkService to 100% line+branch coverage.

The original (pre-single-tenant) version of this file lived at
backend/tests/test_magic_link_service.py and assumed a `tenant_id`
argument on `request_magic_link` / `verify_magic_link`. The single-tenant
cleanup pass removed that parameter; this rewrite updates the existing
happy-path tests to the post-cleanup API and adds the gap-fillers
called out in the Phase 2.1.B sub-plan:
- token expiry (freezegun)
- single-use enforcement (already had a basic test; pinned more tightly)
- email content rendering (n/a — MagicLinkService doesn't render email;
  the routes layer does. The Phase 2.1 audit's note was about the
  *welcome* email rendering, which lives in WelcomeEmailService and is
  covered in test_activation_service.py)
- unknown-email enumeration policy (verify_magic_link returns None
  silently for unknown emails — pinned via test_verify_magic_link_no_token
  and test_verify_magic_link_user_not_found_after_token_lookup)

The service has no email-sending responsibilities itself; the routes
layer triggers SendGrid. Email-rendering / SendGrid mocks belong in the
route tests (Batch 2.1.C).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from freezegun import freeze_time

from src.auth.magic_link_service import MagicLinkService
from src.public_users.models import MagicLinkToken, PublicUser

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_users_repo() -> AsyncMock:
    """Mock PublicUsersRepository."""
    return AsyncMock()


@pytest.fixture
def mock_tokens_repo() -> AsyncMock:
    """Mock MagicLinkTokensRepository."""
    return AsyncMock()


@pytest.fixture
def magic_link_service(mock_users_repo: AsyncMock, mock_tokens_repo: AsyncMock) -> MagicLinkService:
    return MagicLinkService(
        users_repo=mock_users_repo,
        tokens_repo=mock_tokens_repo,
        token_expiration_minutes=15,
    )


@pytest.fixture
def sample_user() -> PublicUser:
    return PublicUser(
        id="user-123",
        email="test@example.com",
        name="Test User",
        email_verified=True,
        status="active",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        request_ids=[],
    )


# ---------------------------------------------------------------------------
# Token generation / hashing primitives
# ---------------------------------------------------------------------------


class TestTokenGeneration:
    """Pure-function helpers — generate / hash / verify token."""

    def test_generate_token_is_unique(self, magic_link_service: MagicLinkService) -> None:
        t1 = magic_link_service.generate_token()
        t2 = magic_link_service.generate_token()
        assert t1 != t2

    def test_generate_token_url_safe_length(self, magic_link_service: MagicLinkService) -> None:
        token = magic_link_service.generate_token()
        assert isinstance(token, str)
        # secrets.token_urlsafe(32) -> 43 URL-safe chars (without padding)
        assert len(token) >= 32

    def test_hash_token_format(self, magic_link_service: MagicLinkService) -> None:
        token_hash = magic_link_service.hash_token("test-token-12345")
        assert token_hash.startswith("$2b$")
        assert isinstance(token_hash, str)

    def test_verify_token_success(self, magic_link_service: MagicLinkService) -> None:
        token = "test-token-12345"
        token_hash = magic_link_service.hash_token(token)
        assert magic_link_service.verify_token(token, token_hash) is True

    def test_verify_token_failure_wrong_token(self, magic_link_service: MagicLinkService) -> None:
        token_hash = magic_link_service.hash_token("right-token")
        assert magic_link_service.verify_token("wrong-token", token_hash) is False

    def test_verify_token_handles_invalid_hash_gracefully(
        self, magic_link_service: MagicLinkService
    ) -> None:
        """A malformed bcrypt hash makes bcrypt.checkpw raise; the service
        catches the exception and returns False rather than propagating —
        defensive against corrupted DB rows. Hits lines 50-52 (except branch)."""
        assert magic_link_service.verify_token("any-token", "not-a-valid-bcrypt-hash") is False


# ---------------------------------------------------------------------------
# request_magic_link
# ---------------------------------------------------------------------------


class TestRequestMagicLink:
    """Magic link request flow."""

    @pytest.mark.asyncio
    async def test_request_magic_link_new_user_creates_user(
        self,
        magic_link_service: MagicLinkService,
        mock_users_repo: AsyncMock,
        mock_tokens_repo: AsyncMock,
    ) -> None:
        mock_users_repo.get_by_email.return_value = None
        mock_users_repo.create.return_value = AsyncMock()
        mock_tokens_repo.count_recent_requests.return_value = 0
        mock_tokens_repo.create_token.return_value = AsyncMock()

        token, expires_at = await magic_link_service.request_magic_link(
            email="newuser@example.com",
            name="New User",
            ip_address="192.168.1.1",
        )

        assert isinstance(token, str)
        assert len(token) >= 32
        assert isinstance(expires_at, datetime)
        assert expires_at > datetime.utcnow()

        # User created + token stored
        mock_users_repo.create.assert_called_once()
        mock_tokens_repo.create_token.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_magic_link_existing_user_does_not_recreate(
        self,
        magic_link_service: MagicLinkService,
        mock_users_repo: AsyncMock,
        mock_tokens_repo: AsyncMock,
        sample_user: PublicUser,
    ) -> None:
        mock_users_repo.get_by_email.return_value = sample_user
        mock_tokens_repo.count_recent_requests.return_value = 0
        mock_tokens_repo.create_token.return_value = AsyncMock()

        token, expires_at = await magic_link_service.request_magic_link(
            email=sample_user.email,
        )

        assert isinstance(token, str)
        assert isinstance(expires_at, datetime)

        # User NOT recreated
        mock_users_repo.create.assert_not_called()
        # Token still stored
        mock_tokens_repo.create_token.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_magic_link_rate_limit_raises_and_skips_create(
        self,
        magic_link_service: MagicLinkService,
        mock_tokens_repo: AsyncMock,
        mock_users_repo: AsyncMock,
    ) -> None:
        """Rate limiter at default MAGIC_LINK_RATE_LIMIT_MAX (3). Hitting it
        raises ValueError('RATE_LIMIT_EXCEEDED') BEFORE the token is created."""
        mock_tokens_repo.count_recent_requests.return_value = 3

        with pytest.raises(ValueError, match="RATE_LIMIT_EXCEEDED"):
            await magic_link_service.request_magic_link(email="rl@example.com")

        mock_tokens_repo.create_token.assert_not_called()
        mock_users_repo.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_request_magic_link_passes_audit_fields_to_repo(
        self,
        magic_link_service: MagicLinkService,
        mock_users_repo: AsyncMock,
        mock_tokens_repo: AsyncMock,
        sample_user: PublicUser,
    ) -> None:
        """Audit fields (ip_address + user_agent) propagate through to the
        token-storage call."""
        mock_users_repo.get_by_email.return_value = sample_user
        mock_tokens_repo.count_recent_requests.return_value = 0

        await magic_link_service.request_magic_link(
            email=sample_user.email,
            ip_address="10.0.0.5",
            user_agent="pytest/1.0",
        )

        call_kwargs = mock_tokens_repo.create_token.call_args.kwargs
        assert call_kwargs["ip_address"] == "10.0.0.5"
        assert call_kwargs["user_agent"] == "pytest/1.0"

    @pytest.mark.asyncio
    @freeze_time("2026-05-11 12:00:00")
    async def test_request_magic_link_expiry_uses_configured_minutes(
        self,
        mock_users_repo: AsyncMock,
        mock_tokens_repo: AsyncMock,
        sample_user: PublicUser,
    ) -> None:
        """A service constructed with token_expiration_minutes=N returns
        expires_at = now + N minutes (deterministic under freezegun)."""
        service = MagicLinkService(
            users_repo=mock_users_repo,
            tokens_repo=mock_tokens_repo,
            token_expiration_minutes=30,
        )
        mock_users_repo.get_by_email.return_value = sample_user
        mock_tokens_repo.count_recent_requests.return_value = 0

        _token, expires_at = await service.request_magic_link(email=sample_user.email)

        expected = datetime(2026, 5, 11, 12, 30, 0)
        assert expires_at == expected


# ---------------------------------------------------------------------------
# verify_magic_link
# ---------------------------------------------------------------------------


class TestVerifyMagicLink:
    """Magic link verification flow."""

    @pytest.mark.asyncio
    async def test_verify_magic_link_success(
        self,
        magic_link_service: MagicLinkService,
        mock_users_repo: AsyncMock,
        mock_tokens_repo: AsyncMock,
        sample_user: PublicUser,
    ) -> None:
        token = magic_link_service.generate_token()
        token_hash = magic_link_service.hash_token(token)

        stored_token = MagicLinkToken(
            id="token-123",
            email=sample_user.email,
            token_hash=token_hash,
            expires_at=datetime.utcnow() + timedelta(minutes=15),
            used=False,
            created_at=datetime.utcnow(),
        )
        mock_tokens_repo.get_by_email.return_value = stored_token
        mock_tokens_repo.mark_as_used.return_value = True
        mock_users_repo.get_by_email.return_value = sample_user
        mock_users_repo.update_last_login.return_value = True

        user = await magic_link_service.verify_magic_link(
            token=token,
            email=sample_user.email,
        )

        assert user is not None
        assert user.id == sample_user.id
        assert user.email == sample_user.email
        mock_tokens_repo.mark_as_used.assert_called_once_with(stored_token.id)
        mock_users_repo.update_last_login.assert_called_once()

    @pytest.mark.asyncio
    async def test_verify_magic_link_no_token_for_email(
        self,
        magic_link_service: MagicLinkService,
        mock_tokens_repo: AsyncMock,
    ) -> None:
        """Unknown email -> None silently (no enumeration). Pins the
        anti-enumeration behavior of the service layer: callers cannot
        distinguish 'no token for this email' from 'wrong token' — both
        return None without raising."""
        mock_tokens_repo.get_by_email.return_value = None

        user = await magic_link_service.verify_magic_link(
            token="any-token", email="nobody@example.com"
        )
        assert user is None

    @pytest.mark.asyncio
    async def test_verify_magic_link_wrong_token(
        self,
        magic_link_service: MagicLinkService,
        mock_tokens_repo: AsyncMock,
    ) -> None:
        correct_token = magic_link_service.generate_token()
        token_hash = magic_link_service.hash_token(correct_token)
        wrong_token = magic_link_service.generate_token()

        stored_token = MagicLinkToken(
            id="token-123",
            email="test@example.com",
            token_hash=token_hash,
            expires_at=datetime.utcnow() + timedelta(minutes=15),
            used=False,
            created_at=datetime.utcnow(),
        )
        mock_tokens_repo.get_by_email.return_value = stored_token

        user = await magic_link_service.verify_magic_link(
            token=wrong_token, email="test@example.com"
        )
        assert user is None
        mock_tokens_repo.mark_as_used.assert_not_called()

    @pytest.mark.asyncio
    async def test_verify_magic_link_expired(
        self,
        magic_link_service: MagicLinkService,
        mock_tokens_repo: AsyncMock,
    ) -> None:
        """Expired token returns None. Pins line 140-143.

        Note: the production repo's `get_by_email` filters by
        `expires_at > now`, so in normal operation a stale token wouldn't
        even reach the service's own expiry check. The service-level
        belt-and-braces check exists for clock skew / race scenarios and
        is exercised here by bypassing the repo filter via the mock."""
        token = magic_link_service.generate_token()
        token_hash = magic_link_service.hash_token(token)

        stored_token = MagicLinkToken(
            id="token-123",
            email="test@example.com",
            token_hash=token_hash,
            expires_at=datetime.utcnow() - timedelta(minutes=1),
            used=False,
            created_at=datetime.utcnow() - timedelta(minutes=16),
        )
        mock_tokens_repo.get_by_email.return_value = stored_token

        user = await magic_link_service.verify_magic_link(token=token, email="test@example.com")
        assert user is None
        mock_tokens_repo.mark_as_used.assert_not_called()

    @pytest.mark.asyncio
    async def test_verify_magic_link_expired_via_freezegun(
        self,
        magic_link_service: MagicLinkService,
        mock_tokens_repo: AsyncMock,
    ) -> None:
        """Same as test_verify_magic_link_expired, but using freezegun to
        prove deterministic time control works for the service's
        `datetime.utcnow() > expires_at` comparison."""
        token = magic_link_service.generate_token()
        token_hash = magic_link_service.hash_token(token)

        with freeze_time("2026-05-11 12:00:00"):
            expires = datetime(2026, 5, 11, 12, 10, 0)
            stored_token = MagicLinkToken(
                id="token-frozen",
                email="frozen@example.com",
                token_hash=token_hash,
                expires_at=expires,
                used=False,
                created_at=datetime(2026, 5, 11, 11, 55, 0),
            )
            mock_tokens_repo.get_by_email.return_value = stored_token

        with freeze_time("2026-05-11 12:15:00"):  # 5 min after expiry
            user = await magic_link_service.verify_magic_link(
                token=token, email="frozen@example.com"
            )
            assert user is None

    @pytest.mark.asyncio
    async def test_verify_magic_link_already_used(
        self,
        magic_link_service: MagicLinkService,
        mock_tokens_repo: AsyncMock,
    ) -> None:
        """Single-use enforcement: a token with used=True returns None."""
        token = magic_link_service.generate_token()
        token_hash = magic_link_service.hash_token(token)

        stored_token = MagicLinkToken(
            id="token-123",
            email="test@example.com",
            token_hash=token_hash,
            expires_at=datetime.utcnow() + timedelta(minutes=15),
            used=True,  # Already used
            created_at=datetime.utcnow(),
        )
        mock_tokens_repo.get_by_email.return_value = stored_token

        user = await magic_link_service.verify_magic_link(token=token, email="test@example.com")
        assert user is None
        mock_tokens_repo.mark_as_used.assert_not_called()

    @pytest.mark.asyncio
    async def test_verify_magic_link_user_not_found_after_token_lookup(
        self,
        magic_link_service: MagicLinkService,
        mock_users_repo: AsyncMock,
        mock_tokens_repo: AsyncMock,
    ) -> None:
        """The token exists and is valid, but the user record has been
        deleted between request_magic_link and verify_magic_link. The
        service returns None and logs an error — exercises the
        `if not user` branch after mark_as_used (lines 156-159)."""
        token = magic_link_service.generate_token()
        token_hash = magic_link_service.hash_token(token)
        stored_token = MagicLinkToken(
            id="token-orphan",
            email="orphan@example.com",
            token_hash=token_hash,
            expires_at=datetime.utcnow() + timedelta(minutes=15),
            used=False,
            created_at=datetime.utcnow(),
        )
        mock_tokens_repo.get_by_email.return_value = stored_token
        mock_tokens_repo.mark_as_used.return_value = True
        mock_users_repo.get_by_email.return_value = None  # user deleted

        user = await magic_link_service.verify_magic_link(token=token, email="orphan@example.com")
        assert user is None
        # Token still gets marked used (already committed) — pins behavior.
        mock_tokens_repo.mark_as_used.assert_called_once()


# ---------------------------------------------------------------------------
# issue_token (JWT issuance)
# ---------------------------------------------------------------------------


class TestIssueToken:
    """Public-user JWT issuance."""

    def test_issue_token_payload_shape(
        self, magic_link_service: MagicLinkService, sample_user: PublicUser
    ) -> None:
        """Token payload has the post-single-tenant shape: sub/email/realm/
        user_type with realm='public' and user_type='public'. No tenant_id."""
        with patch("src.auth.magic_link_service.create_access_token") as mock_create_token:
            mock_create_token.return_value = "mock-jwt-token"

            token = magic_link_service.issue_token(sample_user)

            mock_create_token.assert_called_once()
            call_args = mock_create_token.call_args[0][0]

            assert call_args["sub"] == sample_user.id
            assert call_args["email"] == sample_user.email
            assert call_args["realm"] == "public"
            assert call_args["user_type"] == "public"
            assert "tenant_id" not in call_args  # post-single-tenant
            assert token == "mock-jwt-token"

    def test_issue_token_uses_public_session_hours_env(
        self,
        magic_link_service: MagicLinkService,
        sample_user: PublicUser,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """PUBLIC_USER_SESSION_HOURS env var controls expires_delta."""
        monkeypatch.setenv("PUBLIC_USER_SESSION_HOURS", "2")
        with patch("src.auth.magic_link_service.create_access_token") as mock_create_token:
            mock_create_token.return_value = "tok"
            magic_link_service.issue_token(sample_user)
            kwargs = mock_create_token.call_args.kwargs
            assert kwargs["expires_delta"] == timedelta(hours=2)


# ---------------------------------------------------------------------------
# cleanup_expired_tokens
# ---------------------------------------------------------------------------


class TestCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_expired_tokens_returns_count(
        self, magic_link_service: MagicLinkService, mock_tokens_repo: AsyncMock
    ) -> None:
        mock_tokens_repo.cleanup_expired.return_value = 5

        deleted = await magic_link_service.cleanup_expired_tokens()

        assert deleted == 5
        mock_tokens_repo.cleanup_expired.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_expired_tokens_zero_silent(
        self, magic_link_service: MagicLinkService, mock_tokens_repo: AsyncMock
    ) -> None:
        """If nothing was deleted, the service still returns 0 — no log
        spam (the `if deleted > 0` branch is exercised here, hitting the
        false leg at line 202)."""
        mock_tokens_repo.cleanup_expired.return_value = 0

        deleted = await magic_link_service.cleanup_expired_tokens()
        assert deleted == 0
