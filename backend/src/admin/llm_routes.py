"""
Admin LLM Configuration Routes

Security-review 2026-09:
- LLM-20: gated on the DB-backed role (``require_role``), owner or admin.
- LLM-05: endpoints must be https (http only for localhost) and must not
  point at private or link-local addresses unless
  LLM_ALLOW_PRIVATE_ENDPOINTS is on (422 otherwise). Changing the endpoint
  or provider without a new key clears the stored key (``api_key_set:
  false`` in the response). Custom header values are masked in responses.
  Every change is written to ``audit_logs`` (category ``llm_config``).
- LLM-02/LLM-09: the connection test sends a system + user message through
  the same adapter as real calls and never returns provider error text.
"""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..config import llm_settings
from ..core.dependencies import require_role
from ..core.rate_limit import limiter
from ..database import db
from ..dependencies import get_current_user
from ..llm import (
    LLMConfigCreate,
    LLMConfigResponse,
    LLMConfigUpdate,
    LLMEndpointError,
    LLMError,
    LLMRepository,
    LLMService,
)
from ..llm.audit import endpoint_host, record_llm_config_event
from ..llm.encryption import EncryptionKeyError
from ..llm.safety import validate_llm_endpoint
from ..llm.service import extract_completion

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/llm", tags=["Admin - LLM Configuration"])

LLM_ADMIN_ROLES = ["owner", "admin"]
_admin_gate = [Depends(require_role(LLM_ADMIN_ROLES))]


def get_llm_service() -> LLMService:
    """Get LLM service instance"""
    return LLMService(db)


def get_llm_repository() -> LLMRepository:
    """Get LLM repository instance"""
    return LLMRepository(db)


async def _validate_endpoint_or_422(url: str) -> None:
    try:
        await validate_llm_endpoint(url)
    except LLMEndpointError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


def _encryption_unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="LLM API keys cannot be stored: LLM_API_KEY_ENCRYPTION_KEY is missing or invalid.",
    )


# LLM Configuration CRUD


@router.post("/configs", response_model=LLMConfigResponse, dependencies=_admin_gate)
async def create_llm_config(
    request: Request,
    config: LLMConfigCreate,
    current_user=Depends(get_current_user),
    repo: LLMRepository = Depends(get_llm_repository),
    service: LLMService = Depends(get_llm_service),
):
    """Create a new LLM configuration. Requires owner or admin.

    If no global default LLM is set yet, the newly created config is
    auto-promoted to default — otherwise AI features stay silently
    disabled until an operator manually clicks "Set Default" (FE-F11).
    """
    await _validate_endpoint_or_422(config.api_endpoint)
    try:
        llm_config = await repo.create(config, current_user["id"])
    except EncryptionKeyError:
        raise _encryption_unavailable() from None

    promoted = False
    if llm_config.enabled and await service.get_default_llm_id() is None:
        promoted = await service.set_default_llm(llm_config.id, current_user["id"])

    await record_llm_config_event(
        db,
        "llm_config_created",
        request=request,
        actor=current_user,
        config_id=llm_config.id,
        details={
            "name": llm_config.name,
            "request_format": llm_config.request_format.value,
            "endpoint_host": endpoint_host(llm_config.api_endpoint),
            "model_name": llm_config.model_name,
            "enabled": llm_config.enabled,
            "header_names": sorted((llm_config.headers or {}).keys()),
            "set_as_default": promoted,
        },
    )
    return LLMConfigResponse.from_config(llm_config)


@router.get("/configs", response_model=list[LLMConfigResponse], dependencies=_admin_gate)
async def list_llm_configs(
    enabled_only: bool = False, repo: LLMRepository = Depends(get_llm_repository)
):
    """List all LLM configurations. Requires owner or admin."""
    configs = await repo.list_all(enabled_only=enabled_only)
    return [LLMConfigResponse.from_config(config) for config in configs]


@router.get("/configs/{config_id}", response_model=LLMConfigResponse, dependencies=_admin_gate)
async def get_llm_config(config_id: str, repo: LLMRepository = Depends(get_llm_repository)):
    """Get a specific LLM configuration. Requires owner or admin."""
    config = await repo.get_by_id(config_id)
    if not config:
        raise HTTPException(status_code=404, detail="LLM configuration not found")
    return LLMConfigResponse.from_config(config)


@router.put("/configs/{config_id}", response_model=LLMConfigResponse, dependencies=_admin_gate)
async def update_llm_config(
    request: Request,
    config_id: str,
    update: LLMConfigUpdate,
    current_user=Depends(get_current_user),
    repo: LLMRepository = Depends(get_llm_repository),
):
    """Update an LLM configuration. Requires owner or admin.

    Changing ``api_endpoint`` or ``request_format`` without a new
    ``api_key`` clears the stored key; the response then has
    ``api_key_set: false`` and AI calls fail until a key is entered.
    """
    before = await repo.get_by_id(config_id)
    if not before:
        raise HTTPException(status_code=404, detail="LLM configuration not found")
    if update.api_endpoint is not None and update.api_endpoint != before.api_endpoint:
        await _validate_endpoint_or_422(update.api_endpoint)

    try:
        config = await repo.update(config_id, update)
    except EncryptionKeyError:
        raise _encryption_unavailable() from None
    if not config:
        raise HTTPException(status_code=404, detail="LLM configuration not found")

    changed = sorted(
        name
        for name, value in update.model_dump(exclude={"api_key"}).items()
        if value is not None and getattr(before, name) != getattr(config, name)
    )
    details = {
        "changed_fields": changed,
        "api_key_changed": bool(update.api_key),
        "api_key_cleared": bool(before.api_key_encrypted) and not config.api_key_encrypted,
    }
    if "api_endpoint" in changed:
        details["endpoint_host_before"] = endpoint_host(before.api_endpoint)
        details["endpoint_host_after"] = endpoint_host(config.api_endpoint)
    if "request_format" in changed:
        details["request_format_before"] = before.request_format.value
        details["request_format_after"] = config.request_format.value
    if "model_name" in changed:
        details["model_before"] = before.model_name
        details["model_after"] = config.model_name
    if "enabled" in changed:
        details["enabled"] = config.enabled
    await record_llm_config_event(
        db,
        "llm_config_updated",
        request=request,
        actor=current_user,
        config_id=config_id,
        details=details,
    )
    return LLMConfigResponse.from_config(config)


