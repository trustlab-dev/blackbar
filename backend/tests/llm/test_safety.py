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
        validate_llm_endpoint_static("http://10.1.2.3/v1")
        with pytest.raises(LLMEndpointError):
            validate_llm_endpoint_static("https://169.254.169.254/x")
        # https stays mandatory for public hosts.
        with pytest.raises(LLMEndpointError, match="https"):
            validate_llm_endpoint_static("http://api.openai.com/v1/chat/completions")

    LOCAL_HTTP = [
        "http://ollama:11434/v1/chat/completions",
        "http://10.0.0.5:8000/v1/chat/completions",
        "http://host.docker.internal:11434/v1/chat/completions",
        "http://172.17.0.1:11434/api/chat",
        "http://192.168.1.20:8080/v1",
        "http://[fd12:3456::5]:8000/v1",
    ]

    @pytest.mark.parametrize("url", LOCAL_HTTP)
    def test_local_http_model_servers_need_the_opt_in(
        self, url: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """I5: a model server on the compose network, the Docker host or a
        private range works over http once LLM_ALLOW_PRIVATE_ENDPOINTS=true."""
        monkeypatch.delenv("LLM_ALLOW_PRIVATE_ENDPOINTS", raising=False)
        with pytest.raises(LLMEndpointError):
            validate_llm_endpoint_static(url)
        monkeypatch.setenv("LLM_ALLOW_PRIVATE_ENDPOINTS", "true")
        validate_llm_endpoint_static(url)

    @pytest.mark.parametrize("url", LOCAL_HTTP[:3])
    async def test_local_http_passes_full_validation_with_opt_in(
        self, url: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.llm.safety as safety

        async def _resolve(host: str) -> list[str]:
            return ["172.18.0.4"]

        monkeypatch.setattr(safety, "_resolve", _resolve)
        monkeypatch.setenv("LLM_ALLOW_PRIVATE_ENDPOINTS", "true")
        await validate_llm_endpoint(url)
        monkeypatch.delenv("LLM_ALLOW_PRIVATE_ENDPOINTS")
        with pytest.raises(LLMEndpointError):
            await validate_llm_endpoint(url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://169.254.169.254/latest/meta-data",
            "https://169.254.169.254/latest/meta-data",
            "http://[fd00:ec2::254]/latest",
            "http://100.100.100.200/latest",
            "http://[fe80::1]/x",
            "http://metadata.google.internal/x",
            "http://metadata/x",
            "http://[::ffff:169.254.169.254]/x",
        ],
    )
    @pytest.mark.parametrize("opt_in", [False, True])
    def test_metadata_and_link_local_always_refused(
        self, url: str, opt_in: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        if opt_in:
            monkeypatch.setenv("LLM_ALLOW_PRIVATE_ENDPOINTS", "true")
        else:
            monkeypatch.delenv("LLM_ALLOW_PRIVATE_ENDPOINTS", raising=False)
        with pytest.raises(LLMEndpointError):
            validate_llm_endpoint_static(url)

    async def test_http_name_resolving_to_public_address_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.llm.safety as safety

        async def _resolve(host: str) -> list[str]:
            return ["93.184.216.34"]

        monkeypatch.setattr(safety, "_resolve", _resolve)
        monkeypatch.setenv("LLM_ALLOW_PRIVATE_ENDPOINTS", "true")
        with pytest.raises(LLMEndpointError, match="public"):
            await validate_llm_endpoint("http://ollama:11434/v1")

    async def test_name_resolving_to_link_local_is_refused_with_opt_in(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.llm.safety as safety

        async def _resolve(host: str) -> list[str]:
            return ["169.254.169.254"]

        monkeypatch.setattr(safety, "_resolve", _resolve)
        monkeypatch.setenv("LLM_ALLOW_PRIVATE_ENDPOINTS", "true")
        with pytest.raises(LLMEndpointError, match="link-local"):
            await validate_llm_endpoint("http://ollama:11434/v1")

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
