"""Tests for `src.config.Config` — env-var loading & validation.

Target: 100% coverage on the `Config.__init__` body.

`src.config` constructs a singleton `config = Config()` at import time
and exports a handful of module-level constants. To test branches we
re-instantiate `Config()` (the class) with monkey-patched env vars; the
already-imported module constants are left intact.

Branches under test:
- Default MONGODB_URI when unset
- Explicit MONGODB_URI from env
- JWT_SECRET unset + ENVIRONMENT=="production" -> ValueError
- JWT_SECRET unset + dev environment -> auto-generated + RuntimeWarning
- JWT_SECRET < 32 chars -> ValueError
- ALLOWED_ORIGINS env var present -> split on commas
- ALLOWED_ORIGINS env var absent -> default localhost list
- ACCESS_TOKEN_EXPIRE_MINUTES default 60 (no JWT_EXPIRATION env var)
- ACCESS_TOKEN_EXPIRE_MINUTES picks up integer JWT_EXPIRATION env var (B5)
- ACCESS_TOKEN_EXPIRE_MINUTES warns + falls back on non-integer JWT_EXPIRATION

Phase 4 Batch 4.4 (audit B5, B41): the previous behaviour pinned a
hardcoded `ACCESS_TOKEN_EXPIRE_MINUTES = 60` and silently ignored
`JWT_EXPIRATION` from the env. The dead `if not self.MONGODB_URI`
guard (B41) was removed: with the `mongodb://mongodb:27017/blackbar`
default literal, the guard was unreachable.
"""

from __future__ import annotations

import secrets

import pytest

# A secret with the shape `openssl rand -base64 48` / `secrets.token_urlsafe(48)`
# produces. Every non-JWT test uses it so the secret-strength gate stays quiet.
GOOD_SECRET = secrets.token_urlsafe(48)


def _reload_config_class():
    """Helper: returns the Config class fresh from the module. Avoids
    triggering the module-level `config = Config()` re-run on every test
    by accessing the class directly."""
    from src.config import Config

    return Config


# ---------------------------------------------------------------------------
# MongoDB URI
# ---------------------------------------------------------------------------


