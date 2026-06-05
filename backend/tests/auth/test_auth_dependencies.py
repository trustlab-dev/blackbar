"""Tests for `src.auth.dependencies` (public-user / magic-link JWT helpers).

Phase 2.1.C. Covers 100% of src.auth.dependencies:
- `get_current_user_public`: validates Bearer JWT for public users
- `get_optional_public_user`: same but optional (returns None on failure)

Reality calibration vs. the plan:
- `get_current_user_public` enforces `user_type == "public"`. After
  Phase 4 Batch 4.4 (audit B6) the source preserves the intentional 403
  HTTPException raised for non-public realms; the prior broad-except
  bug that swallowed it into 401 has been fixed. Tests assert 403.
- The function uses `HTTPBearer()` (not `OAuth2PasswordBearer`); credentials
  are `HTTPAuthorizationCredentials(scheme, credentials)`. We construct
  them directly for unit-style tests (no need for FastAPI app + TestClient).
- `get_optional_public_user` catches `HTTPException` and returns None for
  ANY raised exception path. Tests verify both the no-credentials branch
  (returns None immediately) and the invalid-token branch (returns None
  after wrapping `get_current_user_public`).
- There is no DB lookup in these dependencies — they're pure JWT validation.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from src.auth.dependencies import (
    get_current_user_public,
    get_optional_public_user,
)
from src.config import ALGORITHM, JWT_SECRET


def _credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _mint(payload: dict, secret: str = JWT_SECRET) -> str:
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def _future_exp(minutes: int = 60) -> int:
    return int((datetime.utcnow() + timedelta(minutes=minutes)).timestamp())


# ---------------------------------------------------------------------------
# get_current_user_public — happy + auth-failure paths
# ---------------------------------------------------------------------------


class TestGetCurrentUserPublic:
    async def test_valid_public_token_returns_user_dict(self) -> None:
        """Happy path: a well-formed public-realm token -> user dict."""
        token = _mint(
            {
                "sub": "pub-user-1",
                "email": "alice@public.example",
                "user_type": "public",
                "exp": _future_exp(),
            }
        )
        result = await get_current_user_public(_credentials(token))

        assert result == {
            "user_id": "pub-user-1",
            "email": "alice@public.example",
            "user_type": "public",
        }

    async def test_missing_sub_raises_401(self) -> None:
        """Token without `sub` -> 401 'Could not validate credentials'.
        Pins lines 52-54."""
        token = _mint({"email": "x@y.test", "user_type": "public", "exp": _future_exp()})
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_public(_credentials(token))
        assert exc_info.value.status_code == 401

    async def test_missing_email_raises_401(self) -> None:
        """Token without `email` -> 401. Pins line 52 (second clause)."""
        token = _mint({"sub": "u-1", "user_type": "public", "exp": _future_exp()})
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_public(_credentials(token))
        assert exc_info.value.status_code == 401

    async def test_non_public_user_type_raises_403(self) -> None:
        """Phase 4 Batch 4.4 (audit B6): the intentional 403 raise inside
        the try-block now reaches the caller. Previously the broad
        `except Exception` swallowed it into a 401; the source now
        catches `HTTPException` first and re-raises.

        Test flipped from the prior `_raises_401` characterization."""
        token = _mint(
            {
                "sub": "u-1",
                "email": "a@b.test",
                "user_type": "internal",
                "exp": _future_exp(),
            }
        )
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_public(_credentials(token))
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "This endpoint is for public users only"

    async def test_missing_user_type_raises_403(self) -> None:
        """A token with NO user_type claim hits the same 403 branch as
        an explicit non-public user_type; Phase 4 Batch 4.4 (audit B6)
        preserves the 403 status code."""
        token = _mint({"sub": "u-1", "email": "a@b.test", "exp": _future_exp()})
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_public(_credentials(token))
        assert exc_info.value.status_code == 403

    async def test_expired_token_raises_401(self) -> None:
        """An exp claim in the past -> JWTError -> 401. Pins lines 69-71.

        Uses `time.time() - N` for a reliable past timestamp across
        timezones (same pattern as test_auth_service.py — see the
        utcnow-to-timestamp note there)."""
        import time

        past = int(time.time() - 600)
        token = _mint(
            {
                "sub": "u-1",
                "email": "a@b.test",
                "user_type": "public",
                "exp": past,
            }
        )
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_public(_credentials(token))
        assert exc_info.value.status_code == 401

    async def test_wrong_secret_raises_401(self) -> None:
        """Token signed with a different secret -> JWTError -> 401."""
        token = _mint(
            {
                "sub": "u-1",
                "email": "a@b.test",
                "user_type": "public",
                "exp": _future_exp(),
            },
            secret="totally-different-secret-padded-out-to-be-long-enough",
        )
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_public(_credentials(token))
        assert exc_info.value.status_code == 401

    async def test_malformed_token_raises_401(self) -> None:
        """Garbage that isn't a JWT -> JWTError -> 401."""
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_public(_credentials("not.a.jwt"))
        assert exc_info.value.status_code == 401

    async def test_unexpected_exception_raises_401(self) -> None:
        """The catch-all `except Exception` (lines 72-74) reaches the same
        credentials_exception. Trigger by passing credentials whose
        `credentials` attr raises on access — proves the broad guard.

        Simpler: jwt.decode with token=None raises TypeError (not JWTError),
        which is caught by the broad `except Exception` branch."""

        class BadCred:
            scheme = "Bearer"

            @property
            def credentials(self):  # noqa: ANN201
                raise RuntimeError("boom")

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_public(BadCred())  # type: ignore[arg-type]
        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# get_optional_public_user — None on failure, dict on success
# ---------------------------------------------------------------------------


class TestGetOptionalPublicUser:
    async def test_no_credentials_returns_none(self) -> None:
        """When the Bearer header is absent (credentials=None), the optional
        helper short-circuits to None. Pins lines 86-87."""
        result = await get_optional_public_user(credentials=None)
        assert result is None

    async def test_valid_token_returns_user(self) -> None:
        """Happy path through the wrapper -> same dict as
        get_current_user_public would return."""
        token = _mint(
            {
                "sub": "u-2",
                "email": "x@y.test",
                "user_type": "public",
                "exp": _future_exp(),
            }
        )
        result = await get_optional_public_user(credentials=_credentials(token))
        assert result == {
            "user_id": "u-2",
            "email": "x@y.test",
            "user_type": "public",
        }

    async def test_invalid_token_returns_none(self) -> None:
        """A malformed token raises HTTPException inside the wrapped helper,
        which the optional wrapper catches and converts to None.
        Pins lines 90-92."""
        result = await get_optional_public_user(credentials=_credentials("garbage"))
        assert result is None

    async def test_expired_token_returns_none(self) -> None:
        """Expired token -> 401 -> caught -> None."""
        import time

        past = int(time.time() - 600)
        token = _mint(
            {
                "sub": "u-3",
                "email": "z@y.test",
                "user_type": "public",
                "exp": past,
            }
        )
        result = await get_optional_public_user(credentials=_credentials(token))
        assert result is None

    async def test_non_public_user_returns_none(self) -> None:
        """A token with user_type != 'public' raises 403 inside the wrapped
        helper, which the optional wrapper catches and converts to None.
        Pins the HTTPException catch on line 91 against a 403 (not 401)."""
        token = _mint(
            {
                "sub": "u-4",
                "email": "i@y.test",
                "user_type": "internal",
                "exp": _future_exp(),
            }
        )
        result = await get_optional_public_user(credentials=_credentials(token))
        assert result is None
