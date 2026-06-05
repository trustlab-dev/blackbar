"""Integration tests for `src.auth.magic_link_routes` (RFC-007).

Phase 2.1.C. Target ≥80% line coverage on src.auth.magic_link_routes.

Scope vs. service-level tests:
- Service-level: `tests/auth/test_magic_link_service.py` covers
  MagicLinkService internals (request, verify, hash, rate-limit) with
  mocked repos.
- Route-level (this file): HTTP-layer concerns: request validation,
  response shapes, status codes, rate-limit translation to HTTP 429,
  middleware bypass via the `/api/v1/auth/public` prefix.

Reality calibration:
- Path prefix: `/auth/public/magic-link` under api_router (`/api/v1`)
  -> full path `/api/v1/auth/public/magic-link/...`. This prefix IS in
  AuthMiddleware's public_routes_prefix list, so the routes are
  reachable WITHOUT a token (as the magic-link flow requires).
- Both endpoints depend on `get_magic_link_service`, which builds the
  service via `get_shared_database()`. We override that dependency with
  a stub that returns a service backed by mocks — sidesteps motor loop
  binding and lets us test pure route-level behaviour.
- The `email_service` is module-global; we monkeypatch
  `src.auth.magic_link_routes.email_service.send_magic_link` to avoid
  real SendGrid calls.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.auth.magic_link_routes import get_magic_link_service
from src.auth.magic_link_service import MagicLinkService
from src.public_users.models import PublicUser


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


def _make_mock_service(
    *,
    request_returns: tuple[str, datetime] | None = None,
    request_raises: Exception | None = None,
    verify_returns: PublicUser | None = None,
    issue_token_returns: str = "fake-jwt-token",
) -> AsyncMock:
    """Build an AsyncMock that conforms to MagicLinkService's interface."""
    svc = AsyncMock(spec=MagicLinkService)
    if request_raises is not None:
        svc.request_magic_link.side_effect = request_raises
    else:
        if request_returns is None:
            request_returns = (
                "fake-token-abc",
                datetime.utcnow() + timedelta(minutes=15),
            )
        svc.request_magic_link.return_value = request_returns
    svc.verify_magic_link.return_value = verify_returns
    # issue_token is sync (not async); use MagicMock for that one
    svc.issue_token = MagicMock(return_value=issue_token_returns)
    return svc


@pytest.fixture
def override_magic_link_service(app):
    """Yield a callable to install a dependency override. Cleans up after."""

    def _install(svc: AsyncMock) -> None:
        app.dependency_overrides[get_magic_link_service] = lambda: svc

    yield _install
    app.dependency_overrides.pop(get_magic_link_service, None)


@pytest.fixture
def stub_email_send(monkeypatch: pytest.MonkeyPatch):
    """Stub out `email_service.send_magic_link` so no SMTP/SendGrid call
    is attempted. Returns a MagicMock so tests can inspect call args."""
    import src.auth.magic_link_routes as _mod

    mock = MagicMock(return_value=True)
    monkeypatch.setattr(_mod.email_service, "send_magic_link", mock)
    return mock


# ---------------------------------------------------------------------------
# POST /auth/public/magic-link/request
# ---------------------------------------------------------------------------


