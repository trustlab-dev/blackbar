"""Tests for `src.llm.encryption`.

LLM-19: the key comes only from ``LLM_API_KEY_ENCRYPTION_KEY``. There is no
``/app/.env`` fallback; a missing, malformed or mismatched key fails closed
with ``EncryptionKeyError`` (a ``ValueError``). A comma-separated list of keys
supports rotation: the first encrypts, any decrypts.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

from src.llm.encryption import (
    EncryptionKeyError,
    decrypt_api_key,
    encrypt_api_key,
    get_encryption_key,
)


class TestGetEncryptionKey:
    def test_returns_key_bytes_from_env(self) -> None:
        """conftest.py sets LLM_API_KEY_ENCRYPTION_KEY to a stable Fernet key."""
        key = get_encryption_key()
        assert isinstance(key, bytes)
        Fernet(key)

    def test_reads_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        custom_key = Fernet.generate_key().decode()
        monkeypatch.setenv("LLM_API_KEY_ENCRYPTION_KEY", custom_key)
        assert get_encryption_key() == custom_key.encode()

    def test_no_dotenv_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An unset env var is an error even if a .env file exists."""
        monkeypatch.delenv("LLM_API_KEY_ENCRYPTION_KEY", raising=False)
        with patch("os.path.exists", return_value=True) as exists:
            with pytest.raises(ValueError, match="LLM_API_KEY_ENCRYPTION_KEY not set"):
                get_encryption_key()
        exists.assert_not_called()

    def test_invalid_key_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_API_KEY_ENCRYPTION_KEY", "CHANGE_THIS_TO_FERNET_KEY")
        with pytest.raises(EncryptionKeyError, match="not a valid Fernet key"):
            encrypt_api_key("sk-x")


class TestEncryptDecryptRoundtrip:
    def test_roundtrip_recovers_original_plaintext(self) -> None:
        plaintext = "sk-proj-abcdef1234567890"
        encrypted = encrypt_api_key(plaintext)
        assert encrypted != plaintext
        assert decrypt_api_key(encrypted) == plaintext

    def test_encrypt_is_non_deterministic(self) -> None:
        a = encrypt_api_key("sk-test")
        b = encrypt_api_key("sk-test")
        assert a != b
        assert decrypt_api_key(a) == decrypt_api_key(b) == "sk-test"

    def test_decrypt_rejects_tampered_ciphertext(self) -> None:
        encrypted = encrypt_api_key("payload")
        midpoint = len(encrypted) // 2
        replacement = "B" if encrypted[midpoint] == "A" else "A"
        tampered = encrypted[:midpoint] + replacement + encrypted[midpoint + 1 :]
        with pytest.raises(EncryptionKeyError):
            decrypt_api_key(tampered)

    def test_decrypt_with_different_key_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        encrypted = encrypt_api_key("sk-test-key-rotation")
        monkeypatch.setenv("LLM_API_KEY_ENCRYPTION_KEY", Fernet.generate_key().decode())
        with pytest.raises(EncryptionKeyError, match="re-enter the API key"):
            decrypt_api_key(encrypted)

    def test_rotation_list_decrypts_old_and_encrypts_with_new(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        old_key = Fernet.generate_key().decode()
        new_key = Fernet.generate_key().decode()
        monkeypatch.setenv("LLM_API_KEY_ENCRYPTION_KEY", old_key)
        old_token = encrypt_api_key("sk-old")

        monkeypatch.setenv("LLM_API_KEY_ENCRYPTION_KEY", f"{new_key},{old_key}")
        assert decrypt_api_key(old_token) == "sk-old"
        new_token = encrypt_api_key("sk-new")
        # Encrypted with the first (new) key alone.
        assert Fernet(new_key.encode()).decrypt(new_token.encode()) == b"sk-new"

    def test_encrypt_handles_unicode_plaintext(self) -> None:
        plaintext = "sk-clé-ñoñó-😀"
        assert decrypt_api_key(encrypt_api_key(plaintext)) == plaintext

    def test_encrypt_empty_string(self) -> None:
        assert decrypt_api_key(encrypt_api_key("")) == ""
