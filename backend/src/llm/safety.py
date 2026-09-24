"""
Safety helpers for the LLM egress path.

- ``redact_secrets``: scrub API keys and credentials from any text before it
  is logged, stored, or returned (LLM-02).
- ``LLMProviderError`` / ``LLMDisabledError``: typed failures whose ``str()``
  never contains provider response bodies or request URLs.
- ``validate_llm_endpoint``: https-only, no private/link-local targets unless
  explicitly allowed (LLM-05).
- ``log_content_debug``: document text and prompts are only ever logged at
  DEBUG, truncated, and never in production (LLM-10).
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
import uuid
from collections.abc import Iterable
from urllib.parse import urlsplit

from src.config import llm_settings

_REDACTED = "[REDACTED]"

# Query parameters, header-style pairs and bearer tokens that carry secrets.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)([?&](?:key|api[_-]?key|access[_-]?token|token|sig|signature)=)[^&\s'\"#]+"),
    re.compile(
        r"(?i)((?:x-goog-api-key|x-api-key|api-key|authorization|proxy-authorization)"
        r"[\"']?\s*[:=]\s*[\"']?)(?:bearer\s+|basic\s+)?[^\s,'\"}]+"
    ),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"),
    # Well-known key shapes: OpenAI/Anthropic "sk-...", Google "AIza...",
    # Cohere/other long opaque tokens prefixed with a vendor tag.
    re.compile(r"()\bsk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"()\bAIza[0-9A-Za-z_-]{20,}"),
)


def redact_secrets(text: object, secrets: Iterable[str | None] = ()) -> str:
    """Return ``text`` with credentials removed.

    ``secrets`` are exact values (for example the decrypted API key and
    custom header values) that are replaced wherever they appear, whatever
    their shape.
    """
    out = "" if text is None else str(text)
    for secret in secrets:
        if secret and len(secret) >= 4:
            out = out.replace(secret, _REDACTED)
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub(lambda m: f"{m.group(1)}{_REDACTED}", out)
    return out


def new_error_reference() -> str:
    """Short opaque id that ties a generic client message to the server log."""
    try:
        from src.core.correlation import get_correlation_id

        cid = get_correlation_id()
    except Exception:  # pragma: no cover - import cycle guard
        cid = None
    return cid or uuid.uuid4().hex[:12]


class LLMError(Exception):
    """Base class for LLM failures that are safe to surface generically."""

    code = "llm_error"
    public_message = "The AI provider request failed."

    def __init__(self, message: str | None = None, *, reference: str | None = None):
        self.reference = reference or new_error_reference()
        super().__init__(message or self.public_message)

    def public_detail(self) -> str:
        return f"{self.public_message} (reference {self.reference})"


class LLMDisabledError(LLMError):
    """The default LLM configuration exists but is switched off."""

    code = "ai_disabled"
    public_message = "AI features are disabled: the default LLM configuration is turned off."

    def public_detail(self) -> str:
        return self.public_message


class LLMNotConfiguredError(LLMError):
    code = "ai_not_configured"
    public_message = (
        "AI features are unavailable: no default LLM is set. Visit Admin → LLM "
        "Configuration and click 'Set Default' on an enabled config."
    )

    def public_detail(self) -> str:
        return self.public_message


class LLMProviderError(LLMError):
    """A provider call failed. ``str()`` holds only status and provider;
    ``detail`` holds the redacted provider message for DEBUG logging."""

    code = "provider_error"

    def __init__(
        self,
        provider: str,
        status_code: int | None = None,
        *,
        detail: str = "",
        reference: str | None = None,
    ):
        self.provider = provider
        self.status_code = status_code
        self.detail = detail
        status = f"HTTP {status_code}" if status_code else "connection error"
        super().__init__(f"{provider} request failed ({status})", reference=reference)

    def public_detail(self) -> str:
        status = f"HTTP {self.status_code}" if self.status_code else "no response"
        return f"The AI provider request failed ({status}). Reference {self.reference}."


class LLMEndpointError(ValueError):
    """An LLM endpoint URL failed validation."""


# ---------------------------------------------------------------------------
# Endpoint validation (LLM-05)
# ---------------------------------------------------------------------------

_BLOCKED_HOSTNAMES = {"metadata.google.internal", "metadata", "instance-data"}
_LOOPBACK_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost"}


def _classify_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    """Return why ``ip`` is not a public address, or None."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.is_link_local:
        return "link-local"
    if ip.is_loopback:
        return "loopback"
    if ip.is_unspecified or ip.is_multicast or ip.is_reserved:
        return "reserved"
    if ip.is_private or (isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT):
        return "private"
    return None


