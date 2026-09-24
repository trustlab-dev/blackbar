"""Audit trail for LLM configuration changes (LLM-05).

Entries go to the shared ``audit_logs`` collection with category
``llm_config``. They record who changed what and when; API keys and header
values are never recorded, only the fact that they changed.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from starlette.requests import Request

from src.auth.audit import AUDIT_COLLECTION
from src.core.rate_limit import client_ip

logger = logging.getLogger(__name__)


def endpoint_host(url: str | None) -> str | None:
    try:
        return urlsplit(url or "").hostname
    except ValueError:
        return None


async def record_llm_config_event(
    db: Any,
    action: str,
    *,
    request: Request | None,
    actor: dict | None,
    config_id: str | None,
    details: dict[str, Any] | None = None,
) -> None:
    """Append one LLM-config event; failures are logged, never raised."""
    if db is None:
        return
    entry: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "category": "llm_config",
        "action": action,
        "timestamp": datetime.now(UTC),
        "actor_id": (actor or {}).get("id"),
        "actor_username": (actor or {}).get("username"),
        "actor_role": (actor or {}).get("role"),
        "target_id": config_id,
        "success": True,
        "details": details or {},
    }
    if request is not None:
        try:
            entry["ip_address"] = client_ip(request)
            entry["user_agent"] = request.headers.get("user-agent")
        except AttributeError:  # pragma: no cover - stand-in request objects
            pass
    try:
        await db[AUDIT_COLLECTION].insert_one(entry)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error(f"Failed to write LLM config audit event {action}: {exc}")
