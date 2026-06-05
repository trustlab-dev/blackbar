"""Tests for ``src.utils.llm_client``.

``LLMClient`` is a thin wrapper around ``LLMService`` that exposes a
provider-agnostic ``chat_completion`` interface. Tests use a stubbed
``LLMService`` (no real network calls) and verify:

- Text sanitization replaces all listed Unicode -> ASCII pairs
- ``_ensure_config`` lazy-loads from the service exactly once
- Each of the four provider response shapes (openai/anthropic/google/cohere)
  is parsed correctly
- Temperature / max_tokens overrides are forwarded to the service
- ``get_llm_client`` returns None when no config is set up
- ``test_llm_connection`` exercises the integration entry point

Note: ``src.utils.llm_client`` imports ``from ..database import db`` at
module top, so the test plan's "no ``from src.database import db``"
caveat applies — we only call ``get_llm_client`` through patches.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.llm.models import LLMConfig, LLMSettings, RequestFormat
from src.utils.llm_client import LLMClient, get_llm_client, test_llm_connection


def _make_config(provider: str = "openai") -> LLMConfig:
    return LLMConfig(
        id="cfg-1",
        name="Test config",
        enabled=True,
        api_endpoint="https://api.example.test/v1",
        model_name="test-model",
        request_format=RequestFormat(provider),
        default_settings=LLMSettings(temperature=0.5, max_tokens=1000),
        headers=None,
        notes=None,
        api_key_encrypted="encrypted-blob",
        created_at=datetime(2024, 1, 1),
        updated_at=datetime(2024, 1, 1),
        created_by="user-1",
    )


# ---------------------------------------------------------------------------
# _sanitize_text
# ---------------------------------------------------------------------------


class TestSanitizeText:
    def test_replaces_listed_unicode_chars(self) -> None:
        svc = MagicMock()
        client = LLMClient(svc)
        text = "Hello\xa0world—with…everything"
        clean = client._sanitize_text(text)
        # nbsp -> space, em-dash -> --, ellipsis -> ...
        assert "\xa0" not in clean
        assert "—" not in clean
        assert "…" not in clean
        assert "Hello world--with...everything" == clean

    def test_replaces_all_quote_styles(self) -> None:
        svc = MagicMock()
        client = LLMClient(svc)
        clean = client._sanitize_text("‘a’ “b”")
        assert clean == "'a' \"b\""

    def test_replaces_arrows_and_bullets(self) -> None:
        svc = MagicMock()
        client = LLMClient(svc)
        clean = client._sanitize_text("→ ← •")
        assert clean == "-> <- *"

    def test_non_ascii_chars_replaced_with_question_mark(self) -> None:
        svc = MagicMock()
        client = LLMClient(svc)
        # An unhandled non-ascii char (CJK)
        clean = client._sanitize_text("中")
        assert clean == "?"

    def test_control_chars_replaced_with_space(self) -> None:
        svc = MagicMock()
        client = LLMClient(svc)
        # \x01 is a control char; \n/\r/\t are preserved
        clean = client._sanitize_text("a\x01b\nc\tx")
        assert "a b\nc\tx" == clean


# ---------------------------------------------------------------------------
# _ensure_config
# ---------------------------------------------------------------------------


class TestEnsureConfig:
    @pytest.mark.asyncio
    async def test_loads_config_from_service(self) -> None:
        svc = MagicMock()
        cfg = _make_config()
        svc.get_default_llm = AsyncMock(return_value=cfg)
        client = LLMClient(svc)

        await client._ensure_config()
        assert client.config is cfg
        assert client.provider == "openai"
        assert client.model == "test-model"
        assert client.temperature == 0.5
        assert client.max_tokens == 1000

    @pytest.mark.asyncio
    async def test_skips_loading_when_already_configured(self) -> None:
        svc = MagicMock()
        cfg = _make_config()
        svc.get_default_llm = AsyncMock(return_value=cfg)
        client = LLMClient(svc)

        await client._ensure_config()
        # Reset call counter
        svc.get_default_llm.reset_mock()
        await client._ensure_config()
        svc.get_default_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_config_leaves_provider_unset(self) -> None:
        svc = MagicMock()
        svc.get_default_llm = AsyncMock(return_value=None)
        client = LLMClient(svc)
        await client._ensure_config()
        assert client.config is None
        assert client.provider is None


# ---------------------------------------------------------------------------
# chat_completion — provider parsing
# ---------------------------------------------------------------------------


class TestChatCompletion:
    @pytest.mark.asyncio
    async def test_openai_response_parsing(self) -> None:
        svc = MagicMock()
        svc.get_default_llm = AsyncMock(return_value=_make_config("openai"))
        svc.make_llm_call = AsyncMock(
            return_value={
                "choices": [{"message": {"content": "openai-reply"}}],
            }
        )
        client = LLMClient(svc)
        reply = await client.chat_completion([{"role": "user", "content": "hi"}])
        assert reply == "openai-reply"

    @pytest.mark.asyncio
    async def test_anthropic_response_parsing(self) -> None:
        svc = MagicMock()
        svc.get_default_llm = AsyncMock(return_value=_make_config("anthropic"))
        svc.make_llm_call = AsyncMock(return_value={"content": [{"text": "anthropic-reply"}]})
        client = LLMClient(svc)
        reply = await client.chat_completion([{"role": "user", "content": "hi"}])
        assert reply == "anthropic-reply"

    @pytest.mark.asyncio
    async def test_google_response_parsing(self) -> None:
        svc = MagicMock()
        svc.get_default_llm = AsyncMock(return_value=_make_config("google"))
        svc.make_llm_call = AsyncMock(
            return_value={"candidates": [{"content": {"parts": [{"text": "google-reply"}]}}]}
        )
        client = LLMClient(svc)
        reply = await client.chat_completion([{"role": "user", "content": "hi"}])
        assert reply == "google-reply"

    @pytest.mark.asyncio
    async def test_cohere_response_parsing(self) -> None:
        svc = MagicMock()
        svc.get_default_llm = AsyncMock(return_value=_make_config("cohere"))
        svc.make_llm_call = AsyncMock(return_value={"text": "cohere-reply"})
        client = LLMClient(svc)
        reply = await client.chat_completion([{"role": "user", "content": "hi"}])
        assert reply == "cohere-reply"

    @pytest.mark.asyncio
    async def test_unknown_format_falls_back_to_str(self) -> None:
        """Pin: an unrecognized request_format logs a warning and
        stringifies the response."""
        svc = MagicMock()
        cfg = _make_config("openai")
        # Patch the request_format to a value the function doesn't branch on
        cfg.request_format = RequestFormat.CUSTOM
        svc.get_default_llm = AsyncMock(return_value=cfg)
        svc.make_llm_call = AsyncMock(return_value={"raw": "data"})
        client = LLMClient(svc)
        reply = await client.chat_completion([{"role": "user", "content": "hi"}])
        assert "raw" in reply

    @pytest.mark.asyncio
    async def test_temperature_and_max_tokens_overrides_forwarded(self) -> None:
        svc = MagicMock()
        svc.get_default_llm = AsyncMock(return_value=_make_config("openai"))
        svc.make_llm_call = AsyncMock(return_value={"choices": [{"message": {"content": "ok"}}]})
        client = LLMClient(svc)
        await client.chat_completion(
            [{"role": "user", "content": "hi"}], temperature=0.1, max_tokens=50
        )
        call_kwargs = svc.make_llm_call.call_args.kwargs
        assert call_kwargs["temperature"] == 0.1
        assert call_kwargs["max_tokens"] == 50

    @pytest.mark.asyncio
    async def test_no_config_raises_value_error(self) -> None:
        svc = MagicMock()
        svc.get_default_llm = AsyncMock(return_value=None)
        client = LLMClient(svc)
        with pytest.raises(ValueError, match="No LLM configuration"):
            await client.chat_completion([{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_service_exception_propagates(self) -> None:
        svc = MagicMock()
        svc.get_default_llm = AsyncMock(return_value=_make_config("openai"))
        svc.make_llm_call = AsyncMock(side_effect=RuntimeError("provider down"))
        client = LLMClient(svc)
        with pytest.raises(RuntimeError, match="provider down"):
            await client.chat_completion([{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_sanitizes_messages_before_forwarding(self) -> None:
        svc = MagicMock()
        svc.get_default_llm = AsyncMock(return_value=_make_config("openai"))
        svc.make_llm_call = AsyncMock(return_value={"choices": [{"message": {"content": "ok"}}]})
        client = LLMClient(svc)
        await client.chat_completion([{"role": "user", "content": "hello—world"}])
        sent_messages = svc.make_llm_call.call_args.args[1]
        assert "—" not in sent_messages[0]["content"]
        assert "--" in sent_messages[0]["content"]


# ---------------------------------------------------------------------------
# get_llm_client
# ---------------------------------------------------------------------------


class TestGetLlmClient:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_config_available(self) -> None:
        fake_service = MagicMock()
        fake_service.get_default_llm = AsyncMock(return_value=None)

        with patch(
            "src.utils.llm_client.LLMService",
            return_value=fake_service,
        ):
            result = await get_llm_client()
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_client_when_config_present(self) -> None:
        fake_service = MagicMock()
        fake_service.get_default_llm = AsyncMock(return_value=_make_config())

        with patch(
            "src.utils.llm_client.LLMService",
            return_value=fake_service,
        ):
            result = await get_llm_client()
        assert result is not None
        assert isinstance(result, LLMClient)

    @pytest.mark.asyncio
    async def test_returns_none_on_service_initialization_failure(self) -> None:
        with patch(
            "src.utils.llm_client.LLMService",
            side_effect=RuntimeError("db connect failed"),
        ):
            result = await get_llm_client()
        assert result is None


# ---------------------------------------------------------------------------
# test_llm_connection
# ---------------------------------------------------------------------------


class TestTestLlmConnection:
    @pytest.mark.asyncio
    async def test_returns_failure_when_no_client(self) -> None:
        with patch(
            "src.utils.llm_client.get_llm_client",
            new=AsyncMock(return_value=None),
        ):
            result = await test_llm_connection()
        assert result["success"] is False
        # Copy was tightened in 6ef0929: "No default LLM configured"
        # (was "LLM not configured") so operators know what to do.
        assert "no default llm" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_returns_success_on_happy_path(self) -> None:
        fake_client = MagicMock()
        fake_client.provider = "openai"
        fake_client.model = "gpt-4o"
        fake_client.chat_completion = AsyncMock(return_value="success")

        with patch(
            "src.utils.llm_client.get_llm_client",
            new=AsyncMock(return_value=fake_client),
        ):
            result = await test_llm_connection()
        assert result["success"] is True
        assert result["response"] == "success"
        assert "openai" in result["message"]

    @pytest.mark.asyncio
    async def test_returns_failure_when_completion_raises(self) -> None:
        fake_client = MagicMock()
        fake_client.provider = "openai"
        fake_client.model = "gpt-4o"
        fake_client.chat_completion = AsyncMock(side_effect=RuntimeError("boom"))

        with patch(
            "src.utils.llm_client.get_llm_client",
            new=AsyncMock(return_value=fake_client),
        ):
            result = await test_llm_connection()
        assert result["success"] is False
        assert "boom" in result["message"]
