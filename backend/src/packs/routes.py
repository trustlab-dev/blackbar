"""
Pack Management API Routes
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from ..dependencies import check_role, get_current_user
from .loader import PackLoader, get_active_pack, reload_packs, set_active_pack
from .registry import PackRegistry
from .validator import validate_pack

router = APIRouter(prefix="/packs", tags=["Packs"])
logger = logging.getLogger(__name__)


@router.get("/")
async def list_packs():
    """
    List all available jurisdiction packs

    Returns:
        List of pack summaries
    """
    try:
        packs = PackRegistry.list_packs()
        active_pack = get_active_pack()
        active_pack_id = active_pack.get("pack_id") if active_pack else None

        # Mark active pack
        for pack in packs:
            pack["is_active"] = pack["pack_id"] == active_pack_id

        return {"packs": packs, "active_pack_id": active_pack_id}
    except Exception as e:
        logger.error(f"Error listing packs: {e}")
        raise HTTPException(status_code=500, detail="Error listing packs")


@router.get("/active")
async def get_active_pack_info():
    """
    Get the currently active pack

    Returns:
        Active pack data
    """
    pack = get_active_pack()
    if not pack:
        raise HTTPException(status_code=404, detail="No active pack found")

    return pack


@router.get("/active/categories")
async def get_active_pack_categories():
    """
    Get redaction categories from the currently active pack

    Returns:
        List of redaction categories with their details
    """
    pack = get_active_pack()
    if not pack:
        raise HTTPException(status_code=404, detail="No active pack found")

    categories = pack.get("redaction_categories", [])

    return {"categories": categories, "pack_id": pack.get("pack_id"), "pack_name": pack.get("name")}


@router.get("/active/sections")
async def get_active_pack_sections(q: str | None = None):
    """
    Get exemption sections from the currently active pack for autocomplete.

    Sections are derived from redaction_categories in the pack.
    Each category typically maps to a legal section (e.g., S.22 for personal privacy).

    Args:
        q: Optional search query to filter sections

    Returns:
        List of sections with code, name, and description
    """
    pack = get_active_pack()
    if not pack:
        raise HTTPException(status_code=404, detail="No active pack found")

    categories = pack.get("redaction_categories", [])

    # Build sections list from categories
    sections = []
    for cat in categories:
        section = {
            "code": cat.get("code", cat.get("id", "")),
            "name": cat.get("name", ""),
            "description": cat.get("description", ""),
            "category_id": cat.get("id", ""),
            "subsections": cat.get("subsections", []),
        }
        sections.append(section)

        # Add subsections as separate entries for more granular selection
        for subsec in cat.get("subsections", []):
            sub_section = {
                "code": subsec.get("code", ""),
                "name": subsec.get("name", ""),
                "description": subsec.get("description", ""),
                "category_id": cat.get("id", ""),
                "parent_code": cat.get("code", cat.get("id", "")),
            }
            sections.append(sub_section)

    # Filter by search query if provided
    if q:
        q_lower = q.lower()
        sections = [
            s
            for s in sections
            if q_lower in s.get("code", "").lower()
            or q_lower in s.get("name", "").lower()
            or q_lower in s.get("description", "").lower()
        ]

    return {
        "sections": sections,
        "pack_id": pack.get("pack_id"),
        "pack_name": pack.get("name"),
        "count": len(sections),
    }


@router.get("/search")
async def search_packs(q: str):
    """
    Search packs by name, jurisdiction, or description

    Phase 4 Batch 4.4 (audit B48): registered BEFORE the `/{pack_id}`
    catch-all so FastAPI's first-match rule resolves `/search` directly
    instead of treating "search" as a pack_id and 404'ing.

    Args:
        q: Search query

    Returns:
        Matching packs
    """
    try:
        packs = PackRegistry.search_packs(q)
        return {"query": q, "results": packs, "count": len(packs)}
    except Exception as e:
        logger.error(f"Error searching packs: {e}")
        raise HTTPException(status_code=500, detail=f"Error searching packs: {str(e)}")


@router.get("/country/{country_code}")
async def get_packs_by_country(country_code: str):
    """
    Get all packs for a specific country

    Phase 4 Batch 4.4 (audit B48): registered BEFORE `/{pack_id}` for
    consistency with `/search`. (Two-segment URLs were already reachable
    because no two-segment shadow existed, but explicit ordering is
    safer.)

    Args:
        country_code: Two-letter country code (e.g., 'CA', 'US')

    Returns:
        Packs for that country
    """
    try:
        packs = PackRegistry.get_packs_by_country(country_code)
        return {"country": country_code.upper(), "packs": packs, "count": len(packs)}
    except Exception as e:
        logger.error(f"Error getting packs by country: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/{pack_id}")
async def get_pack_details(pack_id: str):
    """
    Get detailed information about a specific pack

    Args:
        pack_id: Pack identifier

    Returns:
        Full pack data
    """
    pack = PackLoader.load_pack(pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail=f"Pack '{pack_id}' not found")

    return pack


@router.get("/{pack_id}/summary")
async def get_pack_summary(pack_id: str):
    """
    Get summary information about a pack

    Args:
        pack_id: Pack identifier

    Returns:
        Pack summary
    """
    summary = PackRegistry.get_pack_summary(pack_id)
    if not summary:
        raise HTTPException(status_code=404, detail=f"Pack '{pack_id}' not found")

    return summary


@router.get("/{pack_id}/preview")
async def preview_pack(pack_id: str):
    """
    Preview pack settings without activating

    Args:
        pack_id: Pack identifier

    Returns:
        Pack preview data
    """
    pack = PackLoader.load_pack(pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail=f"Pack '{pack_id}' not found")

    return {
        "pack_id": pack.get("pack_id"),
        "name": pack.get("name"),
        "version": pack.get("version"),
        "jurisdiction": pack.get("jurisdiction"),
        "terminology": pack.get("terminology"),
        "timelines": pack.get("timelines"),
        "categories": pack.get("redaction_categories", []),
        "statuses": pack.get("statuses", []),
        "priorities": pack.get("priorities", []),
        "templates": list(pack.get("templates", {}).keys()),
        "features": pack.get("features", {}),
        "branding": pack.get("branding", {}),
    }


@router.post("/activate", dependencies=[Depends(check_role(["owner", "admin"]))])
async def activate_pack(pack_id: str, current_user=Depends(get_current_user)):
    """
    Activate a jurisdiction pack

    Args:
        pack_id: Pack identifier to activate

    Returns:
        Success message
    """
    success = set_active_pack(pack_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Pack '{pack_id}' not found or invalid")

    logger.info(f"Pack '{pack_id}' activated by {current_user.get('username')}")

    # TODO(issue: TBD): Save to system_config in database

    return {
        "success": True,
        "message": f"Pack '{pack_id}' activated successfully",
        "active_pack": pack_id,
    }


@router.post("/validate")
async def validate_pack_data(pack_data: dict[str, Any]):
    """
    Validate a pack without saving it

    Args:
        pack_data: Pack JSON data

    Returns:
        Validation results
    """
    try:
        result = validate_pack(pack_data)
        return result
    except Exception as e:
        logger.error(f"Error validating pack: {e}")
        return {"valid": False, "errors": [str(e)], "warnings": []}


@router.post("/upload", dependencies=[Depends(check_role(["owner", "admin"]))])
async def upload_custom_pack(file: UploadFile = File(...), current_user=Depends(get_current_user)):
    """
    Upload a custom jurisdiction pack

    Args:
        file: JSON file containing pack data

    Returns:
        Upload result
    """
    if not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="File must be a JSON file")

    try:
        # Read and parse JSON
        content = await file.read()
        pack_data = json.loads(content)

        # Validate pack
        validation = validate_pack(pack_data)
        if not validation["valid"]:
            return {
                "success": False,
                "message": "Pack validation failed",
                "errors": validation["errors"],
                "warnings": validation["warnings"],
            }

        # Save to custom packs directory
        pack_id = pack_data.get("pack_id")
        custom_dir = PackLoader.get_packs_directory() / "custom"
        custom_dir.mkdir(exist_ok=True)

        pack_file = custom_dir / f"{pack_id}.json"
        with open(pack_file, "w", encoding="utf-8") as f:
            json.dump(pack_data, f, indent=2, ensure_ascii=False)

        logger.info(f"Custom pack '{pack_id}' uploaded by {current_user.get('username')}")

        # Reload packs to include new one
        reload_packs()

        return {
            "success": True,
            "message": f"Pack '{pack_id}' uploaded successfully",
            "pack_id": pack_id,
            "warnings": validation.get("warnings", []),
        }

    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")
    except Exception as e:
        logger.error(f"Error uploading pack: {e}")
        raise HTTPException(status_code=500, detail=f"Error uploading pack: {str(e)}")


@router.post("/reload", dependencies=[Depends(check_role(["owner", "admin"]))])
async def reload_all_packs(current_user=Depends(get_current_user)):
    """
    Reload all packs from filesystem

    Returns:
        Reload result
    """
    try:
        reload_packs()
        packs = PackRegistry.list_packs()

        logger.info(f"Packs reloaded by {current_user.get('username')}")

        return {
            "success": True,
            "message": f"Reloaded {len(packs)} packs",
            "pack_count": len(packs),
        }
    except Exception as e:
        logger.error(f"Error reloading packs: {e}")
        raise HTTPException(status_code=500, detail=f"Error reloading packs: {str(e)}")


# Phase 4 Batch 4.4 (audit B48): `/search` and `/country/{country_code}`
# moved to the top of the module (above `/{pack_id}`) so FastAPI's
# first-match rule resolves them before the catch-all.
