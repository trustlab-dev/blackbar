"""
Logging utilities for privacy-safe logging
Prevents PII exposure in application logs
"""

import hashlib


def hash_email_for_logs(email: str) -> str:
    """
    Hash email for logging while maintaining uniqueness for debugging

    Args:
        email: Email address to hash

    Returns:
        Short hash (12 chars) prefixed with 'user_'

    Example:
        hash_email_for_logs("user@example.com") -> "user_a3b2c1d4e5f6"
    """
    if not email:
        return "user_unknown"

    # Use SHA256 for consistent hashing
    email_hash = hashlib.sha256(email.lower().encode()).hexdigest()[:12]
    return f"user_{email_hash}"


def sanitize_email_in_message(message: str, email: str) -> str:
    """
    Replace email address with hash in log message

    Args:
        message: Log message that may contain email
        email: Email address to replace

    Returns:
        Message with email replaced by hash
    """
    if not email or email not in message:
        return message

    email_hash = hash_email_for_logs(email)
    return message.replace(email, email_hash)
