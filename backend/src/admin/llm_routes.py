"""
Admin LLM Configuration Routes
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core.dependencies import require_role
from ..database import db
from ..dependencies import get_current_user
from ..llm import LLMConfigCreate, LLMConfigResponse, LLMConfigUpdate, LLMRepository, LLMService

router = APIRouter(prefix="/llm", tags=["Admin - LLM Configuration"])


def get_llm_service() -> LLMService:
    """Get LLM service instance"""
    return LLMService(db)


def get_llm_repository() -> LLMRepository:
    """Get LLM repository instance"""
    return LLMRepository(db)


# LLM Configuration CRUD


@router.post(
    "/configs", response_model=LLMConfigResponse, dependencies=[Depends(require_role(["admin"]))]
)
async def create_llm_config(
    config: LLMConfigCreate,
    current_user=Depends(get_current_user),
    repo: LLMRepository = Depends(get_llm_repository),
    service: LLMService = Depends(get_llm_service),
):
    """Create a new LLM configuration. Requires admin role.

    If no global default LLM is set yet, the newly created config is
    auto-promoted to default — otherwise AI features stay silently
    disabled until an operator manually clicks "Set Default" (FE-F11).
    """
    llm_config = await repo.create(config, current_user["id"])

    # Auto-mark as default when there's no existing default — covers the
    # first-config case and avoids the "config exists but AI says LLM not
    # configured" trap.
    if llm_config.enabled:
        existing_default = await service.get_default_llm()
        if existing_default is None:
            await service.set_default_llm(llm_config.id, current_user["id"])

    # Return response without encrypted key
    return LLMConfigResponse(**llm_config.model_dump())


@router.get(
    "/configs",
    response_model=list[LLMConfigResponse],
    dependencies=[Depends(require_role(["admin"]))],
)
async def list_llm_configs(
    enabled_only: bool = False, repo: LLMRepository = Depends(get_llm_repository)
):
    """List all LLM configurations. Requires admin role."""
    configs = await repo.list_all(enabled_only=enabled_only)

    # Return responses without encrypted keys
    return [LLMConfigResponse(**config.model_dump()) for config in configs]


@router.get(
    "/configs/{config_id}",
    response_model=LLMConfigResponse,
    dependencies=[Depends(require_role(["admin"]))],
)
async def get_llm_config(config_id: str, repo: LLMRepository = Depends(get_llm_repository)):
    """Get a specific LLM configuration. Requires admin role."""
    config = await repo.get_by_id(config_id)
    if not config:
        raise HTTPException(status_code=404, detail="LLM configuration not found")

    return LLMConfigResponse(**config.model_dump())


@router.put(
    "/configs/{config_id}",
    response_model=LLMConfigResponse,
    dependencies=[Depends(require_role(["admin"]))],
)
async def update_llm_config(
    config_id: str, update: LLMConfigUpdate, repo: LLMRepository = Depends(get_llm_repository)
):
    """Update an LLM configuration. Requires admin role."""
    config = await repo.update(config_id, update)
    if not config:
        raise HTTPException(status_code=404, detail="LLM configuration not found")

    return LLMConfigResponse(**config.model_dump())


@router.delete("/configs/{config_id}", dependencies=[Depends(require_role(["admin"]))])
async def delete_llm_config(
    config_id: str,
    repo: LLMRepository = Depends(get_llm_repository),
    service: LLMService = Depends(get_llm_service),
):
    """Delete an LLM configuration. Requires admin role."""

    # Check if it's the global default
    default_config = await service.get_default_llm()
    if default_config and default_config.id == config_id:
        raise HTTPException(
            status_code=400, detail="Cannot delete default LLM. Set a different default first."
        )

    # Delete
    deleted = await repo.delete(config_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="LLM configuration not found")

    return {"message": "LLM configuration deleted successfully"}


# Global Default Management


@router.get(
    "/default", response_model=LLMConfigResponse, dependencies=[Depends(require_role(["admin"]))]
)
async def get_default_llm(service: LLMService = Depends(get_llm_service)):
    """Get the default LLM configuration. Requires admin role."""

    config = await service.get_default_llm()
    if not config:
        raise HTTPException(status_code=404, detail="No global default LLM configured")

    return LLMConfigResponse(**config.model_dump())


@router.put("/default/{config_id}", dependencies=[Depends(require_role(["admin"]))])
async def set_default_llm(
    config_id: str,
    current_user=Depends(get_current_user),
    service: LLMService = Depends(get_llm_service),
):
    """Set the default LLM configuration. Requires admin role."""
    success = await service.set_default_llm(config_id, current_user["id"])
    if not success:
        raise HTTPException(status_code=404, detail="LLM configuration not found or not enabled")

    return {"message": "Default LLM set successfully", "config_id": config_id}


# LLM Testing


class LLMTestRequest(BaseModel):
    config_id: str


@router.post("/test", dependencies=[Depends(require_role(["admin"]))])
async def test_llm(request: LLMTestRequest, service: LLMService = Depends(get_llm_service)):
    """Test an LLM configuration by sending a real prompt. Requires admin role."""
    import time

    repo = LLMRepository(db)
    config = await repo.get_by_id(request.config_id)

    if not config:
        raise HTTPException(status_code=404, detail="LLM configuration not found")

    if not config.enabled:
        return {"success": False, "message": "Configuration is disabled", "response": None}

    test_messages = [
        {
            "role": "user",
            "content": "This is a connection test. Reply with a single short sentence confirming you are working.",
        }
    ]

    start = time.time()
    try:
        raw_response = await service.make_llm_call(
            config, test_messages, temperature=0, max_tokens=50
        )

        # Extract text based on provider format
        if config.request_format.value == "openai":
            text = raw_response["choices"][0]["message"]["content"]
        elif config.request_format.value == "anthropic":
            text = raw_response["content"][0]["text"]
        elif config.request_format.value == "google":
            text = raw_response["candidates"][0]["content"]["parts"][0]["text"]
        elif config.request_format.value == "cohere":
            text = raw_response.get("text", str(raw_response))
        else:
            text = str(raw_response)

        elapsed = round(time.time() - start, 2)

        return {
            "success": True,
            "message": f"Connection successful ({elapsed}s)",
            "response": text.strip(),
            "model": config.model_name,
            "latency_seconds": elapsed,
        }
    except Exception as e:
        elapsed = round(time.time() - start, 2)
        return {
            "success": False,
            "message": f"Connection failed ({elapsed}s): {str(e)}",
            "response": None,
            "latency_seconds": elapsed,
        }
