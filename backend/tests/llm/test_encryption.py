"""Tests for `src.llm.encryption`.

Phase 2.6. Critical-path module — target 100% line + branch coverage.

Covers:
    - `get_encryption_key` (env var path, /app/.env fallback, missing-key error)
    - `encrypt_api_key` (roundtrip + Fernet usage)
    - `decrypt_api_key` (roundtrip + tamper rejection)
    - `test_encryption` self-test helper
    - `__main__` execution path (via runpy)

Reality pins:
- `get_encryption_key()` reads `LLM_API_KEY_ENCRYPTION_KEY` env var first.
- If env var unset, falls back to scanning `/app/.env` for the key.
- If still unset, raises `ValueError` instructing how to generate a key.
- Encrypted output is a non-deterministic Fernet token (each call differs)
  but always decrypts back to the original plaintext.
- A tampered ciphertext raises `cryptography.fernet.InvalidToken`.
- A ciphertext encrypted with key A cannot be decrypted with key B
  (raises `InvalidToken`).
"""

from __future__ import annotations

import os
import runpy
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet, InvalidToken

from src.llm.encryption import (
    decrypt_api_key,
    encrypt_api_key,
    get_encryption_key,
)
from src.llm.encryption import (
    test_encryption as encryption_self_test,
)

# ---------------------------------------------------------------------------
# get_encryption_key
# ---------------------------------------------------------------------------


