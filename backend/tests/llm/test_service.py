"""Tests for `src.llm.service`.

Phase 2.6. Target >=80% line coverage on src.llm.service.

LLMService orchestrates four provider formats (OpenAI / Anthropic / Google /
Cohere) via raw httpx requests. We mock every provider URL via respx — no
real network calls.

Reality pins:
- `get_llm_config()` is a thin wrapper around `get_default_llm()`.
- `get_default_llm()` returns None if `system_config.global_llm_config` is
  missing OR if `default_llm_id` does not resolve to an enabled config.
- `set_default_llm()` returns False if the target config doesn't exist or
  is disabled; returns True (and upserts `system_config.global_llm_config`)
  on success. NOTE: the source code has a `from datetime import datetime`
  at the bottom of the module — verified working via this test.
- `make_llm_call()` routes by `request_format`; raises ValueError on unknown.
- API key decryption happens inside `make_llm_call`, not the formatters.
- Anthropic format reads `max_tokens` / `temperature` directly from settings.
- Google format puts the API key in the URL query, converts messages to its
  `contents` shape, and packs settings into `generationConfig`.
- Cohere format splits messages: all but last -> `chat_history`, last ->
  `message`. Empty messages list yields empty `message` string.
"""

from __future__ import annotations

import json
from datetime import datetime

import httpx
import pytest
import respx
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.llm.encryption import encrypt_api_key
from src.llm.models import (
    LLMConfig,
    LLMConfigCreate,
    LLMSettings,
    RequestFormat,
)
from src.llm.repository import LLMRepository
from src.llm.service import LLMService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_config(
    db: AsyncIOMotorDatabase,
    *,
    name: str = "Provider",
    request_format: RequestFormat = RequestFormat.OPENAI,
    api_endpoint: str = "https://api.openai.com/v1/chat/completions",
    model_name: str = "gpt-4o-mini",
    api_key: str = "sk-real-key",
    enabled: bool = True,
    headers: dict | None = None,
) -> LLMConfig:
    repo = LLMRepository(db)
    return await repo.create(
        LLMConfigCreate(
            name=name,
            enabled=enabled,
            api_endpoint=api_endpoint,
            model_name=model_name,
            request_format=request_format,
            api_key=api_key,
            headers=headers,
            default_settings=LLMSettings(),
        ),
        created_by="test-admin",
    )


# ---------------------------------------------------------------------------
# get_llm_config / get_default_llm
# ---------------------------------------------------------------------------


class TestGetDefaultLLM:
    async def test_returns_none_when_global_config_missing(self, db: AsyncIOMotorDatabase) -> None:
        svc = LLMService(db)
        assert await svc.get_default_llm() is None
        # get_llm_config is a thin wrapper
        assert await svc.get_llm_config() is None

    async def test_returns_none_when_default_llm_id_unset(self, db: AsyncIOMotorDatabase) -> None:
        await db.system_config.insert_one({"id": "global_llm_config", "default_llm_id": None})
        svc = LLMService(db)
        assert await svc.get_default_llm() is None

    async def test_returns_config_when_default_set(self, db: AsyncIOMotorDatabase) -> None:
        cfg = await _seed_config(db)
        await db.system_config.insert_one({"id": "global_llm_config", "default_llm_id": cfg.id})
        svc = LLMService(db)
        result = await svc.get_default_llm()
        assert result is not None
        assert result.id == cfg.id


# ---------------------------------------------------------------------------
# set_default_llm
# ---------------------------------------------------------------------------


class TestSetDefaultLLM:
    async def test_set_default_succeeds_for_enabled_config(self, db: AsyncIOMotorDatabase) -> None:
        cfg = await _seed_config(db)
        svc = LLMService(db)
        ok = await svc.set_default_llm(cfg.id, updated_by="admin-1")
        assert ok is True

        # Persisted in system_config
        doc = await db.system_config.find_one({"id": "global_llm_config"})
        assert doc is not None
        assert doc["default_llm_id"] == cfg.id
        assert doc["updated_by"] == "admin-1"
        assert isinstance(doc["updated_at"], datetime)

    async def test_set_default_rejects_missing_config(self, db: AsyncIOMotorDatabase) -> None:
        svc = LLMService(db)
        assert await svc.set_default_llm("does-not-exist", "admin") is False
        # Nothing was written
        assert await db.system_config.find_one({"id": "global_llm_config"}) is None

    async def test_set_default_rejects_disabled_config(self, db: AsyncIOMotorDatabase) -> None:
        cfg = await _seed_config(db, enabled=False)
        svc = LLMService(db)
        assert await svc.set_default_llm(cfg.id, "admin") is False


# ---------------------------------------------------------------------------
# make_llm_call — provider routing
# ---------------------------------------------------------------------------


