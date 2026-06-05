"""
LLM Service Layer
"""

from typing import Any

import httpx
from motor.motor_asyncio import AsyncIOMotorDatabase

from .encryption import decrypt_api_key
from .models import LLMConfig, RequestFormat
from .repository import LLMRepository


class LLMService:
    """Service for managing LLM configurations and making LLM calls"""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.repo = LLMRepository(db)

    async def get_llm_config(self) -> LLMConfig | None:
        """
        Get LLM configuration.
        Returns the global default LLM configuration.
        """
        return await self.get_default_llm()

    async def get_default_llm(self) -> LLMConfig | None:
        """Get the global default LLM configuration"""
        global_config = await self.db.system_config.find_one({"id": "global_llm_config"})
        if global_config and global_config.get("default_llm_id"):
            return await self.repo.get_by_id(global_config["default_llm_id"])
        return None

    async def set_default_llm(self, config_id: str, updated_by: str) -> bool:
        """Set the global default LLM"""
        # Verify config exists and is enabled
        config = await self.repo.get_by_id(config_id)
        if not config or not config.enabled:
            return False

        # Update or create global config
        result = await self.db.system_config.update_one(
            {"id": "global_llm_config"},
            {
                "$set": {
                    "default_llm_id": config_id,
                    "updated_at": datetime.utcnow(),
                    "updated_by": updated_by,
                }
            },
            upsert=True,
        )
        return True

    async def make_llm_call(self, config: LLMConfig, messages: list, **kwargs) -> dict[str, Any]:
        """
        Make an LLM API call using the provided configuration.

        Args:
            config: LLM configuration to use
            messages: List of message dicts with 'role' and 'content'
            **kwargs: Additional parameters (temperature, max_tokens, etc.)

        Returns:
            Response from the LLM API
        """
        # Decrypt API key
        api_key = decrypt_api_key(config.api_key_encrypted)

        # Merge default settings with provided kwargs
        settings = config.default_settings.model_dump()
        settings.update(kwargs)

        # Build request based on format
        if config.request_format == RequestFormat.OPENAI:
            return await self._call_openai_format(
                config.api_endpoint, api_key, config.model_name, messages, settings, config.headers
            )
        elif config.request_format == RequestFormat.ANTHROPIC:
            return await self._call_anthropic_format(
                config.api_endpoint, api_key, config.model_name, messages, settings, config.headers
            )
        elif config.request_format == RequestFormat.GOOGLE:
            return await self._call_google_format(
                config.api_endpoint, api_key, config.model_name, messages, settings, config.headers
            )
        elif config.request_format == RequestFormat.COHERE:
            return await self._call_cohere_format(
                config.api_endpoint, api_key, config.model_name, messages, settings, config.headers
            )
        else:
            raise ValueError(f"Unsupported request format: {config.request_format}")

    async def _call_openai_format(
        self,
        endpoint: str,
        api_key: str,
        model: str,
        messages: list,
        settings: dict,
        custom_headers: dict | None,
    ) -> dict[str, Any]:
        """Make API call in OpenAI format"""
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if custom_headers:
            headers.update(custom_headers)

        payload = {"model": model, "messages": messages, **settings}

        async with httpx.AsyncClient() as client:
            response = await client.post(endpoint, headers=headers, json=payload, timeout=60.0)
            response.raise_for_status()
            return response.json()

    async def _call_anthropic_format(
        self,
        endpoint: str,
        api_key: str,
        model: str,
        messages: list,
        settings: dict,
        custom_headers: dict | None,
    ) -> dict[str, Any]:
        """Make API call in Anthropic format"""
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        if custom_headers:
            headers.update(custom_headers)

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": settings.get("max_tokens", 4000),
            "temperature": settings.get("temperature", 0.7),
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(endpoint, headers=headers, json=payload, timeout=60.0)
            response.raise_for_status()
            return response.json()

    async def _call_google_format(
        self,
        endpoint: str,
        api_key: str,
        model: str,
        messages: list,
        settings: dict,
        custom_headers: dict | None,
    ) -> dict[str, Any]:
        """Make API call in Google format"""
        headers = {"Content-Type": "application/json"}
        if custom_headers:
            headers.update(custom_headers)

        # Google uses query parameter for API key
        url = f"{endpoint}?key={api_key}"

        # Convert messages to Google format
        contents = []
        for msg in messages:
            contents.append(
                {
                    "role": "user" if msg["role"] == "user" else "model",
                    "parts": [{"text": msg["content"]}],
                }
            )

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": settings.get("temperature", 0.7),
                "maxOutputTokens": settings.get("max_tokens", 4000),
                "topP": settings.get("top_p", 1.0),
            },
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=60.0)
            response.raise_for_status()
            return response.json()

    async def _call_cohere_format(
        self,
        endpoint: str,
        api_key: str,
        model: str,
        messages: list,
        settings: dict,
        custom_headers: dict | None,
    ) -> dict[str, Any]:
        """Make API call in Cohere format"""
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if custom_headers:
            headers.update(custom_headers)

        # Cohere uses chat_history and message format
        chat_history = messages[:-1] if len(messages) > 1 else []
        current_message = messages[-1]["content"] if messages else ""

        payload = {
            "model": model,
            "message": current_message,
            "chat_history": chat_history,
            "temperature": settings.get("temperature", 0.7),
            "max_tokens": settings.get("max_tokens", 4000),
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(endpoint, headers=headers, json=payload, timeout=60.0)
            response.raise_for_status()
            return response.json()


from datetime import datetime
