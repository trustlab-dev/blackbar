"""
API key encryption for stored LLM provider credentials.

The key comes only from ``LLM_API_KEY_ENCRYPTION_KEY`` (LLM-19). There is no
fallback key and no ``.env`` parsing: without a valid key, encrypting or
decrypting fails closed. ``src.config`` validates the key at startup and
refuses to start in production without one.

Rotation: set ``LLM_API_KEY_ENCRYPTION_KEY`` to a comma-separated list
``new,old``. New values are encrypted with the first key; any listed key
decrypts (MultiFernet). Re-save each LLM config (or re-enter its key) to
move it to the new key, then drop the old one.
"""

import logging
import os

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

logger = logging.getLogger(__name__)

ENV_VAR = "LLM_API_KEY_ENCRYPTION_KEY"


class EncryptionKeyError(ValueError):
    """The encryption key is missing, malformed, or does not match the data."""


def get_encryption_keys() -> list[bytes]:
    """Return the configured Fernet keys (first one encrypts)."""
    raw = os.getenv(ENV_VAR) or ""
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise EncryptionKeyError(
            f"{ENV_VAR} not set. Generate one with: "
            'python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    return [k.encode() for k in keys]


def get_encryption_key() -> bytes:
    """The primary (encrypting) key."""
    return get_encryption_keys()[0]


def _cipher() -> MultiFernet:
    try:
        return MultiFernet([Fernet(k) for k in get_encryption_keys()])
    except (ValueError, TypeError) as exc:
        if isinstance(exc, EncryptionKeyError):
            raise
        raise EncryptionKeyError(f"{ENV_VAR} is not a valid Fernet key") from None


def encrypt_api_key(api_key: str) -> str:
    """Encrypt an API key for storage."""
    return _cipher().encrypt(api_key.encode()).decode()


def decrypt_api_key(encrypted_key: str) -> str:
    """Decrypt a stored API key. Raises EncryptionKeyError when no configured
    key can decrypt it (for example after an incomplete key rotation)."""
    try:
        return _cipher().decrypt(encrypted_key.encode()).decode()
    except InvalidToken:
        raise EncryptionKeyError(
            f"Stored LLM API key cannot be decrypted with {ENV_VAR}; "
            "re-enter the API key for this configuration."
        ) from None
