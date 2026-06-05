"""
Unified LLM client using the new LLM configuration system.
Provides backward-compatible interface for existing code.
"""

import logging
from typing import Any

from ..database import db
from ..llm import LLMService

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Unified interface for LLM providers using the new configuration system.
    Maintains backward compatibility with existing code.
    """

    def __init__(self, llm_service: LLMService):
        """
        Initialize LLM client with service.

        Args:
            llm_service: LLM service instance
        """
        self.service = llm_service
        self.config = None
        self.provider = None
        self.model = None
        self.temperature = 0.7
        self.max_tokens = 2000

    async def _ensure_config(self):
        """Ensure LLM configuration is loaded"""
        if not self.config:
            self.config = await self.service.get_default_llm()
            if self.config:
                self.provider = self.config.request_format.value
                self.model = self.config.model_name
                self.temperature = self.config.default_settings.temperature
                self.max_tokens = self.config.default_settings.max_tokens

    def _sanitize_text(self, text: str) -> str:
        """
        Sanitize text to handle encoding issues across all providers.
        Converts ALL text to ASCII-safe characters.
        """
        # First, replace common Unicode characters with ASCII equivalents
        replacements = {
            "\xa0": " ",  # Non-breaking space
            "\u2028": "\n",  # Line separator
            "\u2029": "\n\n",  # Paragraph separator
            "\u2192": "->",  # Rightwards arrow →
            "\u2190": "<-",  # Leftwards arrow ←
            "\u2022": "*",  # Bullet •
            "\u2013": "-",  # En dash –
            "\u2014": "--",  # Em dash —
            "\u2018": "'",  # Left single quote '
            "\u2019": "'",  # Right single quote '
            "\u201c": '"',  # Left double quote "
            "\u201d": '"',  # Right double quote "
            "\u2026": "...",  # Ellipsis …
        }

        for unicode_char, ascii_char in replacements.items():
            text = text.replace(unicode_char, ascii_char)

        # Then encode to ASCII, replacing any remaining non-ASCII with '?'
        text = text.encode("ascii", errors="replace").decode("ascii")

        # Finally, remove control characters except newlines, tabs, carriage returns
        text = "".join(char if ord(char) >= 32 or char in "\n\r\t" else " " for char in text)

        return text

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """
        Get a chat completion from the configured LLM provider.

        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Optional override for temperature
            max_tokens: Optional override for max_tokens

        Returns:
            The completion text
        """
        await self._ensure_config()

        if not self.config:
            raise ValueError("No LLM configuration available")

        # Sanitize all message content before sending to provider
        sanitized_messages = []
        for msg in messages:
            original = msg["content"]
            sanitized = self._sanitize_text(original)
            sanitized_messages.append({"role": msg["role"], "content": sanitized})
            # Log if sanitization changed anything
            if original != sanitized:
                logger.info(
                    f"Sanitized {len(original)} chars, removed {len(original) - len(sanitized)} chars"
                )

        try:
            # Use the new LLM service to make the call
            kwargs = {}
            if temperature is not None:
                kwargs["temperature"] = temperature
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens

            response = await self.service.make_llm_call(self.config, sanitized_messages, **kwargs)

            # Extract text from response based on provider format
            if self.config.request_format.value == "openai":
                return response["choices"][0]["message"]["content"]
            elif self.config.request_format.value == "anthropic":
                return response["content"][0]["text"]
            elif self.config.request_format.value == "google":
                return response["candidates"][0]["content"]["parts"][0]["text"]
            elif self.config.request_format.value == "cohere":
                return response["text"]
            else:
                # Fallback - try to extract text
                logger.warning(f"Unknown response format for {self.config.request_format}")
                return str(response)

        except Exception as e:
            import traceback

            logger.error(f"Error getting completion from {self.provider}: {str(e)}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise


async def get_llm_client() -> LLMClient | None:
    """
    Get an initialized LLM client.

    Returns:
        LLMClient instance or None if not configured
    """
    try:
        service = LLMService(db)
        client = LLMClient(service)

        # Verify configuration exists
        await client._ensure_config()
        if not client.config:
            logger.warning("No LLM configuration available")
            return None

        return client
    except Exception as e:
        logger.error(f"Error initializing LLM client: {str(e)}")
        return None


async def test_llm_connection() -> dict[str, Any]:
    """
    Test the LLM connection with a simple prompt.

    Returns:
        Dict with success status and message
    """
    client = await get_llm_client()

    if not client:
        return {"success": False, "message": "No default LLM configured"}

    try:
        messages = [
            {"role": "user", "content": "Reply with just the word 'success' if you can read this."}
        ]

        response = await client.chat_completion(messages, temperature=0, max_tokens=10)

        return {
            "success": True,
            "message": f"Connection successful! Provider: {client.provider}, Model: {client.model}",
            "response": response,
        }
    except Exception as e:
        return {"success": False, "message": f"Connection failed: {str(e)}"}