class TestMakeLLMCallRouting:
    async def test_unknown_request_format_raises(self, db: AsyncIOMotorDatabase) -> None:
        """Hand-build an LLMConfig with a value the router won't recognize.

        Note: RequestFormat.CUSTOM is in the enum but has no `_call_custom_format`
        method — falls through to the `else` branch.
        """
        svc = LLMService(db)
        # Construct an LLMConfig directly to bypass create() validation
        cfg = LLMConfig(
            id="test",
            name="Custom",
            api_endpoint="https://example.test/v1/chat",
            model_name="custom-model",
            request_format=RequestFormat.CUSTOM,
            api_key_encrypted=encrypt_api_key("sk-x"),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            created_by="u",
        )
        with pytest.raises(ValueError, match="Unsupported request format"):
            await svc.make_llm_call(cfg, [{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# _call_openai_format
# ---------------------------------------------------------------------------


class TestOpenAIFormat:
    @respx.mock
    async def test_openai_call_sends_bearer_auth_and_payload(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        cfg = await _seed_config(
            db,
            request_format=RequestFormat.OPENAI,
            api_endpoint="https://api.openai.com/v1/chat/completions",
            model_name="gpt-4o-mini",
            api_key="sk-openai-key",
        )

        route = respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "test",
                    "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                },
            )
        )

        svc = LLMService(db)
        result = await svc.make_llm_call(cfg, [{"role": "user", "content": "Hello"}])

        assert result["id"] == "test"
        assert route.called
        sent = route.calls.last.request
        assert sent.headers["Authorization"] == "Bearer sk-openai-key"
        body = json.loads(sent.content)
        assert body["model"] == "gpt-4o-mini"
        assert body["messages"] == [{"role": "user", "content": "Hello"}]
        # Default settings merged in
        assert body["temperature"] == 0.7
        assert body["max_tokens"] == 4000

    @respx.mock
    async def test_openai_kwargs_override_defaults(self, db: AsyncIOMotorDatabase) -> None:
        cfg = await _seed_config(db)
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json={})
        )

        svc = LLMService(db)
        await svc.make_llm_call(
            cfg,
            [{"role": "user", "content": "x"}],
            temperature=0.1,
            max_tokens=500,
        )

        sent_body = json.loads(respx.calls.last.request.content)
        assert sent_body["temperature"] == 0.1
        assert sent_body["max_tokens"] == 500

    @respx.mock
    async def test_openai_custom_headers_merged(self, db: AsyncIOMotorDatabase) -> None:
        cfg = await _seed_config(db, headers={"X-Org-Id": "org-7", "X-Custom": "yes"})
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json={})
        )

        svc = LLMService(db)
        await svc.make_llm_call(cfg, [{"role": "user", "content": "x"}])

        headers = respx.calls.last.request.headers
        assert headers["X-Org-Id"] == "org-7"
        assert headers["X-Custom"] == "yes"
        assert headers["Authorization"].startswith("Bearer ")

    @respx.mock
    async def test_openai_raises_on_http_error(self, db: AsyncIOMotorDatabase) -> None:
        cfg = await _seed_config(db)
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(500, json={"error": "boom"})
        )

        svc = LLMService(db)
        with pytest.raises(httpx.HTTPStatusError):
            await svc.make_llm_call(cfg, [{"role": "user", "content": "x"}])


# ---------------------------------------------------------------------------
# _call_anthropic_format
# ---------------------------------------------------------------------------


class TestAnthropicFormat:
    @respx.mock
    async def test_anthropic_call_sends_xapikey_and_version_headers(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        cfg = await _seed_config(
            db,
            request_format=RequestFormat.ANTHROPIC,
            api_endpoint="https://api.anthropic.com/v1/messages",
            model_name="claude-3-5-sonnet-20241022",
            api_key="sk-ant-key",
        )
        respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "msg",
                    "content": [{"type": "text", "text": "ok"}],
                },
            )
        )

        svc = LLMService(db)
        result = await svc.make_llm_call(cfg, [{"role": "user", "content": "Hi"}])
        assert result["id"] == "msg"

        sent = respx.calls.last.request
        assert sent.headers["x-api-key"] == "sk-ant-key"
        assert sent.headers["anthropic-version"] == "2023-06-01"
        body = json.loads(sent.content)
        assert body["model"] == "claude-3-5-sonnet-20241022"
        # Defaults applied
        assert body["max_tokens"] == 4000
        assert body["temperature"] == 0.7

    @respx.mock
    async def test_anthropic_custom_headers_merged(self, db: AsyncIOMotorDatabase) -> None:
        cfg = await _seed_config(
            db,
            request_format=RequestFormat.ANTHROPIC,
            api_endpoint="https://api.anthropic.com/v1/messages",
            headers={"X-Trace-Id": "abc-123"},
        )
        respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(200, json={})
        )
        svc = LLMService(db)
        await svc.make_llm_call(cfg, [{"role": "user", "content": "x"}])
        assert respx.calls.last.request.headers["X-Trace-Id"] == "abc-123"


# ---------------------------------------------------------------------------
# _call_google_format
# ---------------------------------------------------------------------------


