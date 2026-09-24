"""Unit tests for src.auth.security.

Pure-unit tests (no DB, no FastAPI). Cover the bcrypt password helpers and
the create_access_token JWT helper. Phase 2.1.A per
docs/superpowers/plans/2026-05-11-phase-2-1-auth-tests.md.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import jwt
import pytest
from freezegun import freeze_time

from src.auth.security import (
    PasswordTooLongError,
    create_access_token,
    hash_password,
    password_policy_error,
    verify_password,
)
from src.config import ACCESS_TOKEN_EXPIRE_MINUTES, ALGORITHM, JWT_SECRET

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# hash_password / verify_password
# ---------------------------------------------------------------------------


def test_hash_password_returns_string() -> None:
    h = hash_password("hunter2")
    assert isinstance(h, str)
    # bcrypt hashes start with $2b$ (or $2a$/$2y$); confirm we got a real hash
    # and not, say, the plaintext echoed back.
    assert h.startswith("$2")
    assert h != "hunter2"


def test_hash_password_different_each_call() -> None:
    """bcrypt embeds a random salt per hash; same plaintext -> different output."""
    a = hash_password("same-password")
    b = hash_password("same-password")
    assert a != b


def test_verify_password_accepts_correct_password() -> None:
    h = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", h) is True


def test_verify_password_rejects_wrong_password() -> None:
    h = hash_password("right-one")
    assert verify_password("wrong-one", h) is False


def test_verify_password_rejects_empty_password() -> None:
    h = hash_password("non-empty")
    assert verify_password("", h) is False


def test_hash_password_handles_unicode() -> None:
    """Non-ASCII / emoji plaintexts must round-trip."""
    pwd = "pässwörd-🔒-日本語"
    h = hash_password(pwd)
    assert verify_password(pwd, h) is True
    assert verify_password("pässwörd-🔒-日本", h) is False


def test_hash_password_rejects_input_over_72_bytes() -> None:
    """AUTH-27: bcrypt only reads 72 bytes. Rather than silently truncating
    (so any 72-byte prefix would verify), over-long passwords are refused."""
    with pytest.raises(PasswordTooLongError):
        hash_password("a" * 73)
    # Multi-byte characters count by UTF-8 length, not code points.
    with pytest.raises(PasswordTooLongError):
        hash_password("é" * 37)


def test_hash_password_accepts_exactly_72_bytes() -> None:
    pwd = "a" * 72
    assert verify_password(pwd, hash_password(pwd)) is True


def test_verify_password_over_72_bytes_is_false_not_error() -> None:
    """Login with a >72-byte password must be a clean mismatch, never a 500
    (bcrypt >= 5 raises ValueError on such input)."""
    h = hash_password("a" * 72)
    assert verify_password("a" * 100, h) is False


def test_verify_password_malformed_hash_is_false() -> None:
    assert verify_password("anything", "not-a-bcrypt-hash") is False


def test_password_policy_error() -> None:
    assert password_policy_error("short") is not None
    assert password_policy_error("x" * 11) is not None
    assert password_policy_error("x" * 12) is None
    assert password_policy_error("x" * 73) is not None


# ---------------------------------------------------------------------------
# create_access_token
# ---------------------------------------------------------------------------


def _decode(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM], options={"verify_aud": False})


def test_create_access_token_includes_exp_claim() -> None:
    token = create_access_token({"sub": "user-1"})
    payload = _decode(token)
    assert "exp" in payload
    assert payload["sub"] == "user-1"


def test_create_access_token_signs_with_jwt_secret() -> None:
    """Decoding with the wrong secret must fail; decoding with the configured
    secret succeeds and returns the original claims."""
    token = create_access_token({"sub": "user-2", "role": "analyst"})

    # Wrong secret rejected.
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(
            token, "definitely-not-the-real-secret-padded-to-32-chars", algorithms=[ALGORITHM]
        )

    # Right secret accepted, payload preserved.
    payload = _decode(token)
    assert payload["sub"] == "user-2"
    assert payload["role"] == "analyst"


@freeze_time("2026-01-01 12:00:00")
def test_create_access_token_custom_expires_delta() -> None:
    """Custom expires_delta is honored to the second."""
    delta = timedelta(minutes=5)
    token = create_access_token({"sub": "user-3"}, expires_delta=delta)
    payload = _decode(token)

    # Source uses datetime.utcnow() which is naive UTC. Compare against the
    # same naive-UTC clock under freezegun.
    expected_exp = int((datetime(2026, 1, 1, 12, 5, 0)).timestamp())
    assert payload["exp"] == expected_exp


@freeze_time("2026-01-01 12:00:00")
def test_create_access_token_default_expiration_uses_config() -> None:
    """No expires_delta -> ACCESS_TOKEN_EXPIRE_MINUTES from src.config.

    Phase 4 Batch 4.4 (audit B5): the constant is now sourced from the
    `JWT_EXPIRATION` env var (integer minutes) with a 60-minute fallback.
    This test still asserts the create_access_token <-> module constant
    coupling; the env-var plumbing is covered in tests/test_config.py.
    """
    token = create_access_token({"sub": "user-4"})
    payload = _decode(token)

    expected_exp = int(
        (
            datetime(2026, 1, 1, 12, 0, 0) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        ).timestamp()
    )
    assert payload["exp"] == expected_exp
