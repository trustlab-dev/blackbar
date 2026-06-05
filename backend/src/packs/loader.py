"""
Pack Loader - Loads jurisdiction packs from filesystem
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Global pack cache
_pack_cache: dict[str, dict[str, Any]] = {}
_active_pack: dict[str, Any] | None = None
_packs_directory = Path(__file__).parent.parent.parent / "packs"


class PackLoader:
    """Loads and manages jurisdiction packs"""

    @staticmethod
    def get_packs_directory() -> Path:
        """Get the packs directory path"""
        return _packs_directory

    @staticmethod
    def load_pack(pack_id: str) -> dict[str, Any] | None:
        """
        Load a pack by ID from filesystem

        Args:
            pack_id: Pack identifier (e.g., 'bc-fippa-v1')

        Returns:
            Pack data dictionary or None if not found
        """
        # Check cache first
        if pack_id in _pack_cache:
            logger.info(f"Loading pack '{pack_id}' from cache")
            return _pack_cache[pack_id]

        # Try to load from filesystem
        pack_file = _packs_directory / f"{pack_id}.json"

        if not pack_file.exists():
            # Try custom directory
            pack_file = _packs_directory / "custom" / f"{pack_id}.json"

        if not pack_file.exists():
            logger.error(f"Pack file not found: {pack_id}")
            return None

        try:
            with open(pack_file, encoding="utf-8") as f:
                pack_data = json.load(f)

            # Validate pack has required fields
            if not pack_data.get("pack_id"):
                logger.error(f"Pack missing 'pack_id' field: {pack_file}")
                return None

            # Cache the pack
            _pack_cache[pack_id] = pack_data
            logger.info(f"Loaded pack '{pack_id}' from {pack_file}")

            return pack_data

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in pack file {pack_file}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error loading pack {pack_id}: {e}")
            return None

    @staticmethod
    def load_pack_by_filename(filename: str) -> dict[str, Any] | None:
        """
        Load a pack by filename

        Args:
            filename: Pack filename (e.g., 'bc-fippa.json')

        Returns:
            Pack data dictionary or None if not found
        """
        pack_file = _packs_directory / filename

        if not pack_file.exists():
            pack_file = _packs_directory / "custom" / filename

        if not pack_file.exists():
            logger.error(f"Pack file not found: {filename}")
            return None

        try:
            with open(pack_file, encoding="utf-8") as f:
                pack_data = json.load(f)

            pack_id = pack_data.get("pack_id")
            if pack_id:
                _pack_cache[pack_id] = pack_data

            return pack_data

        except Exception as e:
            logger.error(f"Error loading pack from {filename}: {e}")
            return None

    @staticmethod
    def get_all_packs() -> dict[str, dict[str, Any]]:
        """
        Load all available packs from filesystem

        Returns:
            Dictionary of pack_id -> pack_data
        """
        packs = {}

        # Load from main packs directory
        if _packs_directory.exists():
            for pack_file in _packs_directory.glob("*.json"):
                try:
                    with open(pack_file, encoding="utf-8") as f:
                        pack_data = json.load(f)

                    pack_id = pack_data.get("pack_id")
                    if pack_id:
                        packs[pack_id] = pack_data
                        _pack_cache[pack_id] = pack_data

                except Exception as e:
                    logger.error(f"Error loading pack {pack_file}: {e}")

        # Load from custom directory
        custom_dir = _packs_directory / "custom"
        if custom_dir.exists():
            for pack_file in custom_dir.glob("*.json"):
                try:
                    with open(pack_file, encoding="utf-8") as f:
                        pack_data = json.load(f)

                    pack_id = pack_data.get("pack_id")
                    if pack_id:
                        packs[pack_id] = pack_data
                        _pack_cache[pack_id] = pack_data

                except Exception as e:
                    logger.error(f"Error loading custom pack {pack_file}: {e}")

        logger.info(f"Loaded {len(packs)} packs")
        return packs

    @staticmethod
    def clear_cache():
        """Clear the pack cache"""
        global _pack_cache
        _pack_cache = {}
        logger.info("Pack cache cleared")


def get_active_pack() -> dict[str, Any] | None:
    """
    Get the currently active pack

    Returns:
        Active pack data or None
    """
    global _active_pack

    if _active_pack:
        return _active_pack

    # Try to load from system config (will implement later)
    # For now, default to BC FIPPA
    _active_pack = PackLoader.load_pack("bc-fippa-v1")

    if not _active_pack:
        logger.warning("No active pack found, loading default bc-fippa-v1")
        _active_pack = PackLoader.load_pack("bc-fippa-v1")

    return _active_pack


def set_active_pack(pack_id: str) -> bool:
    """
    Set the active pack

    Args:
        pack_id: Pack identifier to activate

    Returns:
        True if successful, False otherwise
    """
    global _active_pack

    pack = PackLoader.load_pack(pack_id)
    if not pack:
        logger.error(f"Cannot activate pack '{pack_id}' - not found")
        return False

    _active_pack = pack
    logger.info(f"Activated pack: {pack_id}")

    # TODO(issue: TBD): Save to system_config in database

    return True


def reload_packs():
    """Reload all packs from filesystem"""
    PackLoader.clear_cache()
    PackLoader.get_all_packs()
    logger.info("Packs reloaded")


def get_pack_categories() -> list:
    """Get redaction categories from active pack"""
    pack = get_active_pack()
    if not pack:
        return []
    return pack.get("redaction_categories", [])


def get_pack_statuses() -> list:
    """Get case statuses from active pack"""
    pack = get_active_pack()
    if not pack:
        return []
    return pack.get("statuses", [])


def get_pack_priorities() -> list:
    """Get priorities from active pack"""
    pack = get_active_pack()
    if not pack:
        return []
    return pack.get("priorities", [])


def get_pack_timelines() -> dict:
    """Get timeline configuration from active pack"""
    pack = get_active_pack()
    if not pack:
        return {}
    return pack.get("timelines", {})


def get_pack_templates() -> dict:
    """Get document templates from active pack"""
    pack = get_active_pack()
    if not pack:
        return {}
    return pack.get("templates", {})


def get_pack_terminology() -> dict:
    """Get terminology from active pack"""
    pack = get_active_pack()
    if not pack:
        return {}
    return pack.get("terminology", {})


def get_pack_ai_prompts() -> dict:
    """Get AI prompts from active pack"""
    pack = get_active_pack()
    if not pack:
        return {}
    return pack.get("ai_prompts", {})