@router.delete("/configs/{config_id}", dependencies=_admin_gate)
async def delete_llm_config(
    request: Request,
    config_id: str,
    current_user=Depends(get_current_user),
    repo: LLMRepository = Depends(get_llm_repository),
    service: LLMService = Depends(get_llm_service),
):
    """Delete an LLM configuration. Requires owner or admin."""
    if await service.get_default_llm_id() == config_id:
        raise HTTPException(
            status_code=400, detail="Cannot delete default LLM. Set a different default first."
        )

    existing = await repo.get_by_id(config_id)
    deleted = await repo.delete(config_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="LLM configuration not found")

    await record_llm_config_event(
        db,
        "llm_config_deleted",
        request=request,
        actor=current_user,
        config_id=config_id,
        details={
            "name": existing.name if existing else None,
            "endpoint_host": endpoint_host(existing.api_endpoint) if existing else None,
        },
    )
    return {"message": "LLM configuration deleted successfully"}


# Global Default Management


@router.get("/default", response_model=LLMConfigResponse, dependencies=_admin_gate)
async def get_default_llm(service: LLMService = Depends(get_llm_service)):
    """Get the default LLM configuration (even when disabled). Requires owner or admin."""
    config = await service.get_default_llm(include_disabled=True)
    if not config:
        raise HTTPException(status_code=404, detail="No global default LLM configured")
    return LLMConfigResponse.from_config(config)


@router.put("/default/{config_id}", dependencies=_admin_gate)
async def set_default_llm(
    request: Request,
    config_id: str,
    current_user=Depends(get_current_user),
    service: LLMService = Depends(get_llm_service),
):
    """Set the default LLM configuration. Requires owner or admin."""
    previous = await service.get_default_llm_id()
    success = await service.set_default_llm(config_id, current_user["id"])
    if not success:
        raise HTTPException(status_code=404, detail="LLM configuration not found or not enabled")

    await record_llm_config_event(
        db,
        "llm_default_set",
        request=request,
        actor=current_user,
        config_id=config_id,
        details={"previous_default_id": previous},
    )
    return {"message": "Default LLM set successfully", "config_id": config_id}


# LLM Testing


class LLMTestRequest(BaseModel):
    config_id: str


# Same message shape as a real analysis call: system + user, JSON requested.
_TEST_MESSAGES = [
    {
        "role": "system",
        "content": (
            "You are a connection check for a document redaction service. "
            "Respond with valid JSON only."
        ),
    },
    {
        "role": "user",
        "content": 'Reply with exactly this JSON and nothing else: {"status": "ok"}',
    },
]


@router.post("/test", dependencies=_admin_gate)
@limiter.limit(lambda: llm_settings.user_rate_limit)
async def test_llm(
    request: Request,
    body: LLMTestRequest,
    service: LLMService = Depends(get_llm_service),
):
    """Test an LLM configuration with a real system + user prompt. Requires
    owner or admin. Failures return a generic message and a reference id;
    provider error text is logged server-side only."""
    repo = LLMRepository(db)
    config = await repo.get_by_id(body.config_id)

    if not config:
        raise HTTPException(status_code=404, detail="LLM configuration not found")

    if not config.enabled:
        return {"success": False, "message": "Configuration is disabled", "response": None}

    await _validate_endpoint_or_422(config.api_endpoint)

    start = time.time()
    try:
        raw_response = await service.make_llm_call(
            config, _TEST_MESSAGES, temperature=0, max_tokens=256
        )
        text, finish_reason = extract_completion(config.request_format, raw_response)
        elapsed = round(time.time() - start, 2)
        return {
            "success": True,
            "message": f"Connection successful ({elapsed}s)",
            "response": (text or "").strip()[:500],
            "finish_reason": finish_reason,
            "model": config.model_name,
            "latency_seconds": elapsed,
        }
    except (LLMError, EncryptionKeyError) as exc:
        elapsed = round(time.time() - start, 2)
        public = (
            exc.public_detail()
            if isinstance(exc, LLMError)
            else "The stored API key cannot be decrypted; re-enter it."
        )
        return {
            "success": False,
            "message": f"Connection failed ({elapsed}s): {public}",
            "error_code": getattr(exc, "code", "api_key_unreadable"),
            "reference": getattr(exc, "reference", None),
            "response": None,
            "latency_seconds": elapsed,
        }
