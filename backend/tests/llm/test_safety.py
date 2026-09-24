"""Tests for `src.llm.safety` (LLM-02 secret redaction, LLM-05 endpoint
validation, LLM-10 content logging)."""

from __future__ import annotations

import logging

import pytest

from src.llm.safety import (
    LLMEndpointError,
    LLMProviderError,
    log_content_debug,
    redact_secrets,
    validate_llm_endpoint,
    validate_llm_endpoint_static,
)


class TestRedactSecrets:
    @pytest.mark.parametrize(
        "text",
        [
            "Client error '400' for url 'https://g.example/v1/m:gen?key=AIzaSyABCDEFGHIJKLMNOPQRSTU'",
            "Authorization: Bearer sk-proj-abcdefghijklmnop",
            '{"x-api-key": "sk-ant-api03-abcdefghijklmn"}',
            "x-goog-api-key=AIzaSyABCDEFGHIJKLMNOPQRSTU",
            "token AIzaSyABCDEFGHIJKLMNOPQRSTU leaked",
        ],
    )
    def test_known_shapes_removed(self, text: str) -> None:
        out = redact_secrets(text)
        assert "AIzaSyABCDEFGHIJKLMNOPQRSTU" not in out
        assert "sk-proj-abcdefghijklmnop" not in out
        assert "sk-ant-api03-abcdefghijklmn" not in out
        assert "[REDACTED]" in out

    def test_explicit_secret_values_removed(self) -> None:
        out = redact_secrets("azure says: bad key zz-custom-99", ["zz-custom-99"])
        assert "zz-custom-99" not in out

    def test_plain_text_untouched(self) -> None:
        assert redact_secrets("Rate limited (HTTP 429)") == "Rate limited (HTTP 429)"

    def test_provider_error_str_is_generic(self) -> None:
        err = LLMProviderError("google", 401, detail="key=AIzaSECRET")
        assert str(err) == "google request failed (HTTP 401)"
        assert "AIza" not in err.public_detail()
        assert err.reference in err.public_detail()


class TestEndpointValidation:
    @pytest.mark.parametrize(
        "url",
        [
            "https://api.openai.com/v1/chat/completions",
            "https://api.anthropic.com/v1/messages",
            "https://myresource.openai.azure.com/openai/deployments/x/chat/completions",
        ],
    )
    def test_public_https_accepted(self, url: str) -> None:
        validate_llm_endpoint_static(url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://api.openai.com/v1/chat/completions",
            "ftp://api.openai.com/",
            "https://user:pass@api.example.com/",
            "https://169.254.169.254/latest",
            "https://[fe80::1]/x",
            "https://10.1.2.3/v1",
            "https://192.168.0.2/v1",
            "https://100.64.0.1/v1",
            "https://[::ffff:10.0.0.1]/v1",
            "https://localhost/v1",
            "https://metadata.google.internal/x",
            "https://api.example.com/v1?key=abc",
            "not a url",
        ],
    )
    def test_unsafe_rejected(self, url: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LLM_ALLOW_PRIVATE_ENDPOINTS", raising=False)
        with pytest.raises(LLMEndpointError):
            validate_llm_endpoint_static(url)

    def test_opt_in_allows_private_and_local_http(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_ALLOW_PRIVATE_ENDPOINTS", "true")
        validate_llm_endpoint_static("http://localhost:11434/v1/chat/completions")
        validate_llm_endpoint_static("https://10.1.2.3/v1")
        with pytest.raises(LLMEndpointError):
            validate_llm_endpoint_static("https://169.254.169.254/x")
        with pytest.raises(LLMEndpointError, match="https"):
            validate_llm_endpoint_static("http://10.1.2.3/v1")

    async def test_dns_to_private_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import src.llm.safety as safety

        async def _resolve(host: str) -> list[str]:
            return ["93.184.216.34", "10.0.0.8"]

        monkeypatch.setattr(safety, "_resolve", _resolve)
        with pytest.raises(LLMEndpointError, match="private"):
            await validate_llm_endpoint("https://llm.example.com/v1")

    async def test_dns_public_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import src.llm.safety as safety

        async def _resolve(host: str) -> list[str]:
            return ["93.184.216.34"]

        monkeypatch.setattr(safety, "_resolve", _resolve)
        await validate_llm_endpoint("https://llm.example.com/v1")


class TestContentLogging:
    def test_debug_only_and_truncated(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("test.llm.content")
        caplog.set_level(logging.INFO, logger="test.llm.content")
        log_content_debug(logger, "doc", "Alice Smith")
        assert "Alice" not in caplog.text

        caplog.set_level(logging.DEBUG, logger="test.llm.content")
        log_content_debug(logger, "doc", "A" * 500)
        assert "A" * 81 not in caplog.text
        assert "(500 chars)" in caplog.text

    def test_never_in_production(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ENVIRONMENT", "production")
        logger = logging.getLogger("test.llm.content.prod")
        caplog.set_level(logging.DEBUG, logger="test.llm.content.prod")
        log_content_debug(logger, "doc", "Alice Smith")
        assert "Alice" not in caplog.text
