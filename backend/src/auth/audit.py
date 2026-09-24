"""Durable audit trail for authentication and user-administration events.

Written to the ``audit_logs`` collection (AUTH-24). Recording is best effort:
a failure is logged and never breaks the request that triggered it. Raw
emails are never stored; failed logins carry a salted hash instead.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from starlette.requests import Request

from src.core.rate_limit import client_ip

logger = logging.getLogger(__name__)

AUDIT_COLLECTION = "audit_logs"


async def record_auth_event(
    db: Any,
    action: str,
    *,
    request: Request | None = None,
    actor_id: str | None = None,
    target_id: str | None = None,
    success: bool = True,
    details: dict[str, Any] | None = None,
) -> None:
    """Append one auth/user-admin event to ``audit_logs`` (no-op without a db)."""
    if db is None:
        return
    entry: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "category": "auth",
        "action": action,
        "timestamp": datetime.now(UTC),
        "actor_id": actor_id,
        "target_id": target_id,
        "success": success,
        "details": details or {},
    }
    if request is not None:
        try:
            entry["ip_address"] = client_ip(request)
            entry["user_agent"] = request.headers.get("user-agent")
        except AttributeError:  # stand-in request objects in direct calls
            pass
    try:
        await db[AUDIT_COLLECTION].insert_one(entry)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error(f"Failed to write auth audit event {action}: {exc}")
