"""
System Configuration Routes
API endpoints for managing system configuration
"""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from ..database import db
from ..dependencies import check_role, get_current_user
from .config_models import PublicConfiguration, SystemConfiguration, SystemConfigurationUpdate

router = APIRouter(prefix="/admin/config", tags=["Configuration"])
logger = logging.getLogger(__name__)

# Configuration collection
config_collection = db.system_config


async def get_system_config() -> dict[str, Any]:
    """Get current system configuration"""
    config = await config_collection.find_one({})

    if not config:
        # Create default configuration
        default_config = SystemConfiguration().dict()
        await config_collection.insert_one(default_config)
        config = default_config

    return config


async def update_system_config(updates: dict[str, Any], user_id: str) -> dict[str, Any]:
    """Update system configuration"""
    updates["updated_at"] = datetime.utcnow()
    updates["updated_by"] = user_id

    # Upsert configuration
    await config_collection.update_one({}, {"$set": updates}, upsert=True)

    return await get_system_config()


@router.get("/", response_model=SystemConfiguration)
async def get_configuration(request: Request, current_user=Depends(get_current_user)):
    """
    Get system configuration
    Requires authentication
    """
    try:
        config = await get_system_config()

        # Override default_due_days with pack configuration if not explicitly set
        from src.packs.loader import get_pack_timelines

        timelines = get_pack_timelines()
        if timelines and "default_response_days" in timelines:
            if "default_due_days" not in config or config.get("default_due_days") == 30:
                config["default_due_days"] = timelines["default_response_days"]

        # Remove MongoDB _id field
        if "_id" in config:
            del config["_id"]

        return config
    except Exception as e:
        logger.error(f"Error fetching configuration: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch configuration")


@router.put(
    "/", response_model=SystemConfiguration, dependencies=[Depends(check_role(["admin", "owner"]))]
)
async def update_configuration(
    request: Request,
    config_update: SystemConfigurationUpdate,
    current_user=Depends(get_current_user),
):
    """
    Update system configuration
    Admin only
    """
    try:
        # Get only non-None fields
        updates = {k: v for k, v in config_update.dict().items() if v is not None}

        if not updates:
            raise HTTPException(status_code=400, detail="No updates provided")

        # Update configuration
        updated_config = await update_system_config(updates, current_user["id"])

        # Log the change
        logger.info(
            f"Configuration updated by {current_user['username']}: {', '.join(updates.keys())}"
        )

        # Remove MongoDB _id field
        if "_id" in updated_config:
            del updated_config["_id"]

        return updated_config
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating configuration: {e}")
        raise HTTPException(status_code=500, detail="Failed to update configuration")


@router.get("/public", response_model=PublicConfiguration)
async def get_public_configuration(request: Request):
    """
    Get public configuration (no authentication required)
    Returns only non-sensitive settings
    """
    import os

    try:
        config = await get_system_config()

        return PublicConfiguration(
            org_name=config.get("org_name", "Freedom of Information Office"),
            org_logo_url=config.get("org_logo_url"),
            primary_color=config.get("primary_color", "#0366d6"),
            contact_email=config.get("contact_email", "foi@example.com"),
            footer_text=config.get("footer_text"),
            enable_public_requests=config.get("enable_public_requests", True),
            enable_request_tracking=config.get("enable_request_tracking", True),
            enable_public_upload=config.get("enable_public_upload", True),
            request_categories=config.get(
                "request_categories",
                [
                    "General Records",
                    "Personnel Files",
                    "Financial Records",
                    "Meeting Minutes",
                    "Correspondence",
                    "Contracts & Agreements",
                    "Policy Documents",
                    "Other",
                ],
            ),
            demo_mode=os.getenv("BLACKBAR_DEMO_MODE", "").lower() == "true",
        )
    except Exception as e:
        logger.error(f"Error fetching public configuration: {e}")
        # Phase 4 Batch 4.4 (audit B47): the graceful-fallback now
        # supplies ALL required fields on PublicConfiguration. Previously
        # `org_logo_url`, `contact_email`, and `footer_text` were
        # omitted, which made the model constructor itself raise
        # pydantic.ValidationError — the "degraded mode" was dead code
        # and anonymous portal users saw a 500 instead of defaults.
        return PublicConfiguration(
            org_name="Freedom of Information Office",
            org_logo_url=None,
            primary_color="#0366d6",
            contact_email="foi@example.com",
            footer_text=None,
            enable_public_requests=True,
            enable_request_tracking=True,
            enable_public_upload=True,
            request_categories=[
                "General Records",
                "Personnel Files",
                "Financial Records",
                "Meeting Minutes",
                "Correspondence",
                "Contracts & Agreements",
                "Policy Documents",
                "Other",
            ],
        )
