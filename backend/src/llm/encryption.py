"""
API Key Encryption Utilities
"""

import logging
import os

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)


def get_encryption_key() -> bytes:
    """
    Get encryption key from environment variable.
    If not set, raise an error (production requirement).
    """
    key_str = os.getenv("LLM_API_KEY_ENCRYPTION_KEY")

    if not key_str:
        # Try to read from .env file directly (fallback)
        env_path = "/app/.env"
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith("LLM_API_KEY_ENCRYPTION_KEY="):
                        key_str = line.split("=", 1)[1].strip()
                        logger.info("Loaded encryption key from .env file")
                        break

    if not key_str:
        raise ValueError(
            "LLM_API_KEY_ENCRYPTION_KEY not set. "
            'Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )

    return key_str.encode()


def encrypt_api_key(api_key: str) -> str:
    """
    Encrypt an API key for storage.

    Args:
        api_key: Plain text API key

    Returns:
        Encrypted API key as string
    """
    cipher = Fernet(get_encryption_key())
    encrypted = cipher.encrypt(api_key.encode())
    return encrypted.decode()


def decrypt_api_key(encrypted_key: str) -> str:
    """
    Decrypt an API key for use.

    Args:
        encrypted_key: Encrypted API key string

    Returns:
        Plain text API key
    """
    cipher = Fernet(get_encryption_key())
    decrypted = cipher.decrypt(encrypted_key.encode())
    return decrypted.decode()


def test_encryption():
    """Test encryption/decryption"""
    test_key = "sk-test-1234567890"
    encrypted = encrypt_api_key(test_key)
    decrypted = decrypt_api_key(encrypted)
    assert decrypted == test_key, "Encryption test failed"
    logger.info("Encryption test passed")


if __name__ == "__main__":
    # Run test
    logging.basicConfig(level=logging.INFO)
    test_encryption()
