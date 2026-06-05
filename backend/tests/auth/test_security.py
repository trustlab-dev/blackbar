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

from src.auth.security import create_access_token, hash_password, verify_password
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


def test_hash_password_handles_long_password() -> None:
    """bcrypt silently truncates inputs at 72 bytes.

    Pins reality: with passlib + bcrypt 4.x in this project, a password
    longer than 72 bytes hashes fine, AND its 72-byte prefix verifies
    against the same hash. This is a well-known bcrypt property (RFC: the
    algorithm operates on a 72-byte key). Documented here so future
    upgrades that change this behavior are caught by CI.
    """
    long_pwd = "a" * 100
    h = hash_password(long_pwd)
    # Same long string verifies.
    assert verify_password(long_pwd, h) is True
    # 72-byte prefix also verifies — this is the documented bcrypt truncation.
    assert verify_password("a" * 72, h) is True
    # A genuinely different prefix does NOT verify.
    assert verify_password("b" * 72, h) is False


# ---------------------------------------------------------------------------
# create_access_token
# ---------------------------------------------------------------------------


def _decode(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])


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
