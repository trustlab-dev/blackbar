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


class TestJWTSecret:
    def test_production_requires_jwt_secret(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.delenv("JWT_SECRET", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "production")
        with pytest.raises(ValueError, match="JWT_SECRET"):
            Config()

    def test_development_generates_temp_secret_and_warns(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.delenv("JWT_SECRET", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "development")
        with pytest.warns(RuntimeWarning, match="auto-generated JWT secret"):
            cfg = Config()
        assert cfg.JWT_SECRET
        assert len(cfg.JWT_SECRET) >= 32

    def test_short_secret_raises_in_production(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("JWT_SECRET", "tooshort")
        with pytest.raises(ValueError, match="32 bytes"):
            Config()

    def test_short_secret_replaced_with_ephemeral_in_development(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        Config = _reload_config_class()
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("JWT_SECRET", "tooshort")
        with pytest.warns(RuntimeWarning, match="JWT_SECRET"):
            cfg = Config()
        assert cfg.JWT_SECRET != "tooshort"
        assert len(cfg.JWT_SECRET) >= 32

    def test_valid_secret_accepted(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
        cfg = Config()
        assert cfg.JWT_SECRET == GOOD_SECRET

    def test_valid_secret_accepted_in_production(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
        assert Config().JWT_SECRET == GOOD_SECRET

    def test_hex_secret_accepted_in_production(self, monkeypatch: pytest.MonkeyPatch):
        """`openssl rand -hex 32` has only 16 distinct symbols but 256 bits."""
        Config = _reload_config_class()
        hex_secret = secrets.token_hex(32)
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("JWT_SECRET", hex_secret)
        assert Config().JWT_SECRET == hex_secret

    @pytest.mark.parametrize(
        "placeholder",
        [
            # The literal value shipped in .env.example (AUTH-02).
            "CHANGE_THIS_TO_RANDOM_32_CHAR_STRING",
            "changeme-changeme-changeme-changeme-1234",
            "my-example-jwt-key-with-enough-length-0123456789",
            "SuperSecretSigningKeyForBlackBar0123456789",
            "Password-For-Tokens-abcdefghijklmnopqrstuvwxyz",
        ],
    )
    def test_placeholder_rejected_in_production(
        self, monkeypatch: pytest.MonkeyPatch, placeholder: str
    ):
        Config = _reload_config_class()
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("JWT_SECRET", placeholder)
        with pytest.raises(ValueError, match="JWT_SECRET"):
            Config()

    def test_placeholder_replaced_with_ephemeral_in_development(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        Config = _reload_config_class()
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("JWT_SECRET", "CHANGE_THIS_TO_RANDOM_32_CHAR_STRING")
        with pytest.warns(RuntimeWarning, match="JWT_SECRET"):
            cfg = Config()
        assert cfg.JWT_SECRET != "CHANGE_THIS_TO_RANDOM_32_CHAR_STRING"
        assert len(cfg.JWT_SECRET.encode()) >= 32

    def test_low_variety_secret_rejected_in_production(self, monkeypatch: pytest.MonkeyPatch):
        """Long enough, but 1 distinct character: no real entropy."""
        Config = _reload_config_class()
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("JWT_SECRET", "x" * 64)
        with pytest.raises(ValueError, match="JWT_SECRET"):
            Config()

    def test_prod_alias_is_treated_as_production(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.setenv("ENVIRONMENT", "Production ")
        monkeypatch.setenv("JWT_SECRET", "CHANGE_THIS_TO_RANDOM_32_CHAR_STRING")
        with pytest.raises(ValueError, match="JWT_SECRET"):
            Config()

    def test_environment_defaults_to_development(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
        cfg = Config()
        assert cfg.ENVIRONMENT == "development"


# ---------------------------------------------------------------------------
# OPENAI_API_KEY (optional)
# ---------------------------------------------------------------------------


class TestOpenAIKey:
    def test_unset_is_none(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
        cfg = Config()
        assert cfg.OPENAI_API_KEY is None

    def test_set_passes_through(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
        cfg = Config()
        assert cfg.OPENAI_API_KEY == "sk-test"


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
        assert cfg_mod.OPENAI_API_KEY == cfg_mod.config.OPENAI_API_KEY
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
