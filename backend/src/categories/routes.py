from fastapi import APIRouter

from src.packs.loader import get_pack_categories

router = APIRouter()


@router.get("/")
async def get_categories():
    """
    Get redaction categories from active jurisdiction pack
    """
    categories = get_pack_categories()

    # Return in the format expected by frontend
    return {
        "categories": [
            {
                "id": cat.get("code"),  # Use code as ID for backwards compatibility
                "code": cat.get("code"),
                "name": cat.get("name"),
                "description": cat.get("description"),
                "section": cat.get("section"),
                "color": cat.get("color"),
                "legal_reference": cat.get("legal_reference"),
                "guidance": cat.get("guidance"),
            }
            for cat in categories
        ]
    }
