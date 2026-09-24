"""Shared slowapi limiter and proxy-aware client IP resolution (AUTH-16).

There is exactly one ``Limiter`` for the app (registered on ``app.state`` in
``src.main``); route modules import it from here.

Client IP: ``X-Forwarded-For`` is only believed when the direct peer is one
of the configured ``TRUSTED_PROXIES``. The header is then walked from the
right, skipping trusted hops, and the first untrusted address is the client.
Without ``TRUSTED_PROXIES`` the header is ignored, so it cannot be used to
dodge or poison rate limits.
"""

from __future__ import annotations

import ipaddress
import logging
import os
from functools import lru_cache

from slowapi import Limiter
from starlette.requests import Request

from src.config import config

logger = logging.getLogger(__name__)

_Network = ipaddress.IPv4Network | ipaddress.IPv6Network


@lru_cache(maxsize=8)
def _networks(entries: tuple[str, ...]) -> tuple[_Network, ...]:
    return tuple(ipaddress.ip_network(e, strict=False) for e in entries)


def _is_trusted(address: str, networks: tuple[_Network, ...]) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in net for net in networks)


_warned_untrusted_proxy = False


def _warn_if_behind_untrusted_proxy(peer: str, request: Request) -> None:
    """Log once when requests carry X-Forwarded-For from a private peer but
    no proxy is trusted: every client then shares the proxy's bucket (I4)."""
    global _warned_untrusted_proxy
    if _warned_untrusted_proxy or "x-forwarded-for" not in request.headers:
        return
    try:
        private = ipaddress.ip_address(peer).is_private
    except ValueError:
        return
    if private:
        _warned_untrusted_proxy = True
        logger.warning(
            "Requests arrive through a proxy at %s but TRUSTED_PROXIES is empty: "
            "X-Forwarded-For is ignored and all clients share one rate-limit "
            "bucket. Set TRUSTED_PROXIES to the proxy's address or network.",
            peer,
        )


def client_ip(request: Request) -> str:
    """Best-effort client IP for rate limiting and audit records."""
    peer = request.client.host if request.client else "unknown"
    networks = _networks(tuple(config.TRUSTED_PROXIES))
    if not networks:
        _warn_if_behind_untrusted_proxy(peer, request)
        return peer
    if not _is_trusted(peer, networks):
        return peer

    forwarded = request.headers.get("x-forwarded-for", "")
    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    for hop in reversed(hops):
        try:
            ipaddress.ip_address(hop)
        except ValueError:
            # Garbage in the header: stop trusting it at this point.
            return peer
        if not _is_trusted(hop, networks):
            return hop
    return hops[0] if hops else peer


# Per-route limits; env-overridable for load tests or unusual deployments.
LOGIN_LIMIT = os.getenv("RATE_LIMIT_LOGIN", "5/minute")
AUTH_TOKEN_LIMIT = os.getenv("RATE_LIMIT_AUTH_TOKEN", "10/minute")
PUBLIC_LOOKUP_LIMIT = os.getenv("RATE_LIMIT_PUBLIC_LOOKUP", "10/minute")

# key_style="endpoint": buckets are per (client, route function). slowapi's
# default "url" style keys on the concrete path, which would give every
# guessed /track/{tracking_number} its own fresh bucket.
limiter = Limiter(
    key_func=client_ip,
    storage_uri=config.RATELIMIT_STORAGE_URI,
    key_style="endpoint",
)
