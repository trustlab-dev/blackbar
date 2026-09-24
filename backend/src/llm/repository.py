"""
LLM Configuration Repository
"""

import uuid
from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

from .encryption import encrypt_api_key
from .models import MASKED_HEADER_VALUE, LLMConfig, LLMConfigCreate, LLMConfigUpdate, RequestFormat


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

        await self.collection.insert_one(config_dict)
        return LLMConfig(**config_dict)

    async def get_by_id(self, config_id: str) -> LLMConfig | None:
        """Get LLM configuration by ID"""
        doc = await self.collection.find_one({"id": config_id})
        if doc:
            doc.pop("_id", None)
            return LLMConfig(**doc)
        return None

    async def list_all(self, enabled_only: bool = False) -> list[LLMConfig]:
        """List all LLM configurations"""
        query = {"enabled": True} if enabled_only else {}
        cursor = self.collection.find(query)
        configs = []
        async for doc in cursor:
            doc.pop("_id", None)
            configs.append(LLMConfig(**doc))
        return configs

    async def update(self, config_id: str, update_data: LLMConfigUpdate) -> LLMConfig | None:
        """Update an LLM configuration.

        LLM-05: changing ``api_endpoint`` or ``request_format`` without
        supplying a new ``api_key`` clears the stored key, so a stored
        credential is never sent to a new destination. Header values equal
        to ``MASKED_HEADER_VALUE`` keep their stored value.
        """
        current = await self.get_by_id(config_id)
        if current is None:
            return None

        update_dict = {k: v for k, v in update_data.model_dump().items() if v is not None}
        if not update_dict:
            return current

        if "headers" in update_dict:
            stored = current.headers or {}
            update_dict["headers"] = {
                name: (stored.get(name, "") if value == MASKED_HEADER_VALUE else value)
                for name, value in update_dict["headers"].items()
            }

        endpoint_changed = (
            "api_endpoint" in update_dict and update_dict["api_endpoint"] != current.api_endpoint
        )
        format_changed = "request_format" in update_dict and (
            RequestFormat(update_dict["request_format"]) != current.request_format
        )

        if update_dict.get("api_key"):
            update_dict["api_key_encrypted"] = encrypt_api_key(update_dict.pop("api_key"))
        else:
            update_dict.pop("api_key", None)
            if endpoint_changed or format_changed:
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
