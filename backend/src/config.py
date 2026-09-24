"""
Configuration management for BlackBar
Validates required environment variables and provides secure defaults
"""

import ipaddress
import logging
import os
import secrets
import string
import warnings

logger = logging.getLogger(__name__)

# Substrings that mark a JWT secret as a documentation placeholder or a
# human-chosen word rather than random bytes (AUTH-02). `.env.example` ships
# `CHANGE_THIS_TO_RANDOM_32_CHAR_STRING`, which is 36 characters long and so
# passed the old length-only check.
_JWT_SECRET_PLACEHOLDER_MARKERS = (
    "change_this",
    "changethis",
    "change-this",
    "changeme",
    "change_me",
    "change-me",
    "example",
    "secret",
    "password",
)
MIN_JWT_SECRET_BYTES = 32
# A random base64/urlsafe string of >= 32 bytes has far more than 20 distinct
# symbols; a hex string is capped at 16, so it is judged on length instead.
MIN_JWT_SECRET_DISTINCT_CHARS = 20
MIN_JWT_SECRET_HEX_CHARS = 64

# Upper bound on staff access-token lifetime (AUTH-14). Longer lifetimes turn a
# leaked token into a long-lived credential.
MAX_ACCESS_TOKEN_EXPIRE_MINUTES = 1440

_PRODUCTION_ENVIRONMENTS = {"production", "prod"}


def is_production_environment(environment: str | None) -> bool:
    """True when ``environment`` names a production deployment."""
    return (environment or "").strip().lower() in _PRODUCTION_ENVIRONMENTS


def jwt_secret_weakness(secret: str) -> str | None:
    """Return why ``secret`` is unfit to sign tokens, or None if it is fine."""
    lowered = secret.lower()
    for marker in _JWT_SECRET_PLACEHOLDER_MARKERS:
        if marker in lowered:
            return f"contains the placeholder word {marker!r}"
    if len(secret.encode("utf-8")) < MIN_JWT_SECRET_BYTES:
        return f"is shorter than {MIN_JWT_SECRET_BYTES} bytes"
    if all(c in string.hexdigits for c in secret):
        if len(secret) >= MIN_JWT_SECRET_HEX_CHARS:
            return None
        return f"is a hex string shorter than {MIN_JWT_SECRET_HEX_CHARS} characters"
    if len(set(secret)) < MIN_JWT_SECRET_DISTINCT_CHARS:
        return "does not look random (too few distinct characters)"
    return None


def _split_csv(raw: str | None) -> list[str]:
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


def public_base_url() -> str:
    """Base URL of the public-facing SPA, for links that are emailed out.

    Links must never be built from the request's Host header (AUTH-29): a
    spoofed Host would point capability links at an attacker's domain.
    Read at call time so deployments and tests can change it without a
    reload.
    """
    base = os.getenv("PUBLIC_BASE_URL") or os.getenv("FRONTEND_URL") or "http://localhost:3000"
    return base.rstrip("/")


class Config:
    """Application configuration with validation"""

    def __init__(self):

        # MongoDB
        self.MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://mongodb:27017/blackbar")

        self.ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
        self.IS_PRODUCTION = is_production_environment(self.ENVIRONMENT)

        # JWT Secret
        self.JWT_SECRET = self._load_jwt_secret()

        # Optional OpenAI key — primary configuration is in the admin LLM settings
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

        # CORS - Allow localhost for development
        origins = _split_csv(os.getenv("ALLOWED_ORIGINS", ""))
        # Default to localhost for development
        self.ALLOWED_ORIGINS = origins or ["http://localhost:3000", "http://localhost:8000"]

        # Algorithm
        self.ALGORITHM = "HS256"

        # Access-token lifetime. Reads JWT_EXPIRATION env var (integer
        # minutes) if set; falls back to 60 minutes otherwise. The
        # `.env.example` previously documented a `24h` duration string
        # which was silently ignored — Phase 4 Batch 4.4 (audit B5)
        # standardises on integer minutes and actually reads the var.
        self.ACCESS_TOKEN_EXPIRE_MINUTES = self._load_access_token_minutes()

        # Reverse proxies whose X-Forwarded-For header is believed when
        # working out the client IP for rate limiting and audit records
        # (AUTH-16). Empty (the default) means X-Forwarded-For is ignored.
        self.TRUSTED_PROXIES = _split_csv(os.getenv("TRUSTED_PROXIES"))
        for entry in self.TRUSTED_PROXIES:
            try:
                ipaddress.ip_network(entry, strict=False)
            except ValueError as exc:
                raise ValueError(
                    f"TRUSTED_PROXIES entry {entry!r} is not an IP address or CIDR"
                ) from exc

        # Storage for slowapi counters. "memory://" is per process; point it
        # at Redis (redis://host:6379) when running several workers.
        self.RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")

        # Host header allowlist for TrustedHostMiddleware (AUTH-29). Empty
        # (the default) leaves the middleware off.
        self.TRUSTED_HOSTS = _split_csv(os.getenv("TRUSTED_HOSTS"))

    def _load_jwt_secret(self) -> str:
        secret = os.getenv("JWT_SECRET") or ""
        problem = "is not set" if not secret else jwt_secret_weakness(secret)
        if problem is None:
            return secret

        guidance = "Generate one with `openssl rand -base64 48` and set JWT_SECRET in .env."
        if self.IS_PRODUCTION:
            raise ValueError(f"JWT_SECRET {problem}; refusing to start in production. {guidance}")

        message = (
            f"JWT_SECRET {problem}. Using an auto-generated JWT secret for this process only: "
            f"tokens will not survive a restart or work across workers. {guidance}"
        )
        logger.warning(message)
        warnings.warn(message, RuntimeWarning, stacklevel=2)
        return secrets.token_urlsafe(48)

    def _load_access_token_minutes(self) -> int:
        raw = os.getenv("JWT_EXPIRATION")
        if not raw:
            return 60
        try:
            minutes = int(raw)
        except ValueError:
            warnings.warn(
                f"JWT_EXPIRATION={raw!r} is not an integer (minutes); falling back to 60.",
                RuntimeWarning,
                stacklevel=3,
            )
            return 60
        if minutes <= 0:
            warnings.warn(
                f"JWT_EXPIRATION={raw!r} must be positive; falling back to 60.",
                RuntimeWarning,
                stacklevel=3,
            )
            return 60
        if minutes > MAX_ACCESS_TOKEN_EXPIRE_MINUTES:
            warnings.warn(
                f"JWT_EXPIRATION={raw!r} exceeds the {MAX_ACCESS_TOKEN_EXPIRE_MINUTES}-minute "
                f"cap; using {MAX_ACCESS_TOKEN_EXPIRE_MINUTES}.",
                RuntimeWarning,
                stacklevel=3,
            )
            return MAX_ACCESS_TOKEN_EXPIRE_MINUTES
        return minutes


# Create singleton instance
config = Config()

# Export commonly used values
JWT_SECRET = config.JWT_SECRET
ALGORITHM = config.ALGORITHM
MONGODB_URI = config.MONGODB_URI
OPENAI_API_KEY = config.OPENAI_API_KEY
ALLOWED_ORIGINS = config.ALLOWED_ORIGINS
ACCESS_TOKEN_EXPIRE_MINUTES = config.ACCESS_TOKEN_EXPIRE_MINUTES
