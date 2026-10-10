"""
Unified LLM client using the LLM configuration system.
Provides a backward-compatible interface for existing code.
"""

import logging
import unicodedata
from typing import Any

from ..database import db
from ..llm import LLMService
from ..llm.safety import LLMDisabledError, LLMError
from ..llm.service import LLMCompletion, extract_completion

logger = logging.getLogger(__name__)


def normalize_prompt_text(text: str) -> str:
    """Prepare text for a provider: NFC-normalise and replace control
    characters (except newline, carriage return and tab) with spaces.

    All providers accept UTF-8, so non-ASCII text is sent unchanged (LLM-11):
    converting "José Côté" to "Jos? C?t?" made the model quote strings that
    could not be found on the page.
    """
    text = unicodedata.normalize("NFC", text or "")
    return "".join(
        char if (ord(char) >= 32 and char != "\x7f") or char in "\n\r\t" else " " for char in text
    )


class LLMClient:
    """
    Unified interface for LLM providers using the configuration system.
    """

    def __init__(self, llm_service: LLMService):
        self.service = llm_service
        self.config = None
        self.provider = None
        self.model = None
        self.config_id = None
        self.endpoint = None
        self.temperature = 0.7
        self.max_tokens = 2000

    async def _ensure_config(self):
        """Load the default configuration.

        Raises LLMDisabledError when the default config exists but is
        switched off, so callers can report "AI disabled" instead of
        "not configured" (LLM-04).
        """
        if not self.config:
            config = await self.service.get_default_llm(include_disabled=True)
            if config is not None and config.enabled is False:
                raise LLMDisabledError()
            self.config = config
            if self.config:
                self.provider = self.config.request_format.value
                self.model = self.config.model_name
                self.config_id = self.config.id
                self.endpoint = self.config.api_endpoint
                self.temperature = self.config.default_settings.temperature
                self.max_tokens = self.config.default_settings.max_tokens

    def _sanitize_text(self, text: str) -> str:
        return normalize_prompt_text(text)

    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMCompletion:
        """Run a completion and return text plus finish reason."""
        await self._ensure_config()

        if not self.config:
            raise ValueError("No LLM configuration available")

        sanitized = [
            {"role": msg["role"], "content": self._sanitize_text(msg["content"])}
            for msg in messages
        ]
        kwargs: dict[str, Any] = {}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        try:
            raw = await self.service.make_llm_call(self.config, sanitized, **kwargs)
            text, finish_reason = extract_completion(self.config.request_format, raw)
            return LLMCompletion(
                text=text,
                finish_reason=finish_reason,
                provider=self.config.request_format.value,
                model=self.config.model_name,
            )
        except LLMError as exc:
            logger.error(
                "LLM completion failed (provider=%s, reference=%s): %s",
                self.provider,
                exc.reference,
                exc,
            )
            raise
        except Exception as exc:
            logger.error(
                "LLM completion failed (provider=%s): %s", self.provider, type(exc).__name__
            )
            raise

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Get the completion text from the configured LLM provider."""
        completion = await self.complete(messages, temperature=temperature, max_tokens=max_tokens)
        return completion.text


async def get_llm_client() -> LLMClient | None:
    """
    Get an initialized LLM client.

    Returns:
        LLMClient instance or None if no default LLM is configured.

    Raises:
        LLMDisabledError: the default LLM configuration is switched off.
    """
    try:
        service = LLMService(db)
        client = LLMClient(service)

        await client._ensure_config()
        if not client.config:
            logger.warning("No LLM configuration available")
            return None

        return client
    except LLMDisabledError:
        raise
    except Exception as e:
        logger.error(f"Error initializing LLM client: {type(e).__name__}")
        return None


async def test_llm_connection() -> dict[str, Any]:
    """
    Test the LLM connection with a simple prompt.

    Returns:
        Dict with success status and message
    """
    try:
        client = await get_llm_client()
    except LLMDisabledError as exc:
        return {"success": False, "message": exc.public_detail()}

    if not client:
        return {"success": False, "message": "No default LLM configured"}

    try:
        messages = [
            {"role": "system", "content": "You are a connection check. Reply briefly."},
            {"role": "user", "content": "Reply with just the word 'success' if you can read this."},
        ]

        response = await client.chat_completion(messages, temperature=0, max_tokens=256)

        return {
            "success": True,
            "message": f"Connection successful! Provider: {client.provider}, Model: {client.model}",
            "response": response,
        }
    except LLMError as e:
        return {"success": False, "message": f"Connection failed: {e.public_detail()}"}
    except Exception as e:
        return {"success": False, "message": f"Connection failed: {type(e).__name__}"}
