"""Tests for `src.llm.models` Pydantic V2 schemas.

Phase 2.6. Pins validation behavior, enum membership, and the shape of the
LLM configuration models.

Models covered:
    - RequestFormat enum
    - LLMSettings (temperature, max_tokens, top_p bounds)
    - LLMConfigBase / LLMConfigCreate / LLMConfigUpdate / LLMConfig / LLMConfigResponse

Reality pins:
- `LLMSettings.temperature` is bounded ge=0.0, le=2.0 (Pydantic V2 numeric bounds).
- `LLMSettings.max_tokens` is bounded gt=0.
- `LLMSettings.top_p` is bounded ge=0.0, le=1.0.
- `LLMConfigBase.enabled` defaults to True, `default_settings` to LLMSettings().
- `LLMConfigCreate` requires `api_key` plaintext field.
- `LLMConfigUpdate` is all-optional and accepts an optional `api_key` for re-encryption.
- `LLMConfig` requires `api_key_encrypted` (storage) plus timestamps + created_by.
- `LLMConfigResponse` is identical to LLMConfigBase plus id + audit metadata; it
  intentionally *excludes* the encrypted key from API responses.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from src.llm.models import (
    LLMConfig,
    LLMConfigBase,
    LLMConfigCreate,
    LLMConfigResponse,
    LLMConfigUpdate,
    LLMSettings,
    RequestFormat,
)

# ---------------------------------------------------------------------------
# RequestFormat enum
# ---------------------------------------------------------------------------


class TestRequestFormat:
    def test_supported_values(self) -> None:
        assert RequestFormat.OPENAI.value == "openai"
        assert RequestFormat.ANTHROPIC.value == "anthropic"
        assert RequestFormat.GOOGLE.value == "google"
        assert RequestFormat.COHERE.value == "cohere"
        assert RequestFormat.CUSTOM.value == "custom"

    def test_membership_set(self) -> None:
        assert {f.value for f in RequestFormat} == {
            "openai",
            "anthropic",
            "google",
            "cohere",
            "custom",
        }


# ---------------------------------------------------------------------------
# LLMSettings
# ---------------------------------------------------------------------------


class TestLLMSettings:
    def test_defaults(self) -> None:
        s = LLMSettings()
        assert s.temperature == 0.7
        assert s.max_tokens == 4000
        assert s.top_p == 1.0

    @pytest.mark.parametrize("temp", [-0.01, 2.01, 3.0])
    def test_temperature_out_of_bounds_rejected(self, temp: float) -> None:
        with pytest.raises(ValidationError):
            LLMSettings(temperature=temp)

    @pytest.mark.parametrize("temp", [0.0, 0.5, 1.5, 2.0])
    def test_temperature_in_bounds_accepted(self, temp: float) -> None:
        assert LLMSettings(temperature=temp).temperature == temp

    @pytest.mark.parametrize("tokens", [0, -1, -100])
    def test_max_tokens_must_be_positive(self, tokens: int) -> None:
        with pytest.raises(ValidationError):
            LLMSettings(max_tokens=tokens)

    @pytest.mark.parametrize("top_p", [-0.01, 1.01, 2.0])
    def test_top_p_out_of_bounds_rejected(self, top_p: float) -> None:
        with pytest.raises(ValidationError):
            LLMSettings(top_p=top_p)


# ---------------------------------------------------------------------------
# LLMConfigBase / LLMConfigCreate
# ---------------------------------------------------------------------------


class TestLLMConfigBase:
    def test_minimum_required_fields(self) -> None:
        cfg = LLMConfigBase(
            name="OpenAI Prod",
            api_endpoint="https://api.openai.com/v1/chat/completions",
            model_name="gpt-4o-mini",
            request_format=RequestFormat.OPENAI,
        )
        assert cfg.enabled is True
        assert cfg.default_settings.temperature == 0.7
        assert cfg.headers is None
        assert cfg.notes is None

    def test_missing_required_field_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc:
            LLMConfigBase(  # type: ignore[call-arg]
                name="x",
                api_endpoint="https://api.example.com",
                model_name="m",
                # request_format intentionally omitted
            )
        assert "request_format" in str(exc.value)

    def test_invalid_request_format_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LLMConfigBase(
                name="x",
                api_endpoint="https://api.example.com",
                model_name="m",
                request_format="not-a-format",  # type: ignore[arg-type]
            )


class TestLLMConfigCreate:
    def test_requires_api_key(self) -> None:
        with pytest.raises(ValidationError) as exc:
            LLMConfigCreate(  # type: ignore[call-arg]
                name="OpenAI",
                api_endpoint="https://api.openai.com/v1/chat/completions",
                model_name="gpt-4o",
                request_format=RequestFormat.OPENAI,
            )
        assert "api_key" in str(exc.value)

    def test_accepts_full_payload(self) -> None:
        cfg = LLMConfigCreate(
            name="Anthropic",
            api_endpoint="https://api.anthropic.com/v1/messages",
            model_name="claude-3-5-sonnet-20241022",
            request_format=RequestFormat.ANTHROPIC,
            api_key="sk-ant-1234",
            headers={"X-Custom": "value"},
            notes="Production Anthropic key",
            default_settings=LLMSettings(temperature=0.2, max_tokens=8000),
        )
        assert cfg.api_key == "sk-ant-1234"
        assert cfg.headers == {"X-Custom": "value"}
        assert cfg.default_settings.temperature == 0.2


# ---------------------------------------------------------------------------
# LLMConfigUpdate (all-optional partial update)
# ---------------------------------------------------------------------------


class TestLLMConfigUpdate:
    def test_all_fields_optional(self) -> None:
        upd = LLMConfigUpdate()
        # No required fields — every attribute should be None
        assert upd.name is None
        assert upd.enabled is None
        assert upd.api_endpoint is None
        assert upd.model_name is None
        assert upd.request_format is None
        assert upd.default_settings is None
        assert upd.headers is None
        assert upd.notes is None
        assert upd.api_key is None

    def test_partial_update(self) -> None:
        upd = LLMConfigUpdate(enabled=False, notes="Disabled for billing")
        assert upd.enabled is False
        assert upd.notes == "Disabled for billing"
        assert upd.name is None

    def test_api_key_field_carries_through(self) -> None:
        """The repository.update() path strips `api_key` and re-encrypts it."""
        upd = LLMConfigUpdate(api_key="sk-new-rotated-key")
        assert upd.api_key == "sk-new-rotated-key"

    def test_request_format_enum_validated(self) -> None:
        with pytest.raises(ValidationError):
            LLMConfigUpdate(request_format="invalid")  # type: ignore[arg-type]

    def test_settings_nested_validated(self) -> None:
        """Nested LLMSettings validation propagates."""
        with pytest.raises(ValidationError):
            LLMConfigUpdate(default_settings=LLMSettings(temperature=3.0))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# LLMConfig (storage shape) + LLMConfigResponse (no encrypted key)
# ---------------------------------------------------------------------------


class TestLLMConfigPersistence:
    def _base_kwargs(self) -> dict:  # type: ignore[type-arg]
        now = datetime.utcnow()
        return {
            "name": "OpenAI",
            "api_endpoint": "https://api.openai.com/v1/chat/completions",
            "model_name": "gpt-4o",
            "request_format": RequestFormat.OPENAI,
            "id": "config-1",
            "created_at": now,
            "updated_at": now,
            "created_by": "user-1",
        }

    def test_llm_config_requires_encrypted_key(self) -> None:
        with pytest.raises(ValidationError) as exc:
            LLMConfig(**self._base_kwargs())  # type: ignore[arg-type]
        assert "api_key_encrypted" in str(exc.value)

    def test_llm_config_roundtrip(self) -> None:
        cfg = LLMConfig(**self._base_kwargs(), api_key_encrypted="gAAAA...ciphertext")
        assert cfg.api_key_encrypted == "gAAAA...ciphertext"
        assert cfg.created_by == "user-1"

    def test_response_model_excludes_encrypted_key(self) -> None:
        """LLMConfigResponse must not have an `api_key_encrypted` field at all
        (security contract: never leak encrypted-key blob over the wire)."""
        assert "api_key_encrypted" not in LLMConfigResponse.model_fields
        # And — the field IS present on the storage model
        assert "api_key_encrypted" in LLMConfig.model_fields

    def test_response_model_constructable_without_key(self) -> None:
        resp = LLMConfigResponse(**self._base_kwargs())
        assert resp.id == "config-1"
        # Should not accept api_key_encrypted as it's not a declared field
        # (Pydantic V2 ignores extras silently by default unless extra='forbid')
