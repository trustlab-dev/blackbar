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
- Anthropic format sends the system prompt in the top-level `system` field
  and only sends `temperature` to models that still accept it (LLM-09).
- Google format sends the key in `x-goog-api-key` (never the URL, LLM-02) and
  the system prompt as `systemInstruction`.
- Cohere v1 uses `preamble` + `chat_history` (USER/CHATBOT); v2 uses
  OpenAI-style `messages`.
- Provider failures raise `LLMProviderError`, whose text never contains the
  key; 429/5xx are retried a bounded number of times.
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
from src.llm.safety import LLMDisabledError, LLMProviderError
from src.llm.service import LLMKeyMissingError, LLMService

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
        # Default settings merged in; api.openai.com uses max_completion_tokens
        assert body["temperature"] == 0.7
        assert body["max_completion_tokens"] == 4000
        assert "max_tokens" not in body

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
        assert sent_body["max_completion_tokens"] == 500

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
        with pytest.raises(LLMProviderError) as excinfo:
            await svc.make_llm_call(cfg, [{"role": "user", "content": "x"}])
        assert excinfo.value.status_code == 500


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
            model_name="claude-sonnet-5",
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
        assert body["model"] == "claude-sonnet-5"
        assert body["max_tokens"] == 4000
        # Sonnet 5 rejects sampling parameters
        assert "temperature" not in body

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
    async def test_google_call_uses_header_api_key_and_contents_shape(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "test-gemini-model:generateContent"
        )
        cfg = await _seed_config(
            db,
            request_format=RequestFormat.GOOGLE,
            api_endpoint=endpoint,
            model_name="test-gemini-model",
            api_key="goog-secret",
        )
        route = respx.post(endpoint).mock(
            return_value=httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
            )
        )

        svc = LLMService(db)
        result = await svc.make_llm_call(
            cfg,
            [
                {"role": "system", "content": "Be terse"},
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello"},
            ],
        )
        assert "candidates" in result
        sent = route.calls.last.request
        # LLM-02: key in the header, never in the URL
        assert "goog-secret" not in str(sent.url)
        assert "key=" not in str(sent.url)
        assert sent.headers["x-goog-api-key"] == "goog-secret"
        assert "Authorization" not in sent.headers

        body = json.loads(sent.content)
        assert body["systemInstruction"] == {"parts": [{"text": "Be terse"}]}
        assert body["contents"] == [
            {"role": "user", "parts": [{"text": "Hi"}]},
            {"role": "model", "parts": [{"text": "Hello"}]},
        ]
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
        respx.post("https://google.test/generate").mock(return_value=httpx.Response(200, json={}))
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
            model_name="test-command-model",
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
        assert body["model"] == "test-command-model"
        assert body["message"] == "Latest"
        assert body["chat_history"] == [
            {"role": "USER", "message": "First"},
            {"role": "CHATBOT", "message": "Reply"},
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


# ---------------------------------------------------------------------------
# Security-review 2026-09 (LLM-02, LLM-04, LLM-05, LLM-09, LLM-14)
# ---------------------------------------------------------------------------


class TestDefaultHonoursEnabled:
    async def test_disabled_default_is_not_returned(self, db: AsyncIOMotorDatabase) -> None:
        cfg = await _seed_config(db)
        await db.system_config.insert_one({"id": "global_llm_config", "default_llm_id": cfg.id})
        await db.llm_configs.update_one({"id": cfg.id}, {"$set": {"enabled": False}})
        svc = LLMService(db)
        assert await svc.get_default_llm() is None
        included = await svc.get_default_llm(include_disabled=True)
        assert included is not None and included.enabled is False

    @respx.mock
    async def test_disabled_config_never_calls_provider(self, db: AsyncIOMotorDatabase) -> None:
        cfg = await _seed_config(db, enabled=False)
        with pytest.raises(LLMDisabledError):
            await LLMService(db).make_llm_call(cfg, [{"role": "user", "content": "x"}])
        assert len(respx.calls) == 0


class TestKeyAndEndpointGuards:
    @respx.mock
    async def test_cleared_key_requires_reentry(self, db: AsyncIOMotorDatabase) -> None:
        cfg = await _seed_config(db)
        cfg.api_key_encrypted = ""
        with pytest.raises(LLMKeyMissingError):
            await LLMService(db).make_llm_call(cfg, [{"role": "user", "content": "x"}])
        assert len(respx.calls) == 0

    @respx.mock
    async def test_metadata_endpoint_is_blocked_at_call_time(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        from src.llm.service import LLMBlockedEndpointError

        cfg = await _seed_config(db)
        cfg.api_endpoint = "http://169.254.169.254/latest/meta-data"
        with pytest.raises(LLMBlockedEndpointError):
            await LLMService(db).make_llm_call(cfg, [{"role": "user", "content": "x"}])
        assert len(respx.calls) == 0


class TestGoogleKeyNeverLeaks:
    @respx.mock
    async def test_google_401_error_text_has_no_key(
        self, db: AsyncIOMotorDatabase, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        endpoint = "https://generativelanguage.googleapis.com/v1beta/models/m:generateContent"
        cfg = await _seed_config(
            db,
            request_format=RequestFormat.GOOGLE,
            api_endpoint=endpoint,
            api_key="AIzaSyLEAKLEAKLEAKLEAKLEAKLEAK123",
        )
        # Providers echo the key back in error bodies; it must still not escape.
        respx.post(endpoint).mock(
            return_value=httpx.Response(
                401,
                json={"error": {"message": "API key AIzaSyLEAKLEAKLEAKLEAKLEAKLEAK123 invalid"}},
            )
        )
        caplog.set_level(logging.DEBUG)
        with pytest.raises(LLMProviderError) as excinfo:
            await LLMService(db).make_llm_call(cfg, [{"role": "user", "content": "x"}])
        err = excinfo.value
        assert "AIzaSyLEAK" not in str(err)
        assert "AIzaSyLEAK" not in err.detail
        assert "AIzaSyLEAK" not in err.public_detail()
        assert "AIzaSyLEAK" not in caplog.text
        assert err.status_code == 401


class TestRetries:
    @respx.mock
    async def test_429_then_success_is_retried(self, db: AsyncIOMotorDatabase) -> None:
        cfg = await _seed_config(db)
        route = respx.post("https://api.openai.com/v1/chat/completions").mock(
            side_effect=[
                httpx.Response(429, headers={"retry-after": "0"}),
                httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}),
            ]
        )
        result = await LLMService(db).make_llm_call(cfg, [{"role": "user", "content": "x"}])
        assert result["choices"][0]["message"]["content"] == "ok"
        assert route.call_count == 2

    @respx.mock
    async def test_retries_are_bounded(
        self, db: AsyncIOMotorDatabase, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LLM_MAX_RETRIES", "2")
        cfg = await _seed_config(db)
        route = respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(503)
        )
        with pytest.raises(LLMProviderError):
            await LLMService(db).make_llm_call(cfg, [{"role": "user", "content": "x"}])
        assert route.call_count == 3

    @respx.mock
    async def test_400_is_not_retried(self, db: AsyncIOMotorDatabase) -> None:
        cfg = await _seed_config(db)
        route = respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(400, json={"error": "bad"})
        )
        with pytest.raises(LLMProviderError):
            await LLMService(db).make_llm_call(cfg, [{"role": "user", "content": "x"}])
        assert route.call_count == 1

    async def test_explicit_timeouts(self, db: AsyncIOMotorDatabase) -> None:
        cfg = await _seed_config(db)
        seen = {}

        class _Client:
            def __init__(self, *, timeout):
                seen["timeout"] = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, *args, **kwargs):
                return httpx.Response(
                    200,
                    json={"choices": [{"message": {"content": "ok"}}]},
                    request=httpx.Request("POST", "https://api.openai.com"),
                )

        import src.llm.service as service_mod

        original = service_mod.httpx.AsyncClient
        service_mod.httpx.AsyncClient = _Client  # type: ignore[misc]
        try:
            await LLMService(db).make_llm_call(cfg, [{"role": "user", "content": "x"}])
        finally:
            service_mod.httpx.AsyncClient = original  # type: ignore[misc]
        assert seen["timeout"].connect == 10.0
        assert seen["timeout"].read == 120.0


