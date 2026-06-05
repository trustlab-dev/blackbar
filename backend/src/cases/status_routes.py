"""
Case Status Routes - Dynamic statuses from jurisdiction pack
"""

from fastapi import APIRouter

from src.packs.loader import get_pack_priorities, get_pack_statuses, get_pack_timelines

router = APIRouter()


@router.get("/statuses")
async def get_statuses():
    """
    Get case statuses from active jurisdiction pack
    Public endpoint - no auth required
    """
    statuses = get_pack_statuses()

    return {"statuses": statuses}


@router.get("/priorities")
async def get_priorities():
    """
    Get case priorities from active jurisdiction pack
    Public endpoint - no auth required
    """
    priorities = get_pack_priorities()

    return {"priorities": priorities}


@router.get("/timelines")
async def get_timelines():
    """
    Get timeline configuration from active jurisdiction pack
    Public endpoint - no auth required
    """
    timelines = get_pack_timelines()

    return {"timelines": timelines}
