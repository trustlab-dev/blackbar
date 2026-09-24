"""
LLM service layer: configuration lookup and provider calls.

Every provider call goes through ``_post``, which sets explicit httpx
timeouts, retries 429/5xx and connection failures a bounded number of times
with backoff (honouring Retry-After), and turns any failure into an
``LLMProviderError`` whose text never includes the request URL, headers or
response body (LLM-02, LLM-14).

Adapters (LLM-09):
- OpenAI chat completions: ``max_completion_tokens`` on api.openai.com
  (``max_tokens`` for OpenAI-compatible servers); sampling parameters are
  omitted for reasoning models that reject them.
- Anthropic Messages API: system prompt in the top-level ``system`` field,
  ``anthropic-version: 2023-06-01``; ``temperature`` only for models that
  still accept sampling parameters; text read from ``text`` blocks only.
- Google Gemini ``generateContent``: key in the ``x-goog-api-key`` header,
  system prompt in ``systemInstruction``.
- Cohere: v2 ``/v2/chat`` (OpenAI-style ``messages``) or legacy v1
  ``/v1/chat`` (``preamble`` + ``chat_history`` with USER/CHATBOT roles),
  chosen by the endpoint path.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.config import llm_settings

from .encryption import decrypt_api_key
from .models import LLMConfig, RequestFormat
from .repository import LLMRepository
from .safety import (
    LLMDisabledError,
    LLMEndpointError,
    LLMError,
    LLMProviderError,
    redact_secrets,
    validate_llm_endpoint_static,
)

logger = logging.getLogger(__name__)

ANTHROPIC_VERSION = "2023-06-01"
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}
MAX_RETRY_AFTER_SECONDS = 30.0

# Finish/stop reasons that mean the output was cut off by the token limit.
_TRUNCATION_REASONS = {"length", "max_tokens", "MAX_TOKENS"}


class LLMKeyMissingError(LLMError):
    code = "api_key_required"
    public_message = (
        "The AI provider API key must be re-entered: the endpoint or provider of the "
        "default LLM configuration was changed."
    )

    def public_detail(self) -> str:
        return self.public_message


class LLMBlockedEndpointError(LLMError):
    code = "endpoint_not_allowed"
    public_message = "The configured AI endpoint is not allowed."

    def public_detail(self) -> str:
        return f"{self.public_message} {self.args[0]}" if self.args else self.public_message


@dataclass
class LLMCompletion:
    """Provider-neutral result of one call."""

    text: str
    finish_reason: str | None
    provider: str
    model: str

    @property
    def truncated(self) -> bool:
        return (self.finish_reason or "") in _TRUNCATION_REASONS


# ---------------------------------------------------------------------------
# Model capability helpers
# ---------------------------------------------------------------------------

# Anthropic models that still accept temperature/top_p. Opus 4.7+, Sonnet 5,
# Opus 5.x and the Fable/Mythos family reject sampling parameters with a 400,
# so anything not matching this list gets no sampling parameters.
_ANTHROPIC_SAMPLING_OK = re.compile(
    r"^claude-(3|instant|haiku-4|(opus|sonnet)-4(-[0-6])?(-\d{8})?$|(opus|sonnet)-4-\d{8})"
)
# OpenAI reasoning models reject non-default temperature/top_p.
_OPENAI_REASONING = re.compile(r"^(o\d|gpt-5)")


def anthropic_accepts_sampling(model: str) -> bool:
    return bool(_ANTHROPIC_SAMPLING_OK.match((model or "").lower()))


def _openai_is_reasoning(model: str) -> bool:
    return bool(_OPENAI_REASONING.match((model or "").lower()))


def _split_system(messages: list[dict]) -> tuple[str, list[dict]]:
    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    return "\n\n".join(p for p in system_parts if p), rest


# ---------------------------------------------------------------------------
# Response extraction
# ---------------------------------------------------------------------------


def extract_completion(
    request_format: RequestFormat | str, response: dict[str, Any]
) -> tuple[str, str | None]:
    """Return (text, finish_reason) from a provider response.

    Raises LLMProviderError when the response has no recognisable shape.
    """
    fmt = RequestFormat(request_format).value
    try:
        if fmt == "openai":
            choice = response["choices"][0]
            return (choice["message"].get("content") or ""), choice.get("finish_reason")
        if fmt == "anthropic":
            blocks = response["content"]
            text = "".join(b.get("text", "") for b in blocks if b.get("type", "text") == "text")
            return text, response.get("stop_reason")
        if fmt == "google":
            candidate = response["candidates"][0]
            parts = (candidate.get("content") or {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            return text, candidate.get("finishReason")
        if fmt == "cohere":
            if "message" in response and isinstance(response["message"], dict):  # v2
                content = response["message"].get("content") or []
                text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
                return text, response.get("finish_reason")
            return response["text"], response.get("finish_reason")  # v1
    except (KeyError, IndexError, TypeError, AttributeError):
        raise LLMProviderError(fmt, 200, detail="unexpected response shape") from None
    raise ValueError(f"Unsupported request format: {request_format}")


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class LLMService:
    """Service for managing LLM configurations and making LLM calls"""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.repo = LLMRepository(db)

    async def get_llm_config(self) -> LLMConfig | None:
        """The usable global default LLM configuration (None if unset or disabled)."""
        return await self.get_default_llm()

    async def get_default_llm_id(self) -> str | None:
        global_config = await self.db.system_config.find_one({"id": "global_llm_config"})
        return (global_config or {}).get("default_llm_id")

    async def get_default_llm(self, include_disabled: bool = False) -> LLMConfig | None:
        """The global default LLM configuration.

        A disabled configuration is not returned unless ``include_disabled``
        (LLM-04): turning a config off stops all egress through it.
        """
        default_id = await self.get_default_llm_id()
        if not default_id:
            return None
        config = await self.repo.get_by_id(default_id)
        if config is None or (not config.enabled and not include_disabled):
            return None
        return config

    async def set_default_llm(self, config_id: str, updated_by: str) -> bool:
        """Set the global default LLM"""
        config = await self.repo.get_by_id(config_id)
        if not config or not config.enabled:
            return False

        await self.db.system_config.update_one(
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

    # -- calls -------------------------------------------------------------

    async def complete(self, config: LLMConfig, messages: list, **kwargs) -> LLMCompletion:
        """Make a call and normalise the response to text + finish reason."""
        raw = await self.make_llm_call(config, messages, **kwargs)
        text, finish_reason = extract_completion(config.request_format, raw)
        return LLMCompletion(
            text=text,
            finish_reason=finish_reason,
            provider=config.request_format.value,
            model=config.model_name,
        )

    async def make_llm_call(self, config: LLMConfig, messages: list, **kwargs) -> dict[str, Any]:
        """
        Make an LLM API call using the provided configuration.

        Args:
            config: LLM configuration to use
            messages: List of message dicts with 'role' and 'content'
            **kwargs: temperature / max_tokens / top_p overrides

        Returns:
            The provider's JSON response.

        Raises:
            LLMDisabledError, LLMKeyMissingError, LLMBlockedEndpointError,
            LLMProviderError (never raw httpx errors).
        """
        if not config.enabled:
            raise LLMDisabledError()
        if config.request_format not in (
            RequestFormat.OPENAI,
            RequestFormat.ANTHROPIC,
            RequestFormat.GOOGLE,
            RequestFormat.COHERE,
        ):
            raise ValueError(f"Unsupported request format: {config.request_format}")
        if not config.api_key_encrypted:
            raise LLMKeyMissingError()
        try:
            validate_llm_endpoint_static(config.api_endpoint)
        except LLMEndpointError as exc:
            raise LLMBlockedEndpointError(str(exc)) from None

        api_key = decrypt_api_key(config.api_key_encrypted)

        settings = config.default_settings.model_dump()
        settings.update({k: v for k, v in kwargs.items() if v is not None})

        builders = {
            RequestFormat.OPENAI: self._openai_request,
            RequestFormat.ANTHROPIC: self._anthropic_request,
            RequestFormat.GOOGLE: self._google_request,
            RequestFormat.COHERE: self._cohere_request,
        }
        url, headers, payload = builders[config.request_format](
            config.api_endpoint, api_key, config.model_name, messages, settings
        )
        if config.headers:
            headers.update(config.headers)

        secrets = [api_key, *((config.headers or {}).values())]
        return await self._post(config.request_format.value, url, headers, payload, secrets)

    # -- request builders ----------------------------------------------------

    @staticmethod
    def _openai_request(endpoint, api_key, model, messages, settings):
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload: dict[str, Any] = {"model": model, "messages": messages}
        host = (urlsplit(endpoint).hostname or "").lower()
        reasoning = _openai_is_reasoning(model)
        # api.openai.com deprecated max_tokens and reasoning models reject it;
        # OpenAI-compatible servers (vLLM, Ollama, ...) still expect max_tokens.
        token_field = (
            "max_completion_tokens" if host == "api.openai.com" or reasoning else "max_tokens"
        )
        payload[token_field] = settings.get("max_tokens", 4000)
        if not reasoning:
            payload["temperature"] = settings.get("temperature", 0.7)
            payload["top_p"] = settings.get("top_p", 1.0)
        return endpoint, headers, payload

    @staticmethod
    def _anthropic_request(endpoint, api_key, model, messages, settings):
        headers = {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }
        system, rest = _split_system(messages)
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": settings.get("max_tokens", 4000),
            "messages": [{"role": m["role"], "content": m["content"]} for m in rest],
        }
        if system:
            payload["system"] = system
        if anthropic_accepts_sampling(model):
            payload["temperature"] = settings.get("temperature", 0.7)
        return endpoint, headers, payload

    @staticmethod
    def _google_request(endpoint, api_key, model, messages, settings):
        # Key in a header, never in the URL: httpx error strings and tracing
        # integrations record URLs (LLM-02).
        headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
        system, rest = _split_system(messages)
        payload: dict[str, Any] = {
            "contents": [
                {
                    "role": "user" if m["role"] == "user" else "model",
                    "parts": [{"text": m["content"]}],
                }
                for m in rest
            ],
            "generationConfig": {
                "temperature": settings.get("temperature", 0.7),
                "maxOutputTokens": settings.get("max_tokens", 4000),
                "topP": settings.get("top_p", 1.0),
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        return endpoint, headers, payload

    @staticmethod
    def _cohere_request(endpoint, api_key, model, messages, settings):
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        path = urlsplit(endpoint).path
        if "/v2/" in path:
            payload: dict[str, Any] = {
                "model": model,
                "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
                "temperature": settings.get("temperature", 0.7),
                "max_tokens": settings.get("max_tokens", 4000),
            }
            return endpoint, headers, payload

        system, rest = _split_system(messages)
        current = rest[-1]["content"] if rest else ""
        history = [
            {"role": "USER" if m["role"] == "user" else "CHATBOT", "message": m["content"]}
            for m in rest[:-1]
        ]
        payload = {
            "model": model,
            "message": current,
            "chat_history": history,
            "temperature": settings.get("temperature", 0.7),
            "max_tokens": settings.get("max_tokens", 4000),
        }
        if system:
            payload["preamble"] = system
        return endpoint, headers, payload

    # -- transport -----------------------------------------------------------

    @staticmethod
    def _retry_delay(attempt: int, response: httpx.Response | None) -> float:
        if response is not None:
            retry_after = response.headers.get("retry-after")
            if retry_after:
                try:
                    return min(float(retry_after), MAX_RETRY_AFTER_SECONDS)
                except ValueError:
                    pass
        base = llm_settings.retry_base_delay
        if base <= 0:
            return 0.0
        return min(base * (2**attempt) + random.uniform(0, base), MAX_RETRY_AFTER_SECONDS)

    async def _post(
        self,
        provider: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        secrets: list[str],
    ) -> dict[str, Any]:
        timeout = httpx.Timeout(
            connect=llm_settings.connect_timeout,
            read=llm_settings.read_timeout,
            write=30.0,
            pool=10.0,
        )
        attempts = llm_settings.max_retries + 1
        failure: LLMProviderError | None = None

        for attempt in range(attempts):
            response: httpx.Response | None = None
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(url, headers=headers, json=payload)
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError) as exc:
                failure = LLMProviderError(
                    provider, None, detail=redact_secrets(f"{type(exc).__name__}", secrets)
                )
                retryable = True
            except httpx.HTTPError as exc:
                # Read/write timeouts and other transport errors: a read
                # timeout already waited the full budget, so do not repeat it.
                failure = LLMProviderError(
                    provider, None, detail=redact_secrets(f"{type(exc).__name__}", secrets)
                )
                retryable = False
            else:
                if response.status_code < 400:
                    try:
                        return response.json()
                    except ValueError:
                        failure = LLMProviderError(
                            provider, response.status_code, detail="non-JSON response"
                        )
                        break
                failure = LLMProviderError(
                    provider,
                    response.status_code,
                    detail=redact_secrets(response.text[:500], secrets),
                )
                retryable = response.status_code in RETRYABLE_STATUS

            if not retryable or attempt == attempts - 1:
                break
            await asyncio.sleep(self._retry_delay(attempt, response))

        assert failure is not None
        logger.warning(
            "LLM provider call failed: %s (reference %s, attempts %d)",
            failure,
            failure.reference,
            attempt + 1,
        )
        logger.debug(
            "LLM provider error detail (reference %s): %s", failure.reference, failure.detail
        )
        raise failure