class TestRequestMagicLink:
    async def test_request_happy_path_returns_200(
        self, app, override_magic_link_service, stub_email_send
    ) -> None:
        svc = _make_mock_service()
        override_magic_link_service(svc)

        async with _client(app) as c:
            r = await c.post(
                "/api/v1/auth/public/magic-link/request",
                json={"email": "user@example.com"},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "Magic link sent" in body["message"]
        assert body["expires_in"] == 900
        # The service was invoked with the normalised lowercase email.
        svc.request_magic_link.assert_awaited_once()
        kwargs = svc.request_magic_link.await_args.kwargs
        assert kwargs["email"] == "user@example.com"

    async def test_request_normalizes_uppercase_email(
        self, app, override_magic_link_service, stub_email_send
    ) -> None:
        """Pins `MagicLinkRequest.normalize_email` validator: input
        'CASE@Example.com' -> 'case@example.com' before reaching the
        service. This guards against rate-limit bypass via case
        permutations."""
        svc = _make_mock_service()
        override_magic_link_service(svc)

        async with _client(app) as c:
            r = await c.post(
                "/api/v1/auth/public/magic-link/request",
                json={"email": "CASE@Example.com"},
            )
        assert r.status_code == 200
        kwargs = svc.request_magic_link.await_args.kwargs
        assert kwargs["email"] == "case@example.com"

    async def test_request_rate_limit_returns_429(
        self, app, override_magic_link_service, stub_email_send
    ) -> None:
        """Service raising ValueError('RATE_LIMIT_EXCEEDED') -> 429 with a
        structured detail dict (not the global error envelope, since the
        route raises HTTPException with a dict detail directly)."""
        svc = _make_mock_service(request_raises=ValueError("RATE_LIMIT_EXCEEDED"))
        override_magic_link_service(svc)

        async with _client(app) as c:
            r = await c.post(
                "/api/v1/auth/public/magic-link/request",
                json={"email": "limited@example.com"},
            )
        assert r.status_code == 429, r.text
        # The route raises HTTPException(detail={...}) with a dict —
        # the error_handler short-circuits when detail already has 'error'.
        # In this case detail is {"error": "rate_limit_exceeded", ...},
        # so the structured payload is returned verbatim.
        body = r.json()
        # The route's detail dict has an 'error' key, which the global
        # http_exception_handler treats as already-formatted and returns
        # verbatim.
        assert body["error"] == "rate_limit_exceeded"
        assert body["retry_after"] == 3600

    async def test_request_service_value_error_returns_400(
        self, app, override_magic_link_service, stub_email_send
    ) -> None:
        """A non-rate-limit ValueError from the service -> 400 with str(e)."""
        svc = _make_mock_service(request_raises=ValueError("Some other validation"))
        override_magic_link_service(svc)

        async with _client(app) as c:
            r = await c.post(
                "/api/v1/auth/public/magic-link/request",
                json={"email": "user@example.com"},
            )
        assert r.status_code == 400
        body = r.json()
        assert body["error"]["code"] == "HTTP_400"
        assert "Some other validation" in body["error"]["message"]

    async def test_request_service_unexpected_error_returns_500(
        self, app, override_magic_link_service, stub_email_send
    ) -> None:
        """An unexpected non-ValueError from the service -> 500 generic
        retry message. Pins lines 133-138."""
        svc = _make_mock_service(request_raises=RuntimeError("oops"))
        override_magic_link_service(svc)

        async with _client(app) as c:
            r = await c.post(
                "/api/v1/auth/public/magic-link/request",
                json={"email": "user@example.com"},
            )
        assert r.status_code == 500

    async def test_request_email_send_failure_is_swallowed(
        self, app, override_magic_link_service, monkeypatch
    ) -> None:
        """email_service.send_magic_link returning False is logged but
        does NOT fail the request — the token was already stored.
        Pins lines 113-115."""
        svc = _make_mock_service()
        import src.auth.magic_link_routes as _mod

        monkeypatch.setattr(_mod.email_service, "send_magic_link", MagicMock(return_value=False))
        override_magic_link_service(svc)

        async with _client(app) as c:
            r = await c.post(
                "/api/v1/auth/public/magic-link/request",
                json={"email": "noemail@example.com"},
            )
        assert r.status_code == 200

    async def test_request_invalid_payload_returns_422(
        self, app, override_magic_link_service, stub_email_send
    ) -> None:
        """A missing email field -> Pydantic validation failure -> 422.

        Uses a missing-field (not an invalid-format) to avoid the
        pre-existing source bug where validation_exception_handler
        crashes on JSON-serializing ValueError objects from custom
        validators. Logged for audit Section 11."""
        svc = _make_mock_service()
        override_magic_link_service(svc)

        async with _client(app) as c:
            r = await c.post(
                "/api/v1/auth/public/magic-link/request",
                json={},  # missing required `email`
            )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST /auth/public/magic-link/verify
# ---------------------------------------------------------------------------


class TestVerifyMagicLink:
    @pytest.fixture
    def sample_user(self) -> PublicUser:
        return PublicUser(
            id="pub-1",
            email="verified@example.com",
            name="Verified",
            email_verified=True,
            status="active",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            request_ids=[],
        )

    async def test_verify_happy_path_returns_jwt_and_user(
        self, app, override_magic_link_service, sample_user
    ) -> None:
        svc = _make_mock_service(verify_returns=sample_user, issue_token_returns="real-jwt-here")
        override_magic_link_service(svc)

        async with _client(app) as c:
            r = await c.post(
                "/api/v1/auth/public/magic-link/verify",
                json={"token": "good-token", "email": "verified@example.com"},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["access_token"] == "real-jwt-here"
        assert body["token_type"] == "bearer"
        assert body["user"]["id"] == "pub-1"
        assert body["user"]["email"] == "verified@example.com"
        assert body["user"]["email_verified"] is True

    async def test_verify_invalid_token_returns_400(self, app, override_magic_link_service) -> None:
        """Service returns None -> 400 with structured 'invalid_token' detail."""
        svc = _make_mock_service(verify_returns=None)
        override_magic_link_service(svc)

        async with _client(app) as c:
            r = await c.post(
                "/api/v1/auth/public/magic-link/verify",
                json={"token": "bad-token", "email": "verified@example.com"},
            )
        assert r.status_code == 400
        body = r.json()
        # detail is a dict with 'error' key -> bypasses the wrap
        assert body["error"] == "invalid_token"
        assert "expired" in body["message"]

    async def test_verify_unexpected_exception_returns_500(
        self, app, override_magic_link_service
    ) -> None:
        """A non-HTTPException from the service -> 500. Pins lines 183-188."""
        svc = AsyncMock(spec=MagicLinkService)
        svc.verify_magic_link.side_effect = RuntimeError("boom")
        override_magic_link_service(svc)

        async with _client(app) as c:
            r = await c.post(
                "/api/v1/auth/public/magic-link/verify",
                json={"token": "any", "email": "verified@example.com"},
            )
        assert r.status_code == 500

    async def test_verify_normalizes_email_to_lowercase(
        self, app, override_magic_link_service, sample_user
    ) -> None:
        """Pins `VerifyRequest.normalize_email` validator."""
        svc = _make_mock_service(verify_returns=sample_user)
        override_magic_link_service(svc)

        async with _client(app) as c:
            r = await c.post(
                "/api/v1/auth/public/magic-link/verify",
                json={"token": "t", "email": "VERIFIED@example.com"},
            )
        assert r.status_code == 200
        # Service was invoked with the lowercased email.
        kwargs = svc.verify_magic_link.await_args.kwargs
        assert kwargs["email"] == "verified@example.com"


# ---------------------------------------------------------------------------
# GET /auth/public/magic-link/health
# ---------------------------------------------------------------------------


class TestHealth:
    async def test_health_returns_200(self, app) -> None:
        async with _client(app) as c:
            r = await c.get("/api/v1/auth/public/magic-link/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "healthy"
        assert body["service"] == "magic_link_auth"


# ---------------------------------------------------------------------------
# POST /auth/public/demo-login (env-gated; shipped in 006ae30)
# ---------------------------------------------------------------------------


class TestDemoLogin:
    """The demo-login endpoint is gated by the BLACKBAR_DEMO_MODE env var.
    When the env var is absent or anything other than "true", the endpoint
    returns 404 (no information disclosure that it exists). When enabled,
    it upserts the Jordan Park public user, marks email_verified=true, and
    issues a public-realm JWT."""

    async def test_returns_404_when_flag_unset(
        self, app, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("BLACKBAR_DEMO_MODE", raising=False)
        async with _client(app) as c:
            r = await c.post("/api/v1/auth/public/demo-login")
        assert r.status_code == 404

    async def test_returns_404_when_flag_is_false(
        self, app, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BLACKBAR_DEMO_MODE", "false")
        async with _client(app) as c:
            r = await c.post("/api/v1/auth/public/demo-login")
        assert r.status_code == 404

    async def test_returns_404_for_non_true_values(
        self, app, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only the literal string "true" (case-insensitive) enables
        the endpoint. Anything ambiguous — "1", "yes", "on", " ", etc. —
        is treated as off and the route returns 404."""
        for value in ("1", "yes", "on", " ", "", "true ", " true"):
            monkeypatch.setenv("BLACKBAR_DEMO_MODE", value)
            async with _client(app) as c:
                r = await c.post("/api/v1/auth/public/demo-login")
            assert r.status_code == 404, (
                f"BLACKBAR_DEMO_MODE={value!r} should NOT enable demo-login"
            )

    async def test_returns_token_when_flag_true(
        self,
        app,
        monkeypatch: pytest.MonkeyPatch,
        override_magic_link_service,
    ) -> None:
        """When demo mode is on, the endpoint returns a JWT + user
        payload that matches the Jordan Park persona."""
        monkeypatch.setenv("BLACKBAR_DEMO_MODE", "true")
        # Build a stub service that upsert+token-issue can both run
        # against. The real upsert path uses the users_repo + collection;
        # we mock those minimally.
        from src.auth.magic_link_service import MagicLinkService

        users_repo = AsyncMock()
        now = datetime.utcnow()
        existing_user = PublicUser(
            id="jp-demo-id",
            email="jordan.park@example.org",
            name="Jordan Park",
            email_verified=True,
            created_at=now,
            updated_at=now,
        )
        users_repo.get_by_email.return_value = existing_user
        users_repo.collection = MagicMock()
        users_repo.collection.update_one = AsyncMock()
        users_repo.update_last_login = AsyncMock()

        svc = MagicLinkService(users_repo=users_repo, tokens_repo=AsyncMock())
        # Don't go through the real JWT issuance machinery — stub the
        # method so we get a deterministic token in the response.
        svc.issue_token = MagicMock(return_value="demo-jwt-token")  # type: ignore[method-assign]
        override_magic_link_service(svc)

        async with _client(app) as c:
            r = await c.post("/api/v1/auth/public/demo-login")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["access_token"] == "demo-jwt-token"
        assert body["token_type"] == "bearer"
        assert body["user"]["email"] == "jordan.park@example.org"
        assert body["user"]["name"] == "Jordan Park"
        assert body["user"]["email_verified"] is True

    async def test_creates_user_when_missing(
        self,
        app,
        monkeypatch: pytest.MonkeyPatch,
        override_magic_link_service,
    ) -> None:
        """First call on a fresh DB creates the Jordan Park public user
        rather than 500'ing."""
        monkeypatch.setenv("BLACKBAR_DEMO_MODE", "true")
        from src.auth.magic_link_service import MagicLinkService

        users_repo = AsyncMock()
        # First lookup returns None (no user yet); after .create() we
        # return the newly-made user from the create call itself.
        now = datetime.utcnow()
        new_user = PublicUser(
            id="jp-fresh-id",
            email="jordan.park@example.org",
            name="Jordan Park",
            email_verified=False,
            created_at=now,
            updated_at=now,
        )
        users_repo.get_by_email.return_value = None
        users_repo.create.return_value = new_user
        users_repo.collection = MagicMock()
        users_repo.collection.update_one = AsyncMock()
        users_repo.update_last_login = AsyncMock()

        svc = MagicLinkService(users_repo=users_repo, tokens_repo=AsyncMock())
        svc.issue_token = MagicMock(return_value="demo-jwt-token")  # type: ignore[method-assign]
        override_magic_link_service(svc)

        async with _client(app) as c:
            r = await c.post("/api/v1/auth/public/demo-login")
        assert r.status_code == 200, r.text
        # Verify .create() was called with the demo persona
        users_repo.create.assert_awaited_once()
        created_arg = users_repo.create.await_args.args[0]
        assert created_arg.email == "jordan.park@example.org"
        assert created_arg.name == "Jordan Park"
