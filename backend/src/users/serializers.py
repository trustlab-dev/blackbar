"""The one safe way to read user records for API responses (AUTH-04).

User documents hold `password_hash`, `activation_token` (a bcrypt hash of the
invite token) and other internal fields. Any query whose result can reach a
response body must use ``SAFE_USER_PROJECTION`` (an allowlist, so a new
sensitive field is excluded by default), and any user dict that is returned
must pass through ``serialize_user``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

# Allowlist of user fields that may leave the server.
SAFE_USER_FIELDS = ("id", "email", "name", "role", "status", "created_at", "updated_at")

# Mongo projection form of the allowlist. `token_version` is read (it is a
# counter, not a secret) because the session checks need it; serialize_user
# drops it from response bodies.
SAFE_USER_PROJECTION: dict[str, int] = {
    "_id": 0,
    **dict.fromkeys(SAFE_USER_FIELDS, 1),
    "token_version": 1,
}


def serialize_user(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return only the allowlisted fields of a user document, JSON-ready."""
    if doc is None:
        return None
    out: dict[str, Any] = {}
    for field in SAFE_USER_FIELDS:
        if field in doc:
            value = doc[field]
            out[field] = value.isoformat() if isinstance(value, datetime) else value
    return out