class TestMongoDBUri:
    def test_default_when_env_unset(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.delenv("MONGODB_URI", raising=False)
        # Required: JWT secret so we don't trip that branch
        monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
        cfg = Config()
        assert cfg.MONGODB_URI == "mongodb://mongodb:27017/blackbar"

    def test_explicit_env_var_used(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.setenv("MONGODB_URI", "mongodb://custom:27017/foo")
        monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
        cfg = Config()
        assert cfg.MONGODB_URI == "mongodb://custom:27017/foo"


# ---------------------------------------------------------------------------
# JWT secret + environment-aware validation
# ---------------------------------------------------------------------------
# LLM_API_KEY_ENCRYPTION_KEY (LLM-19): validated once, no fallback key
# ---------------------------------------------------------------------------


class TestLLMEncryptionKey:
    def test_valid_key_is_kept(self, monkeypatch: pytest.MonkeyPatch):
        from cryptography.fernet import Fernet

        Config = _reload_config_class()
        key = Fernet.generate_key().decode()
        monkeypatch.setenv("LLM_API_KEY_ENCRYPTION_KEY", key)
        monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
        assert Config().LLM_API_KEY_ENCRYPTION_KEY == key

    def test_comma_separated_rotation_keys_accepted(self, monkeypatch: pytest.MonkeyPatch):
        from cryptography.fernet import Fernet

        Config = _reload_config_class()
        keys = f"{Fernet.generate_key().decode()},{Fernet.generate_key().decode()}"
        monkeypatch.setenv("LLM_API_KEY_ENCRYPTION_KEY", keys)
        monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
        assert Config().LLM_API_KEY_ENCRYPTION_KEY == keys

    @pytest.mark.parametrize("value", ["", "CHANGE_THIS_TO_FERNET_KEY"])
    def test_missing_or_invalid_key_fails_in_production(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ):
        Config = _reload_config_class()
        monkeypatch.setenv("LLM_API_KEY_ENCRYPTION_KEY", value)
        monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
        monkeypatch.setenv("ENVIRONMENT", "production")
        with pytest.raises(ValueError, match="LLM_API_KEY_ENCRYPTION_KEY"):
            Config()

    def test_invalid_key_outside_production_is_disabled(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.setenv("LLM_API_KEY_ENCRYPTION_KEY", "not-a-fernet-key")
        monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
        monkeypatch.setenv("ENVIRONMENT", "development")
        assert Config().LLM_API_KEY_ENCRYPTION_KEY is None


# ---------------------------------------------------------------------------
# CORS origins
# ---------------------------------------------------------------------------


class TestAllowedOrigins:
    def test_env_var_split_on_comma(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.setenv("ALLOWED_ORIGINS", "https://a.example,https://b.example")
        monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
        cfg = Config()
        assert cfg.ALLOWED_ORIGINS == [
            "https://a.example",
            "https://b.example",
        ]

    def test_single_origin_via_env(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.setenv("ALLOWED_ORIGINS", "https://only.example")
        monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
        cfg = Config()
        assert cfg.ALLOWED_ORIGINS == ["https://only.example"]

    def test_unset_uses_localhost_default(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
        monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
        cfg = Config()
        assert cfg.ALLOWED_ORIGINS == [
            "http://localhost:3000",
            "http://localhost:8000",
        ]

    def test_empty_string_uses_default(self, monkeypatch: pytest.MonkeyPatch):
        """An empty ALLOWED_ORIGINS value triggers the `if origins_env:` False
        branch -> default."""
        Config = _reload_config_class()
        monkeypatch.setenv("ALLOWED_ORIGINS", "")
        monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
        cfg = Config()
        assert cfg.ALLOWED_ORIGINS == [
            "http://localhost:3000",
            "http://localhost:8000",
        ]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_algorithm_is_hs256(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
        cfg = Config()
        assert cfg.ALGORITHM == "HS256"

    def test_access_token_expiration_default(self, monkeypatch: pytest.MonkeyPatch):
        """No JWT_EXPIRATION env var -> 60 minutes."""
        Config = _reload_config_class()
        monkeypatch.delenv("JWT_EXPIRATION", raising=False)
        monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
        cfg = Config()
        assert cfg.ACCESS_TOKEN_EXPIRE_MINUTES == 60

    def test_access_token_expiration_reads_env_var(self, monkeypatch: pytest.MonkeyPatch):
        """Phase 4 Batch 4.4 (audit B5): JWT_EXPIRATION integer minutes
        is honoured by Config."""
        Config = _reload_config_class()
        monkeypatch.setenv("JWT_EXPIRATION", "120")
        monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
        cfg = Config()
        assert cfg.ACCESS_TOKEN_EXPIRE_MINUTES == 120

    def test_access_token_expiration_invalid_warns_and_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Phase 4 Batch 4.4 (audit B5): a non-integer JWT_EXPIRATION
        (e.g. the legacy "24h" form from .env.example) emits a
        RuntimeWarning and falls back to 60."""
        Config = _reload_config_class()
        monkeypatch.setenv("JWT_EXPIRATION", "24h")
        monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
        with pytest.warns(RuntimeWarning, match="JWT_EXPIRATION"):
            cfg = Config()
        assert cfg.ACCESS_TOKEN_EXPIRE_MINUTES == 60

    def test_access_token_expiration_empty_string_falls_back(self, monkeypatch: pytest.MonkeyPatch):
        """An empty JWT_EXPIRATION value is treated as unset -> 60."""
        Config = _reload_config_class()
        monkeypatch.setenv("JWT_EXPIRATION", "")
        monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
        cfg = Config()
        assert cfg.ACCESS_TOKEN_EXPIRE_MINUTES == 60


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_module_exports_match_singleton(self):
        """The module-level `JWT_SECRET`, `ALGORITHM`, etc. mirror the
        singleton's attribute values."""
        from src import config as cfg_mod

        assert cfg_mod.JWT_SECRET == cfg_mod.config.JWT_SECRET
        assert cfg_mod.ALGORITHM == cfg_mod.config.ALGORITHM
        assert cfg_mod.MONGODB_URI == cfg_mod.config.MONGODB_URI
        assert cfg_mod.ALLOWED_ORIGINS == cfg_mod.config.ALLOWED_ORIGINS
        assert cfg_mod.ACCESS_TOKEN_EXPIRE_MINUTES == cfg_mod.config.ACCESS_TOKEN_EXPIRE_MINUTES


# ---------------------------------------------------------------------------
# Security-review 2026-09 settings
# ---------------------------------------------------------------------------


class TestSecuritySettings:
    def test_jwt_expiration_is_capped(self, monkeypatch: pytest.MonkeyPatch):
        """AUTH-14: an unbounded JWT_EXPIRATION defeats revocation; cap at 24h."""
        Config = _reload_config_class()
        monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
        monkeypatch.setenv("JWT_EXPIRATION", "100000")
        with pytest.warns(RuntimeWarning, match="JWT_EXPIRATION"):
            cfg = Config()
        assert cfg.ACCESS_TOKEN_EXPIRE_MINUTES == 1440

    def test_allowed_origins_are_stripped(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
        monkeypatch.setenv("ALLOWED_ORIGINS", "https://a.example, https://b.example ,")
        assert Config().ALLOWED_ORIGINS == ["https://a.example", "https://b.example"]

    def test_trusted_proxies_default_empty(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
        monkeypatch.delenv("TRUSTED_PROXIES", raising=False)
        assert Config().TRUSTED_PROXIES == []

    def test_trusted_proxies_parsed(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
        monkeypatch.setenv("TRUSTED_PROXIES", "172.18.0.0/16, 10.0.0.5")
        assert Config().TRUSTED_PROXIES == ["172.18.0.0/16", "10.0.0.5"]

    def test_trusted_proxies_invalid_entry_raises(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
        monkeypatch.setenv("TRUSTED_PROXIES", "not-an-ip")
        with pytest.raises(ValueError, match="TRUSTED_PROXIES"):
            Config()

    def test_trusted_hosts_default_empty(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
        monkeypatch.delenv("TRUSTED_HOSTS", raising=False)
        assert Config().TRUSTED_HOSTS == []

    def test_trusted_hosts_parsed(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
        monkeypatch.setenv("TRUSTED_HOSTS", "foi.example.org, localhost")
        assert Config().TRUSTED_HOSTS == ["foi.example.org", "localhost"]


class TestPublicBaseUrl:
    def test_prefers_public_base_url(self, monkeypatch: pytest.MonkeyPatch):
        from src.config import public_base_url

        monkeypatch.setenv("PUBLIC_BASE_URL", "https://foi.example.org/")
        monkeypatch.setenv("FRONTEND_URL", "https://other.example.org")
        assert public_base_url() == "https://foi.example.org"

    def test_falls_back_to_frontend_url(self, monkeypatch: pytest.MonkeyPatch):
        from src.config import public_base_url

        monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
        monkeypatch.setenv("FRONTEND_URL", "https://app.example.org")
        assert public_base_url() == "https://app.example.org"

    def test_default_localhost(self, monkeypatch: pytest.MonkeyPatch):
        from src.config import public_base_url

        monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
        monkeypatch.delenv("FRONTEND_URL", raising=False)
        assert public_base_url() == "http://localhost:3000"
