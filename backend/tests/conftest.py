"""
Shared pytest fixtures for BlackBar backend tests.

Spins up an ephemeral MongoDB via testcontainers (session-scoped) and
provides a per-test database that's reset between tests for full
isolation. Authenticated httpx.AsyncClient factory and external-service
mocks (LLM, SMTP) live here too.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
import respx
from fastapi.testclient import TestClient
from httpx import ASGITransport
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from testcontainers.mongodb import MongoDbContainer

# Sample fixtures directory (populated in Phase 1 Task 1.16)
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "redaction-samples"


# ---------------------------------------------------------------------------
# Settings overrides
# ---------------------------------------------------------------------------


def _stable_fernet_key() -> str:
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


def pytest_configure(config: pytest.Config) -> None:
    """Set test env BEFORE any test collection / import of `src.*`.

    `src.config`, `src.database`, and `src.core.database` all read env vars at
    module-import time (notably MONGODB_URI and JWT_SECRET). We set safe
    defaults here so collection of test modules that import `src.*` does not
    blow up. The real MONGODB_URI is patched in by `mongo_uri` before
    `src.main` is imported via the `app` fixture.
    """
    os.environ.setdefault("JWT_SECRET", "test-secret-" + secrets.token_hex(16))
    os.environ.setdefault("JWT_EXPIRATION", "60")
    os.environ.setdefault("LLM_API_KEY_ENCRYPTION_KEY", _stable_fernet_key())
    os.environ.setdefault("ENVIRONMENT", "test")
    os.environ.setdefault("MONGODB_DB_NAME", "blackbar_test")
    os.environ.setdefault("ALLOWED_ORIGINS", "http://testserver")
    # MONGODB_URI gets overwritten by `mongo_uri` fixture once the
    # testcontainer starts; this placeholder prevents import-time crashes.
    os.environ.setdefault("MONGODB_URI", "mongodb://placeholder:27017/blackbar_test")


# ---------------------------------------------------------------------------
# Mongo testcontainer
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _mongo_container() -> Iterator[MongoDbContainer]:
    """One MongoDB container for the entire test session.

    Per-test isolation is handled by dropping the test DB between tests
    (see `db` fixture below), not by spinning up a fresh container each
    time — that would add ~5s per test.
    """
    with MongoDbContainer("mongo:7.0") as mongo:
        yield mongo


@pytest.fixture(scope="session")
def mongo_uri(_mongo_container: MongoDbContainer) -> str:
    """Connection URI exposed to the test process and the app."""
    uri = _mongo_container.get_connection_url()
    os.environ["MONGODB_URI"] = uri
    # If `src.core.database` was already imported with the placeholder URI
    # (e.g. by a unit test that doesn't need the testcontainer), reset its
    # cached client so subsequent integration tests pick up the real URI.
    try:
        from src.core import database as _db_mod

        _db_mod._client = None  # type: ignore[attr-defined]
        # `src.config.MONGODB_URI` is a frozen module-level constant captured
        # at import time; rebind it so any code path that re-reads it sees
        # the live URI.
        import src.config as _cfg

        _cfg.MONGODB_URI = uri
        _cfg.config.MONGODB_URI = uri
    except Exception:
        # If src.* has not yet been imported, the lazy `app` fixture will
        # pick up the live env var on first import.
        pass
    return uri


@pytest_asyncio.fixture
async def db(mongo_uri: str) -> AsyncIterator[AsyncIOMotorDatabase]:
    """Per-test database handle. Dropped after each test for isolation.

    Phase 2.10 fix: AsyncIOMotorClient wraps an internal sync MongoClient
    whose `__del__` raises a ResourceWarning if `close()` wasn't called.
    Calling `client.close()` on the motor wrapper invokes the underlying
    `MongoClient.close()` synchronously — but pytest's GC may run AFTER
    the event loop has closed, so the warning surfaces at session teardown
    as a PytestUnraisableExceptionWarning. Under `filterwarnings = error`
    in pyproject.toml, this is fatal. Force a GC pass here to make the
    `__del__` run while the loop is still alive.
    """
    client = AsyncIOMotorClient(mongo_uri)
    db_name = os.environ["MONGODB_DB_NAME"]
    try:
        yield client[db_name]
    finally:
        try:
            await client.drop_database(db_name)
        finally:
            client.close()
            # Force GC so MongoClient.__del__ runs immediately, not at
            # session teardown when the loop is closed.
            import gc as _gc

            _gc.collect()


# ---------------------------------------------------------------------------
# FastAPI TestClient
# ---------------------------------------------------------------------------


@pytest.fixture
def app(mongo_uri: str):  # type: ignore[no-untyped-def]
    """Importing `src.main` lazily so the env overrides above apply first.

    Depends on `mongo_uri` to guarantee MONGODB_URI is set to the live
    testcontainer URL BEFORE `src.main` (and its import-chain into
    `src.core.database`) runs.
    """
    from src.main import app as fastapi_app

    return fastapi_app


@pytest.fixture
def client(app):  # type: ignore[no-untyped-def]
    """Unauthenticated TestClient."""
    return TestClient(app)


@pytest_asyncio.fixture
async def authed_client_factory(
    app, db: AsyncIOMotorDatabase
) -> AsyncIterator:  # type: ignore[no-untyped-def]
    """Returns a callable that issues a JWT for a freshly-seeded user with the
    requested role and returns an `httpx.AsyncClient` (driving the ASGI app
    via `ASGITransport`) with the `Authorization: Bearer ...` header pre-set.

    Seed pattern replicated from `src.auth.routes` user-management code:
    create the user via `UsersRepository.create(UserCreate, password_hash)`,
    then patch the role onto the users collection directly (UserCreate has
    no `role` field; role lives on the DB record). JWT is minted via
    `AuthService.issue_token(user)`.

    Audit Section 11 finding I1: this fixture previously returned a
    `TestClient`, which spawns its own asyncio loop per request and breaks
    motor collection bindings captured on the pytest-asyncio fixture loop.
    `httpx.AsyncClient` + `ASGITransport(app=app)` shares the fixture loop,
    so route handlers' motor reads/writes bind correctly.

    Clients are tracked and closed automatically at test teardown, so tests
    don't have to wrap the returned client in `async with`:

        async def test_thing(authed_client_factory):
            client = await authed_client_factory(role="analyst")
            r = await client.get("/api/v1/cases/")
            ...
    """
    from src.auth.auth_service import AuthService
    from src.users.models import UserCreate
    from src.users.repository import UsersRepository

    repo = UsersRepository(db)
    clients: list[httpx.AsyncClient] = []

    async def _make(
        role: str = "user",
        email: str | None = None,
        name: str | None = None,
        password: str = "test-password-1234",
    ) -> httpx.AsyncClient:
        nonlocal_email = email or f"{role}-{secrets.token_hex(4)}@example.test"
        nonlocal_name = name or f"Test {role.title()}"
        password_hash = AuthService.hash_password(password)

        # Step 1: create user via the canonical repository path
        user_create = UserCreate(email=nonlocal_email, name=nonlocal_name, password=password)
        user = await repo.create(user_create, password_hash)

        # Step 2: patch role (UserCreate has no `role` field; this mirrors
        # what `src.auth.routes.update_user` does — direct collection write).
        if role != "user":
            await db.users.update_one({"id": user.id}, {"$set": {"role": role}})
            user.role = role

        # Step 3: mint JWT using the production auth service
        auth_service = AuthService(repo)
        token = await auth_service.issue_token(user)

        client = httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {token}"},
        )
        clients.append(client)
        return client

    try:
        yield _make
    finally:
        for c in clients:
            await c.aclose()


# ---------------------------------------------------------------------------
# External service mocks
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_openai(respx_mock: respx.MockRouter) -> respx.MockRouter:
    """Stubs OpenAI's chat-completions endpoint for tests that don't care
    about the actual response — returns a canned successful response.
    Individual tests can override by re-mocking specific routes."""
    respx_mock.post("https://api.openai.com/v1/chat/completions").respond(
        json={
            "id": "test",
            "object": "chat.completion",
            "model": "gpt-4o-mini",
            "choices": [
                {
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )
    return respx_mock


@pytest.fixture
def mock_anthropic(respx_mock: respx.MockRouter) -> respx.MockRouter:
    respx_mock.post("https://api.anthropic.com/v1/messages").respond(
        json={
            "id": "test",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "ok"}],
            "model": "claude-3-5-sonnet-20241022",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    )
    return respx_mock


@pytest.fixture
def mock_sendgrid(respx_mock: respx.MockRouter) -> respx.MockRouter:
    respx_mock.post("https://api.sendgrid.com/v3/mail/send").respond(202)
    return respx_mock


# ---------------------------------------------------------------------------
# Sample document fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_pdf_path() -> Path:
    """Path to a small synthetic FOIPPA test document for OCR / redaction tests."""
    return FIXTURES_DIR / "FOIPPA_Test_Document.docx"


@pytest.fixture
def sample_eml_path() -> Path:
    return FIXTURES_DIR / "test.eml"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR
