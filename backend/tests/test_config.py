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

import pytest


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
        monkeypatch.setenv("JWT_SECRET", "x" * 32)
        cfg = Config()
        assert cfg.MONGODB_URI == "mongodb://mongodb:27017/blackbar"

    def test_explicit_env_var_used(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.setenv("MONGODB_URI", "mongodb://custom:27017/foo")
        monkeypatch.setenv("JWT_SECRET", "x" * 32)
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

    def test_short_secret_raises(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.setenv("JWT_SECRET", "tooshort")
        with pytest.raises(ValueError, match="at least 32 characters"):
            Config()

    def test_valid_secret_accepted(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.setenv("JWT_SECRET", "x" * 32)
        cfg = Config()
        assert cfg.JWT_SECRET == "x" * 32

    def test_environment_defaults_to_development(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.setenv("JWT_SECRET", "x" * 32)
        cfg = Config()
        assert cfg.ENVIRONMENT == "development"


# ---------------------------------------------------------------------------
# OPENAI_API_KEY (optional)
# ---------------------------------------------------------------------------


class TestOpenAIKey:
    def test_unset_is_none(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("JWT_SECRET", "x" * 32)
        cfg = Config()
        assert cfg.OPENAI_API_KEY is None

    def test_set_passes_through(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("JWT_SECRET", "x" * 32)
        cfg = Config()
        assert cfg.OPENAI_API_KEY == "sk-test"


# ---------------------------------------------------------------------------
# CORS origins
# ---------------------------------------------------------------------------


class TestAllowedOrigins:
    def test_env_var_split_on_comma(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.setenv("ALLOWED_ORIGINS", "https://a.example,https://b.example")
        monkeypatch.setenv("JWT_SECRET", "x" * 32)
        cfg = Config()
        assert cfg.ALLOWED_ORIGINS == [
            "https://a.example",
            "https://b.example",
        ]

    def test_single_origin_via_env(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.setenv("ALLOWED_ORIGINS", "https://only.example")
        monkeypatch.setenv("JWT_SECRET", "x" * 32)
        cfg = Config()
        assert cfg.ALLOWED_ORIGINS == ["https://only.example"]

    def test_unset_uses_localhost_default(self, monkeypatch: pytest.MonkeyPatch):
        Config = _reload_config_class()
        monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
        monkeypatch.setenv("JWT_SECRET", "x" * 32)
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
        monkeypatch.setenv("JWT_SECRET", "x" * 32)
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
        monkeypatch.setenv("JWT_SECRET", "x" * 32)
        cfg = Config()
        assert cfg.ALGORITHM == "HS256"

    def test_access_token_expiration_default(self, monkeypatch: pytest.MonkeyPatch):
        """No JWT_EXPIRATION env var -> 60 minutes."""
        Config = _reload_config_class()
        monkeypatch.delenv("JWT_EXPIRATION", raising=False)
        monkeypatch.setenv("JWT_SECRET", "x" * 32)
        cfg = Config()
        assert cfg.ACCESS_TOKEN_EXPIRE_MINUTES == 60

    def test_access_token_expiration_reads_env_var(self, monkeypatch: pytest.MonkeyPatch):
        """Phase 4 Batch 4.4 (audit B5): JWT_EXPIRATION integer minutes
        is honoured by Config."""
        Config = _reload_config_class()
        monkeypatch.setenv("JWT_EXPIRATION", "120")
        monkeypatch.setenv("JWT_SECRET", "x" * 32)
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
        monkeypatch.setenv("JWT_SECRET", "x" * 32)
        with pytest.warns(RuntimeWarning, match="JWT_EXPIRATION"):
            cfg = Config()
        assert cfg.ACCESS_TOKEN_EXPIRE_MINUTES == 60

    def test_access_token_expiration_empty_string_falls_back(self, monkeypatch: pytest.MonkeyPatch):
        """An empty JWT_EXPIRATION value is treated as unset -> 60."""
        Config = _reload_config_class()
        monkeypatch.setenv("JWT_EXPIRATION", "")
        monkeypatch.setenv("JWT_SECRET", "x" * 32)
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