class TestAnthropicShape:
    @respx.mock
    async def test_system_prompt_goes_in_top_level_field(self, db: AsyncIOMotorDatabase) -> None:
        cfg = await _seed_config(
            db,
            request_format=RequestFormat.ANTHROPIC,
            api_endpoint="https://api.anthropic.com/v1/messages",
            model_name="claude-sonnet-5",
        )
        respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                200,
                json={
                    "content": [
                        {"type": "thinking", "thinking": ""},
                        {"type": "text", "text": "hello"},
                    ],
                    "stop_reason": "end_turn",
                },
            )
        )
        completion = await LLMService(db).complete(
            cfg,
            [
                {"role": "system", "content": "SYSTEM RULES"},
                {"role": "user", "content": "Hi"},
            ],
        )
        body = json.loads(respx.calls.last.request.content)
        assert body["system"] == "SYSTEM RULES"
        assert body["messages"] == [{"role": "user", "content": "Hi"}]
        assert respx.calls.last.request.headers["anthropic-version"] == "2023-06-01"
        # Thinking blocks are skipped
        assert completion.text == "hello"
        assert completion.truncated is False

    @pytest.mark.parametrize(
        ("model", "accepts"),
        [
            ("claude-haiku-4-5-20251001", True),
            ("claude-sonnet-4-5-20250929", True),
            ("claude-sonnet-5", False),
            ("claude-opus-5-5", False),
            ("claude-fable-5-1", False),
            ("claude-opus-4-7", False),
        ],
    )
    def test_sampling_parameter_support(self, model: str, accepts: bool) -> None:
        from src.llm.service import anthropic_accepts_sampling

        assert anthropic_accepts_sampling(model) is accepts

    @respx.mock
    async def test_max_tokens_stop_reason_marks_truncated(self, db: AsyncIOMotorDatabase) -> None:
        cfg = await _seed_config(
            db,
            request_format=RequestFormat.ANTHROPIC,
            api_endpoint="https://api.anthropic.com/v1/messages",
            model_name="claude-sonnet-5",
        )
        respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                200,
                json={"content": [{"type": "text", "text": "[{"}], "stop_reason": "max_tokens"},
            )
        )
        completion = await LLMService(db).complete(cfg, [{"role": "user", "content": "Hi"}])
        assert completion.truncated is True


