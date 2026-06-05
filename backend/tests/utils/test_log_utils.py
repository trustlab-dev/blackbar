"""Tests for ``src.utils.log_utils``.

Privacy-safe email hashing helpers used throughout the email service and
auth flows. The module is tiny (44 LoC) but is on the critical path for
keeping raw email addresses out of application logs, so pinning behavior
matters.
"""

from __future__ import annotations

import hashlib

from src.utils.log_utils import hash_email_for_logs, sanitize_email_in_message


class TestHashEmailForLogs:
    """``hash_email_for_logs`` — 12-char SHA-256 prefix, ``user_`` namespaced."""

    def test_returns_user_prefixed_hash_for_normal_email(self) -> None:
        result = hash_email_for_logs("user@example.com")
        assert result.startswith("user_")
        # 'user_' (5) + 12 hash chars
        assert len(result) == 17

    def test_is_deterministic(self) -> None:
        a = hash_email_for_logs("alice@example.com")
        b = hash_email_for_logs("alice@example.com")
        assert a == b

    def test_is_case_insensitive(self) -> None:
        """Email comparison conventions are case-insensitive; the hash
        normalizes via .lower() before hashing."""
        assert hash_email_for_logs("Alice@Example.COM") == hash_email_for_logs("alice@example.com")

    def test_different_emails_produce_different_hashes(self) -> None:
        assert hash_email_for_logs("a@example.com") != hash_email_for_logs("b@example.com")

    def test_uses_sha256_truncated_to_12_chars(self) -> None:
        """Pin the exact hash algorithm — sha256 hexdigest, first 12 chars."""
        email = "test@example.com"
        expected_hash = hashlib.sha256(email.lower().encode()).hexdigest()[:12]
        assert hash_email_for_logs(email) == f"user_{expected_hash}"

    def test_empty_email_returns_user_unknown(self) -> None:
        assert hash_email_for_logs("") == "user_unknown"

    def test_none_email_returns_user_unknown(self) -> None:
        """The current implementation treats ``None`` like empty (falsy
        check)."""
        assert hash_email_for_logs(None) == "user_unknown"  # type: ignore[arg-type]


class TestSanitizeEmailInMessage:
    """``sanitize_email_in_message`` — string replace, no-op for misses."""

    def test_replaces_email_with_hash(self) -> None:
        msg = "User user@example.com signed in"
        sanitized = sanitize_email_in_message(msg, "user@example.com")
        assert "user@example.com" not in sanitized
        assert hash_email_for_logs("user@example.com") in sanitized

    def test_returns_unchanged_when_email_not_in_message(self) -> None:
        msg = "No emails here at all"
        assert sanitize_email_in_message(msg, "user@example.com") == msg

    def test_empty_email_returns_message_unchanged(self) -> None:
        msg = "Hello world"
        assert sanitize_email_in_message(msg, "") == msg

    def test_none_email_returns_message_unchanged(self) -> None:
        msg = "Hello world"
        assert sanitize_email_in_message(msg, None) == msg  # type: ignore[arg-type]

    def test_replaces_all_occurrences_in_message(self) -> None:
        msg = "First a@b.com, then a@b.com again"
        sanitized = sanitize_email_in_message(msg, "a@b.com")
        assert "a@b.com" not in sanitized
        # str.replace replaces every occurrence
        assert sanitized.count(hash_email_for_logs("a@b.com")) == 2