class TestGetEncryptionKey:
    def test_returns_key_bytes_from_env(self) -> None:
        """conftest.py sets LLM_API_KEY_ENCRYPTION_KEY to a stable Fernet key."""
        key = get_encryption_key()
        assert isinstance(key, bytes)
        # Must be a valid Fernet key
        Fernet(key)  # raises if invalid

    def test_reads_env_var_priority(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Env var takes precedence even when /app/.env exists."""
        custom_key = Fernet.generate_key().decode()
        monkeypatch.setenv("LLM_API_KEY_ENCRYPTION_KEY", custom_key)
        assert get_encryption_key() == custom_key.encode()

    def test_falls_back_to_dotenv_when_env_unset(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """When the env var is missing, the function reads /app/.env directly."""
        monkeypatch.delenv("LLM_API_KEY_ENCRYPTION_KEY", raising=False)
        key_value = Fernet.generate_key().decode()

        # Build a fake .env file and patch `os.path.exists` + `open` to point at it
        fake_env = tmp_path / ".env"
        fake_env.write_text(
            "OTHER_VAR=something\n" f"LLM_API_KEY_ENCRYPTION_KEY={key_value}\n" "ANOTHER=value\n"
        )

        real_exists = os.path.exists
        real_open = open

        def fake_exists(path: str) -> bool:
            if path == "/app/.env":
                return True
            return real_exists(path)

        def fake_open(path: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if path == "/app/.env":
                return real_open(fake_env, *args, **kwargs)
            return real_open(path, *args, **kwargs)

        with patch("src.llm.encryption.os.path.exists", side_effect=fake_exists):
            with patch("builtins.open", side_effect=fake_open):
                result = get_encryption_key()

        assert result == key_value.encode()

    def test_raises_value_error_when_no_key_anywhere(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No env var + no /app/.env => ValueError with helpful generation hint."""
        monkeypatch.delenv("LLM_API_KEY_ENCRYPTION_KEY", raising=False)
        with patch("src.llm.encryption.os.path.exists", return_value=False):
            with pytest.raises(ValueError, match="LLM_API_KEY_ENCRYPTION_KEY not set"):
                get_encryption_key()

    def test_raises_value_error_when_dotenv_missing_key_line(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """`/app/.env` exists but doesn't contain LLM_API_KEY_ENCRYPTION_KEY line."""
        monkeypatch.delenv("LLM_API_KEY_ENCRYPTION_KEY", raising=False)

        fake_env = tmp_path / ".env"
        fake_env.write_text("OTHER_VAR=value\nUNRELATED=thing\n")

        real_exists = os.path.exists
        real_open = open

        def fake_exists(path: str) -> bool:
            if path == "/app/.env":
                return True
            return real_exists(path)

        def fake_open(path: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if path == "/app/.env":
                return real_open(fake_env, *args, **kwargs)
            return real_open(path, *args, **kwargs)

        with patch("src.llm.encryption.os.path.exists", side_effect=fake_exists):
            with patch("builtins.open", side_effect=fake_open):
                with pytest.raises(ValueError, match="LLM_API_KEY_ENCRYPTION_KEY not set"):
                    get_encryption_key()


# ---------------------------------------------------------------------------
# encrypt_api_key / decrypt_api_key roundtrip
# ---------------------------------------------------------------------------


class TestEncryptDecryptRoundtrip:
    def test_roundtrip_recovers_original_plaintext(self) -> None:
        plaintext = "sk-proj-abcdef1234567890"
        encrypted = encrypt_api_key(plaintext)
        assert encrypted != plaintext
        assert decrypt_api_key(encrypted) == plaintext

    def test_encrypt_returns_string(self) -> None:
        result = encrypt_api_key("some-key")
        assert isinstance(result, str)

    def test_encrypt_is_non_deterministic(self) -> None:
        """Fernet includes a fresh IV per encryption — same input, different output."""
        plaintext = "sk-test-deterministic"
        a = encrypt_api_key(plaintext)
        b = encrypt_api_key(plaintext)
        assert a != b
        # But both must decrypt to the same value
        assert decrypt_api_key(a) == plaintext
        assert decrypt_api_key(b) == plaintext

    def test_decrypt_rejects_tampered_ciphertext(self) -> None:
        encrypted = encrypt_api_key("payload")
        # Flip a character in the middle — must be a valid base64 char to
        # ensure we test integrity rejection, not decoding failure.
        midpoint = len(encrypted) // 2
        # 'A' / 'B' are both valid base64-urlsafe alphabet members
        replacement = "B" if encrypted[midpoint] == "A" else "A"
        tampered = encrypted[:midpoint] + replacement + encrypted[midpoint + 1 :]
        with pytest.raises(InvalidToken):
            decrypt_api_key(tampered)

    def test_decrypt_with_different_key_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ciphertext from key A cannot be decrypted under key B."""
        # Encrypt under the conftest-provided key
        plaintext = "sk-test-key-rotation"
        encrypted = encrypt_api_key(plaintext)

        # Now rotate the key and attempt decryption — must fail
        new_key = Fernet.generate_key().decode()
        monkeypatch.setenv("LLM_API_KEY_ENCRYPTION_KEY", new_key)
        with pytest.raises(InvalidToken):
            decrypt_api_key(encrypted)

    def test_encrypt_handles_unicode_plaintext(self) -> None:
        plaintext = "sk-clé-ñoñó-😀"
        recovered = decrypt_api_key(encrypt_api_key(plaintext))
        assert recovered == plaintext

    def test_encrypt_empty_string(self) -> None:
        """Empty string is a valid Fernet input — roundtrips cleanly."""
        encrypted = encrypt_api_key("")
        assert decrypt_api_key(encrypted) == ""


# ---------------------------------------------------------------------------
# `test_encryption` self-test helper + `__main__` block
# ---------------------------------------------------------------------------


class TestSelfTest:
    def test_self_test_runs_without_assertion_error(self) -> None:
        """The source-level `test_encryption()` helper must round-trip cleanly
        under the conftest-provided key."""
        # Returns None on success; raises AssertionError on failure
        assert encryption_self_test() is None

    def test_module_main_block_executes(self) -> None:
        """Running the module as `__main__` exercises the
        `if __name__ == "__main__":` guard. logging.basicConfig + self-test."""
        # runpy.run_path runs the file under `__name__ == "__main__"` so the
        # bottom-of-file guard executes, side-stepping the already-imported
        # `src.llm.encryption` module in sys.modules. No exception => self-test passed.
        encryption_file = (
            Path(__file__).resolve().parent.parent.parent / "src" / "llm" / "encryption.py"
        )
        runpy.run_path(str(encryption_file), run_name="__main__")