class TestCohereV2Shape:
    @respx.mock
    async def test_v2_endpoint_uses_messages(self, db: AsyncIOMotorDatabase) -> None:
        cfg = await _seed_config(
            db,
            request_format=RequestFormat.COHERE,
            api_endpoint="https://api.cohere.com/v2/chat",
        )
        respx.post("https://api.cohere.com/v2/chat").mock(
            return_value=httpx.Response(
                200,
                json={
                    "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
                    "finish_reason": "COMPLETE",
                },
            )
        )
        completion = await LLMService(db).complete(
            cfg,
            [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}],
        )
        body = json.loads(respx.calls.last.request.content)
        assert body["messages"] == [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "U"},
        ]
        assert completion.text == "hi"

    @respx.mock
    async def test_v1_system_goes_to_preamble(self, db: AsyncIOMotorDatabase) -> None:
        cfg = await _seed_config(
            db,
            request_format=RequestFormat.COHERE,
            api_endpoint="https://api.cohere.com/v1/chat",
        )
        respx.post("https://api.cohere.com/v1/chat").mock(
            return_value=httpx.Response(200, json={"text": "ok"})
        )
        await LLMService(db).make_llm_call(
            cfg, [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]
        )
        body = json.loads(respx.calls.last.request.content)
        assert body["preamble"] == "S"
        assert body["message"] == "U"
        assert body["chat_history"] == []
