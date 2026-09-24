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


def llm_encryption_key_problem(raw: str) -> str | None:
    """Why ``raw`` (one Fernet key, or several comma-separated) is unusable."""
    from cryptography.fernet import Fernet

    keys = _split_csv(raw)
    if not keys:
        return "is empty"
    for key in keys:
        try:
            Fernet(key.encode())
        except (ValueError, TypeError):
            return "is not a valid Fernet key (32 url-safe base64-encoded bytes)"
    return None


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.getenv(name, "") or default))
    except ValueError:
        return default


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(os.getenv(name, "") or default))
    except ValueError:
        return default


class LLMRuntimeSettings:
    """LLM egress settings, read from the environment at call time so that
    deployments and tests can change them without a reload.

    LLM_ALLOW_PRIVATE_ENDPOINTS   allow loopback/private-network endpoints
                                  (local model servers); default false
    LLM_SEND_CASE_CONTEXT         include case title / filename in prompts;
                                  default false (data minimisation)
    LLM_MAX_ANALYSIS_CHARS        cap on characters analysed per document
                                  (default 200000)
    LLM_CHUNK_CHARS / LLM_CHUNK_OVERLAP   chunk size and overlap for long
                                  documents (default 12000 / 400)
    LLM_MAX_SUGGESTIONS           cap on suggestions kept per document (200)
    LLM_MAX_RETRIES               retries on 429/5xx/connect errors (2)
    LLM_RETRY_BASE_DELAY          first backoff delay in seconds (1.0)
    LLM_CONNECT_TIMEOUT / LLM_READ_TIMEOUT  httpx timeouts (10 / 120 s)
    RATE_LIMIT_LLM                per-user limit on user-triggered LLM calls
                                  ("10/minute")
    LLM_REGENERATE_COOLDOWN_SECONDS  per-document cooldown between LLM
                                  analyses (60)
    AI_FEEDBACK_RETENTION_DAYS    TTL for ai_feedback records (90)
    """

    @property
    def allow_private_endpoints(self) -> bool:
        return _env_bool("LLM_ALLOW_PRIVATE_ENDPOINTS")

    @property
    def send_case_context(self) -> bool:
        return _env_bool("LLM_SEND_CASE_CONTEXT")

    @property
    def max_analysis_chars(self) -> int:
        return _env_int("LLM_MAX_ANALYSIS_CHARS", 200_000, minimum=1)

    @property
    def chunk_chars(self) -> int:
        return _env_int("LLM_CHUNK_CHARS", 12_000, minimum=500)

    @property
    def chunk_overlap(self) -> int:
        return min(_env_int("LLM_CHUNK_OVERLAP", 400), self.chunk_chars // 2)

    @property
    def max_suggestions(self) -> int:
        return _env_int("LLM_MAX_SUGGESTIONS", 200, minimum=1)

    @property
    def max_retries(self) -> int:
        return _env_int("LLM_MAX_RETRIES", 2)

    @property
    def retry_base_delay(self) -> float:
        return _env_float("LLM_RETRY_BASE_DELAY", 1.0)

    @property
    def connect_timeout(self) -> float:
        return _env_float("LLM_CONNECT_TIMEOUT", 10.0, minimum=0.1)

    @property
    def read_timeout(self) -> float:
        return _env_float("LLM_READ_TIMEOUT", 120.0, minimum=0.1)

    @property
    def user_rate_limit(self) -> str:
        return os.getenv("RATE_LIMIT_LLM", "10/minute")

    @property
    def regenerate_cooldown_seconds(self) -> int:
        return _env_int("LLM_REGENERATE_COOLDOWN_SECONDS", 60)

    @property
    def feedback_retention_days(self) -> int:
        return _env_int("AI_FEEDBACK_RETENTION_DAYS", 90, minimum=1)

    @property
    def is_production(self) -> bool:
        return is_production_environment(os.getenv("ENVIRONMENT", "development"))


llm_settings = LLMRuntimeSettings()


class Config:
    """Application configuration with validation"""

    def __init__(self):

        # MongoDB
        self.MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://mongodb:27017/blackbar")

        self.ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
        self.IS_PRODUCTION = is_production_environment(self.ENVIRONMENT)

        # JWT Secret
        self.JWT_SECRET = self._load_jwt_secret()

        # Fernet key(s) protecting stored LLM provider API keys (LLM-19).
        self.LLM_API_KEY_ENCRYPTION_KEY = self._load_llm_encryption_key()

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

    def _load_llm_encryption_key(self) -> str | None:
        """Validate LLM_API_KEY_ENCRYPTION_KEY once at startup (LLM-19).

        There is no fallback key. In production a missing or malformed key
        stops the process; elsewhere it is reported and LLM key storage
        fails closed on first use.
        """
        raw = os.getenv("LLM_API_KEY_ENCRYPTION_KEY") or ""
        problem = "is not set" if not raw else llm_encryption_key_problem(raw)
        if problem is None:
            return raw
        guidance = (
            'Generate one with: python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
        if self.IS_PRODUCTION:
            raise ValueError(
                f"LLM_API_KEY_ENCRYPTION_KEY {problem}; refusing to start in production. {guidance}"
            )
        logger.warning(
            f"LLM_API_KEY_ENCRYPTION_KEY {problem}. LLM provider keys cannot be stored or "
            f"used until it is fixed. {guidance}"
        )
        return None

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
ALLOWED_ORIGINS = config.ALLOWED_ORIGINS
ACCESS_TOKEN_EXPIRE_MINUTES = config.ACCESS_TOKEN_EXPIRE_MINUTES
