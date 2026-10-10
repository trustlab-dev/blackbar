"""Password hashing and JWT primitives.

The single implementation of both: `AuthService` and `MagicLinkService`
delegate here. Uses the `bcrypt` package directly (passlib was dropped in the
2026-09 security review: it is unmaintained and was only ever dead code).
"""

from __future__ import annotations

import functools
import time
from datetime import timedelta
from typing import Any

import bcrypt
import jwt
from jwt import InvalidAudienceError

from src.config import ACCESS_TOKEN_EXPIRE_MINUTES, ALGORITHM, JWT_SECRET

# bcrypt only reads the first 72 bytes of its input; bcrypt >= 5 raises on
# longer input. Longer passwords are refused at the API boundary instead of
# being silently truncated (AUTH-27).
BCRYPT_MAX_PASSWORD_BYTES = 72

# Token audiences (AUTH-03). A public (magic-link) token can never be accepted
# where an internal one is expected, and vice versa.
INTERNAL_AUDIENCE = "blackbar-internal"
PUBLIC_AUDIENCE = "blackbar-public"
KNOWN_AUDIENCES = frozenset({INTERNAL_AUDIENCE, PUBLIC_AUDIENCE})

# Role carried by public-realm tokens. Not a system role: no staff route
# admits it.
PUBLIC_ROLE = "public_user"


class PasswordTooLongError(ValueError):
    """Raised when a password exceeds bcrypt's 72-byte input limit."""


def password_too_long(password: str) -> bool:
    return len(password.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES


def hash_password(password: str) -> str:
    """bcrypt-hash ``password``; refuses input bcrypt would truncate."""
    if password_too_long(password):
        raise PasswordTooLongError(
            f"Password must be at most {BCRYPT_MAX_PASSWORD_BYTES} bytes when UTF-8 encoded"
        )
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check ``plain_password`` against a bcrypt hash. Never raises."""
    if password_too_long(plain_password):
        return False
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        # Malformed stored hash, or a bcrypt version that rejects the input.
        return False


@functools.cache
def _dummy_hash() -> bytes:
    return bcrypt.hashpw(b"blackbar-timing-equaliser", bcrypt.gensalt())


def burn_password_check(plain_password: str) -> None:
    """Spend the same time as a real bcrypt verify (AUTH-23).

    Called on login paths that fail before any real hash comparison (unknown
    email, inactive account) so response time does not reveal which accounts
    exist.
    """
    candidate = plain_password.encode("utf-8")[:BCRYPT_MAX_PASSWORD_BYTES]
    bcrypt.checkpw(candidate, _dummy_hash())


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """Mint an HS256 JWT with ``iat`` and ``exp`` as real Unix epochs.

    Uses ``time.time()`` rather than ``datetime.utcnow().timestamp()``: the
    latter treats a naive UTC datetime as local time and skews ``exp`` by the
    host's UTC offset (AUTH-26 / B1).
    """
    now = int(time.time())
    delta = expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = dict(data)
    to_encode.update({"iat": now, "exp": now + int(delta.total_seconds())})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Verify signature, algorithm and expiry; return the claims.

    ``sub`` and ``exp`` are required. ``aud`` is optional for tokens minted
    before audiences existed, but when present it must be one of ours.

    Raises ``jwt.InvalidTokenError`` (or a subclass) on any failure.
    """
    payload = jwt.decode(
        token,
        JWT_SECRET,
        algorithms=[ALGORITHM],
        options={"require": ["exp", "sub"], "verify_aud": False},
    )
    aud = payload.get("aud")
    if aud is not None and aud not in KNOWN_AUDIENCES:
        raise InvalidAudienceError("Unknown token audience")
    return payload


def is_public_claims(payload: dict[str, Any]) -> bool:
    """True if the claims describe a public (magic-link) principal.

    Any public marker wins, so a token can only ever be downgraded to the
    public realm, never promoted out of it.
    """
    return (
        payload.get("aud") == PUBLIC_AUDIENCE
        or payload.get("realm") == "public"
        or payload.get("user_type") == "public"
        or payload.get("role") == PUBLIC_ROLE
    )


# Minimal password policy for every place a password is set (AUTH-25).
MIN_PASSWORD_LENGTH = 12


def password_policy_error(password: str) -> str | None:
    """Return why ``password`` is not acceptable as a new password, or None."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
    if password_too_long(password):
        return f"Password must be at most {BCRYPT_MAX_PASSWORD_BYTES} bytes when UTF-8 encoded"
    return None