class TestGoogleFormat:
    @respx.mock
    async def test_google_call_uses_query_param_api_key_and_contents_shape(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        cfg = await _seed_config(
            db,
            request_format=RequestFormat.GOOGLE,
            api_endpoint="https://generativelanguage.googleapis.com/v1/models/gemini-pro:generateContent",
            model_name="gemini-pro",
            api_key="goog-secret",
        )
        # Google appends `?key=...` so we match the prefix
        route = respx.post(
            url__startswith="https://generativelanguage.googleapis.com/v1/models/gemini-pro:generateContent"
        ).mock(
            return_value=httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
            )
        )

        svc = LLMService(db)
        result = await svc.make_llm_call(
            cfg,
            [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello"},
            ],
        )
        assert "candidates" in result
        assert route.called

        sent = route.calls.last.request
        # API key in query, not header
        assert "key=goog-secret" in str(sent.url)
        # No Authorization header for Google
        assert "Authorization" not in sent.headers

        body = json.loads(sent.content)
        # Content shape: each message becomes {"role": ..., "parts": [...]}
        assert len(body["contents"]) == 2
        assert body["contents"][0] == {
            "role": "user",
            "parts": [{"text": "Hi"}],
        }
        # Non-"user" roles map to "model"
        assert body["contents"][1]["role"] == "model"
        # generationConfig packs defaults
        cfg_blk = body["generationConfig"]
        assert cfg_blk["temperature"] == 0.7
        assert cfg_blk["maxOutputTokens"] == 4000
        assert cfg_blk["topP"] == 1.0

    @respx.mock
    async def test_google_custom_headers_merged(self, db: AsyncIOMotorDatabase) -> None:
        cfg = await _seed_config(
            db,
            request_format=RequestFormat.GOOGLE,
            api_endpoint="https://google.test/generate",
            headers={"X-Goog-User-Project": "proj-1"},
        )
        respx.post(url__startswith="https://google.test/generate").mock(
            return_value=httpx.Response(200, json={})
        )
        svc = LLMService(db)
        await svc.make_llm_call(cfg, [{"role": "user", "content": "x"}])
        assert respx.calls.last.request.headers["X-Goog-User-Project"] == "proj-1"


# ---------------------------------------------------------------------------
# _call_cohere_format
# ---------------------------------------------------------------------------


class TestCohereFormat:
    @respx.mock
    async def test_cohere_splits_last_message_from_history(self, db: AsyncIOMotorDatabase) -> None:
        cfg = await _seed_config(
            db,
            request_format=RequestFormat.COHERE,
            api_endpoint="https://api.cohere.ai/v1/chat",
            model_name="command-r",
            api_key="co-key",
        )
        respx.post("https://api.cohere.ai/v1/chat").mock(
            return_value=httpx.Response(200, json={"text": "ok"})
        )

        svc = LLMService(db)
        await svc.make_llm_call(
            cfg,
            [
                {"role": "user", "content": "First"},
                {"role": "assistant", "content": "Reply"},
                {"role": "user", "content": "Latest"},
            ],
        )

        sent = respx.calls.last.request
        assert sent.headers["Authorization"] == "Bearer co-key"
        body = json.loads(sent.content)
        assert body["model"] == "command-r"
        assert body["message"] == "Latest"
        assert body["chat_history"] == [
            {"role": "user", "content": "First"},
            {"role": "assistant", "content": "Reply"},
        ]
        assert body["temperature"] == 0.7
        assert body["max_tokens"] == 4000

    @respx.mock
    async def test_cohere_empty_messages_yields_empty_message(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        cfg = await _seed_config(
            db,
            request_format=RequestFormat.COHERE,
            api_endpoint="https://api.cohere.ai/v1/chat",
        )
        respx.post("https://api.cohere.ai/v1/chat").mock(return_value=httpx.Response(200, json={}))
        svc = LLMService(db)
        await svc.make_llm_call(cfg, [])

        body = json.loads(respx.calls.last.request.content)
        assert body["message"] == ""
        assert body["chat_history"] == []

    @respx.mock
    async def test_cohere_single_message_history_is_empty(self, db: AsyncIOMotorDatabase) -> None:
        cfg = await _seed_config(
            db,
            request_format=RequestFormat.COHERE,
            api_endpoint="https://api.cohere.ai/v1/chat",
        )
        respx.post("https://api.cohere.ai/v1/chat").mock(return_value=httpx.Response(200, json={}))
        svc = LLMService(db)
        await svc.make_llm_call(cfg, [{"role": "user", "content": "Only"}])

        body = json.loads(respx.calls.last.request.content)
        assert body["message"] == "Only"
        assert body["chat_history"] == []

    @respx.mock
    async def test_cohere_custom_headers_merged(self, db: AsyncIOMotorDatabase) -> None:
        cfg = await _seed_config(
            db,
            request_format=RequestFormat.COHERE,
            api_endpoint="https://api.cohere.ai/v1/chat",
            headers={"X-Client": "blackbar"},
        )
        respx.post("https://api.cohere.ai/v1/chat").mock(return_value=httpx.Response(200, json={}))
        svc = LLMService(db)
        await svc.make_llm_call(cfg, [{"role": "user", "content": "x"}])
        assert respx.calls.last.request.headers["X-Client"] == "blackbar"