_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def _check_address(host: str, reason: str | None, allow_private: bool) -> None:
    if reason is None:
        return
    # Link-local (cloud metadata, 169.254.0.0/16) is never a model server.
    if reason == "link-local" or reason == "reserved" or not allow_private:
        raise LLMEndpointError(
            f"Endpoint host {host!r} resolves to a {reason} address. "
            + (
                "Set LLM_ALLOW_PRIVATE_ENDPOINTS=true to allow private-network model servers."
                if reason in ("private", "loopback")
                else "This address range is not allowed."
            )
        )


def validate_llm_endpoint_static(url: str) -> str:
    """Scheme/host checks that need no DNS. Returns the lower-cased host."""
    allow_private = llm_settings.allow_private_endpoints
    try:
        parts = urlsplit((url or "").strip())
    except ValueError as exc:
        raise LLMEndpointError("Endpoint is not a valid URL") from exc
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme not in ("http", "https") or not host:
        raise LLMEndpointError("Endpoint must be an absolute http(s) URL")
    if parts.username or parts.password:
        raise LLMEndpointError("Endpoint must not embed credentials")
    if parts.query and re.search(r"(?i)(^|&)(key|api[_-]?key)=", parts.query):
        raise LLMEndpointError("Put the API key in the key field, not in the endpoint URL")
    if host in _BLOCKED_HOSTNAMES or host.endswith(".internal"):
        raise LLMEndpointError(f"Endpoint host {host!r} is not allowed")

    is_loopback_name = host in _LOOPBACK_HOSTNAMES or host.endswith(".localhost")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    is_loopback = is_loopback_name or bool(ip and _classify_ip(ip) == "loopback")

    if parts.scheme != "https" and not is_loopback:
        raise LLMEndpointError("Endpoint must use https (plain http is allowed only for localhost)")
    if is_loopback_name:
        _check_address(host, "loopback", allow_private)
    if ip is not None:
        _check_address(host, _classify_ip(ip), allow_private)
    return host


async def _resolve(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await asyncio.wait_for(
        loop.getaddrinfo(host, None, type=socket.SOCK_STREAM), timeout=3.0
    )
    return sorted({str(info[4][0]) for info in infos})


async def validate_llm_endpoint(url: str) -> None:
    """Full validation for admin writes and connection tests: static checks
    plus DNS resolution, rejecting hosts that resolve to private or
    link-local ranges. An unresolvable host is accepted (it cannot be
    reached either); DNS rebinding is out of scope."""
    host = validate_llm_endpoint_static(url)
    try:
        ipaddress.ip_address(host)
        return  # literal already checked
    except ValueError:
        pass
    try:
        addresses = await _resolve(host)
    except (OSError, TimeoutError, UnicodeError):
        return
    allow_private = llm_settings.allow_private_endpoints
    for addr in addresses:
        try:
            ip = ipaddress.ip_address(addr.split("%", 1)[0])
        except ValueError:
            continue
        _check_address(host, _classify_ip(ip), allow_private)


# ---------------------------------------------------------------------------
# Content logging (LLM-10)
# ---------------------------------------------------------------------------

_CONTENT_PREVIEW_CHARS = 80


def log_content_debug(logger: logging.Logger, label: str, text: object) -> None:
    """Log a truncated preview of document/prompt/model text at DEBUG only,
    and never when ENVIRONMENT is production."""
    if llm_settings.is_production or not logger.isEnabledFor(logging.DEBUG):
        return
    value = "" if text is None else str(text)
    preview = value[:_CONTENT_PREVIEW_CHARS].replace("\n", " ")
    suffix = "…" if len(value) > _CONTENT_PREVIEW_CHARS else ""
    logger.debug("%s (%d chars): %s%s", label, len(value), preview, suffix)
