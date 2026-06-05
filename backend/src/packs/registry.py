"""
Pack Registry - Manages available packs
"""

import logging
from typing import Any

from .loader import PackLoader

logger = logging.getLogger(__name__)


class PackRegistry:
    """Registry of available jurisdiction packs"""

    @staticmethod
    def list_packs() -> list[dict[str, Any]]:
        """
        List all available packs with summary information

        Returns:
            List of pack summaries
        """
        all_packs = PackLoader.get_all_packs()

        pack_list = []
        for pack_id, pack_data in all_packs.items():
            pack_list.append(
                {
                    "pack_id": pack_id,
                    "name": pack_data.get("name", "Unknown"),
                    "version": pack_data.get("version", "0.0.0"),
                    "description": pack_data.get("description", ""),
                    "jurisdiction": {
                        "country": pack_data.get("jurisdiction", {}).get("country", ""),
                        "region": pack_data.get("jurisdiction", {}).get("region", ""),
                        "legislation_short": pack_data.get("jurisdiction", {}).get(
                            "legislation_short", ""
                        ),
                    },
                    "author": pack_data.get("author", "Unknown"),
                    "created_at": pack_data.get("created_at"),
                    "updated_at": pack_data.get("updated_at"),
                    "category_count": len(pack_data.get("redaction_categories", [])),
                    "status_count": len(pack_data.get("statuses", [])),
                    "has_templates": bool(pack_data.get("templates")),
                    "has_ai_prompts": bool(pack_data.get("ai_prompts")),
                }
            )

        # Sort by name
        pack_list.sort(key=lambda x: x["name"])

        return pack_list

    @staticmethod
    def get_pack_summary(pack_id: str) -> dict[str, Any] | None:
        """
        Get summary information for a specific pack

        Args:
            pack_id: Pack identifier

        Returns:
            Pack summary or None if not found
        """
        pack_data = PackLoader.load_pack(pack_id)
        if not pack_data:
            return None

        return {
            "pack_id": pack_id,
            "name": pack_data.get("name", "Unknown"),
            "version": pack_data.get("version", "0.0.0"),
            "description": pack_data.get("description", ""),
            "jurisdiction": pack_data.get("jurisdiction", {}),
            "author": pack_data.get("author", "Unknown"),
            "created_at": pack_data.get("created_at"),
            "updated_at": pack_data.get("updated_at"),
            "terminology": pack_data.get("terminology", {}),
            "timelines": pack_data.get("timelines", {}),
            "features": pack_data.get("features", {}),
            "category_count": len(pack_data.get("redaction_categories", [])),
            "status_count": len(pack_data.get("statuses", [])),
            "priority_count": len(pack_data.get("priorities", [])),
            "template_count": len(pack_data.get("templates", {})),
            "has_ai_prompts": bool(pack_data.get("ai_prompts")),
            "branding": pack_data.get("branding", {}),
        }

    @staticmethod
    def search_packs(query: str) -> list[dict[str, Any]]:
        """
        Search packs by name, jurisdiction, or description

        Args:
            query: Search query string

        Returns:
            List of matching pack summaries
        """
        all_packs = PackRegistry.list_packs()
        query_lower = query.lower()

        matching_packs = []
        for pack in all_packs:
            if (
                query_lower in pack["name"].lower()
                or query_lower in pack.get("description", "").lower()
                or query_lower in pack["jurisdiction"].get("country", "").lower()
                or query_lower in pack["jurisdiction"].get("region", "").lower()
                or query_lower in pack["jurisdiction"].get("legislation_short", "").lower()
            ):
                matching_packs.append(pack)

        return matching_packs

    @staticmethod
    def get_packs_by_country(country_code: str) -> list[dict[str, Any]]:
        """
        Get all packs for a specific country

        Args:
            country_code: Two-letter country code (e.g., 'CA', 'US')

        Returns:
            List of pack summaries for that country
        """
        all_packs = PackRegistry.list_packs()

        return [
            pack
            for pack in all_packs
            if pack["jurisdiction"].get("country", "").upper() == country_code.upper()
        ]


def list_available_packs() -> list[dict[str, Any]]:
    """
    Convenience function to list all available packs

    Returns:
        List of pack summaries
    """
    return PackRegistry.list_packs()
