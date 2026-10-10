"""
LLM Configuration Repository

Custom header values often carry credentials (``api-key``, ``Authorization``),
so they are stored encrypted with the same Fernet key as the API key
(``fernet:<token>``) and decrypted only when a config is loaded (I6).
Values stored in plaintext by older builds are still read, and re-encrypted
the first time the config is loaded.
"""

import logging
import uuid
from datetime import datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from .encryption import EncryptionKeyError, decrypt_api_key, encrypt_api_key
from .models import MASKED_HEADER_VALUE, LLMConfig, LLMConfigCreate, LLMConfigUpdate, RequestFormat

logger = logging.getLogger(__name__)

_HEADER_PREFIX = "fernet:"


def _encrypt_headers(headers: dict[str, str] | None) -> dict[str, str] | None:
    if headers is None:
        return None
    return {name: _HEADER_PREFIX + encrypt_api_key(value) for name, value in headers.items()}


def _decrypt_headers(stored: dict[str, str] | None, config_id: str) -> dict[str, str] | None:
    if not stored:
        return stored
    out = {}
    for name, value in stored.items():
        if isinstance(value, str) and value.startswith(_HEADER_PREFIX):
            try:
                out[name] = decrypt_api_key(value[len(_HEADER_PREFIX) :])
            except EncryptionKeyError:
                logger.warning(
                    "LLM config %s: header %r cannot be decrypted; re-enter it", config_id, name
                )
                out[name] = ""
        else:
            out[name] = value  # legacy plaintext
    return out


def _has_plaintext_headers(stored: Any) -> bool:
    return isinstance(stored, dict) and any(
        not (isinstance(v, str) and v.startswith(_HEADER_PREFIX)) for v in stored.values()
    )


class LLMRepository:
    """Repository for LLM configuration CRUD operations"""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db.llm_configs

    async def create(self, config_data: LLMConfigCreate, created_by: str) -> LLMConfig:
        """Create a new LLM configuration"""
        config_dict = config_data.model_dump(exclude={"api_key"})
        config_dict["id"] = str(uuid.uuid4())
        config_dict["api_key_encrypted"] = encrypt_api_key(config_data.api_key)
        config_dict["created_at"] = datetime.utcnow()
        config_dict["updated_at"] = datetime.utcnow()
        config_dict["created_by"] = created_by

        plain_headers = config_dict.get("headers")
        config_dict["headers"] = _encrypt_headers(plain_headers)
        await self.collection.insert_one(config_dict)
        config_dict["headers"] = plain_headers
        return LLMConfig(**config_dict)

    async def _load(self, doc: dict[str, Any]) -> LLMConfig:
        """Build an LLMConfig with decrypted headers; re-encrypt legacy
        plaintext header values in place."""
        doc.pop("_id", None)
        stored = doc.get("headers")
        doc["headers"] = _decrypt_headers(stored, doc.get("id", "?"))
        if _has_plaintext_headers(stored):
            try:
                await self.collection.update_one(
                    {"id": doc["id"], "headers": stored},
                    {"$set": {"headers": _encrypt_headers(doc["headers"])}},
                )
            except EncryptionKeyError:
                pass  # no usable key: leave as is, calls fail closed anyway
        return LLMConfig(**doc)

    async def get_by_id(self, config_id: str) -> LLMConfig | None:
        """Get LLM configuration by ID"""
        doc = await self.collection.find_one({"id": config_id})
        if doc:
            return await self._load(doc)
        return None

    async def list_all(self, enabled_only: bool = False) -> list[LLMConfig]:
        """List all LLM configurations"""
        query = {"enabled": True} if enabled_only else {}
        cursor = self.collection.find(query)
        configs = []
        async for doc in cursor:
            configs.append(await self._load(doc))
        return configs

    async def update(self, config_id: str, update_data: LLMConfigUpdate) -> LLMConfig | None:
        """Update an LLM configuration.

        LLM-05/I6: changing ``api_endpoint`` or ``request_format`` without
        supplying a new ``api_key`` clears the stored key, and stored custom
        header values are dropped too (they are credentials as often as
        not), so no stored credential is sent to a new destination. Header
        values equal to ``MASKED_HEADER_VALUE`` keep their stored value only
        while the destination is unchanged; on a change they must be
        re-entered.
        """
        current = await self.get_by_id(config_id)
        if current is None:
            return None

        update_dict = {k: v for k, v in update_data.model_dump().items() if v is not None}
        if not update_dict:
            return current

        endpoint_changed = (
            "api_endpoint" in update_dict and update_dict["api_endpoint"] != current.api_endpoint
        )
        format_changed = "request_format" in update_dict and (
            RequestFormat(update_dict["request_format"]) != current.request_format
        )
        destination_changed = endpoint_changed or format_changed

        if "headers" in update_dict:
            stored = current.headers or {}
            update_dict["headers"] = {
                name: (stored.get(name, "") if value == MASKED_HEADER_VALUE else value)
                for name, value in update_dict["headers"].items()
                if not (destination_changed and value == MASKED_HEADER_VALUE)
            }
        elif destination_changed and current.headers:
            update_dict["headers"] = {}
        if "headers" in update_dict:
            update_dict["headers"] = _encrypt_headers(update_dict["headers"])

        if update_dict.get("api_key"):
            update_dict["api_key_encrypted"] = encrypt_api_key(update_dict.pop("api_key"))
        else:
            update_dict.pop("api_key", None)
            if destination_changed:
                update_dict["api_key_encrypted"] = ""

        update_dict["updated_at"] = datetime.utcnow()

        result = await self.collection.update_one({"id": config_id}, {"$set": update_dict})
        if result.matched_count == 0:
            return None
        return await self.get_by_id(config_id)

    async def delete(self, config_id: str) -> bool:
        """Delete an LLM configuration"""
        result = await self.collection.delete_one({"id": config_id})
        return result.deleted_count > 0

    async def create_indexes(self):
        """Create necessary indexes"""
        await self.collection.create_index("id", unique=True)
        await self.collection.create_index("name")
        await self.collection.create_index("enabled")
