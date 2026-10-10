"""AUTH-16: proxy-aware client IP and rate limits on the auth endpoints."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.core.rate_limit import client_ip


def _req(peer: str, xff: str | None = None):
    headers = {"x-forwarded-for": xff} if xff is not None else {}
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)


@pytest.fixture
def trusted(monkeypatch: pytest.MonkeyPatch):
    from src.config import config

    def _set(entries: list[str]) -> None:
        monkeypatch.setattr(config, "TRUSTED_PROXIES", entries)

    return _set


class TestClientIp:
    def test_forwarded_for_ignored_without_trusted_proxies(self, trusted) -> None:
        trusted([])
        assert client_ip(_req("172.18.0.5", "1.2.3.4")) == "172.18.0.5"

    def test_forwarded_for_ignored_when_peer_is_not_trusted(self, trusted) -> None:
        trusted(["172.18.0.0/16"])
        assert client_ip(_req("203.0.113.9", "1.2.3.4")) == "203.0.113.9"

    def test_forwarded_for_used_behind_trusted_proxy(self, trusted) -> None:
        trusted(["172.18.0.0/16"])
        assert client_ip(_req("172.18.0.5", "1.2.3.4")) == "1.2.3.4"

    def test_rightmost_untrusted_hop_wins_over_spoofed_prefix(self, trusted) -> None:
        """A client can prepend anything; only hops added by trusted proxies
        are believed."""
        trusted(["172.18.0.0/16", "10.0.0.1"])
        assert client_ip(_req("172.18.0.5", "6.6.6.6, 1.2.3.4, 10.0.0.1")) == "1.2.3.4"

    def test_garbage_header_falls_back_to_peer(self, trusted) -> None:
        trusted(["172.18.0.0/16"])
        assert client_ip(_req("172.18.0.5", "not-an-ip")) == "172.18.0.5"

    def test_missing_header_uses_peer(self, trusted) -> None:
        trusted(["172.18.0.0/16"])
        assert client_ip(_req("172.18.0.5")) == "172.18.0.5"


class TestUntrustedProxyWarning:
    def test_warns_once_when_proxy_headers_arrive_untrusted(
        self, trusted, monkeypatch: pytest.MonkeyPatch, caplog
    ) -> None:
        import logging

        from src.core import rate_limit

        monkeypatch.setattr(rate_limit, "_warned_untrusted_proxy", False)
        trusted([])
        with caplog.at_level(logging.WARNING, logger="src.core.rate_limit"):
            client_ip(_req("172.30.87.4", "1.2.3.4"))
            client_ip(_req("172.30.87.4", "5.6.7.8"))
        warnings = [r for r in caplog.records if "TRUSTED_PROXIES is empty" in r.message]
        assert len(warnings) == 1

    def test_no_warning_for_direct_public_clients(
        self, trusted, monkeypatch: pytest.MonkeyPatch, caplog
    ) -> None:
        import logging

        from src.core import rate_limit

        monkeypatch.setattr(rate_limit, "_warned_untrusted_proxy", False)
        trusted([])
        with caplog.at_level(logging.WARNING, logger="src.core.rate_limit"):
            client_ip(_req("8.8.8.8", "1.2.3.4"))
            client_ip(_req("172.30.87.4"))
        assert not [r for r in caplog.records if "TRUSTED_PROXIES" in r.message]


class TestShippedComposeTrustsTheProxyNetwork:
    """I4: behind the shipped nginx/Vite container, X-Forwarded-For must be
    honoured, so every compose file sets TRUSTED_PROXIES to the network."""

    @pytest.mark.parametrize(
        "name", ["docker-compose.yml", "docker-compose.prod.yml", "docker-compose.demo.yml"]
    )
    def test_compose_sets_trusted_proxies(self, name: str) -> None:
        import ipaddress
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[3]
        text = (root / name).read_text()
        match = re.search(
            r"TRUSTED_PROXIES=\$\{TRUSTED_PROXIES:-\$\{BLACKBAR_NETWORK_SUBNET:-([^}]+)\}\}",
            text,
        )
        assert match, f"{name} does not set TRUSTED_PROXIES"
        default = ipaddress.ip_network(match.group(1))
        base = (root / "docker-compose.yml").read_text()
        subnet = re.search(r"subnet: \$\{BLACKBAR_NETWORK_SUBNET:-([^}]+)\}", base)
        assert subnet and ipaddress.ip_network(subnet.group(1)) == default
        # The default must itself be a valid TRUSTED_PROXIES value in code.
        assert default.is_private


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


class TestAuthEndpointLimits:
    async def test_login_is_limited(self, app, monkeypatch, db) -> None:
        import src.auth.routes as auth_routes

        monkeypatch.setattr(auth_routes, "db", db)
        async with _client(app) as c:
            codes = [
                (
                    await c.post(
                        "/api/v1/auth/login",
                        json={"email": "nobody@example.com", "password": "wrong-password"},
                    )
                ).status_code
                for _ in range(6)
            ]
        assert codes[:5] == [401] * 5
        assert codes[5] == 429

    async def test_magic_link_request_is_limited_per_ip(self, app, monkeypatch) -> None:
        """The per-email throttle alone allowed mailbombing many addresses."""
        import src.auth.magic_link_routes as ml_routes
        from src.auth.magic_link_routes import get_magic_link_service
        from src.auth.magic_link_service import MagicLinkService

        svc = AsyncMock(spec=MagicLinkService)
        svc.request_magic_link.return_value = ("tok", None)
        monkeypatch.setattr(
            ml_routes.email_service, "send_magic_link", MagicMock(return_value=True)
        )
        app.dependency_overrides[get_magic_link_service] = lambda: svc
        try:
            async with _client(app) as c:
                codes = [
                    (
                        await c.post(
                            "/api/v1/auth/public/magic-link/request",
                            json={"email": f"victim{i}@example.org"},
                        )
                    ).status_code
                    for i in range(12)
                ]
        finally:
            app.dependency_overrides.pop(get_magic_link_service, None)
        assert codes[:10] == [200] * 10
        assert 429 in codes[10:]

    async def test_magic_link_verify_is_limited(self, app) -> None:
        from src.auth.magic_link_routes import get_magic_link_service
        from src.auth.magic_link_service import MagicLinkService

        svc = AsyncMock(spec=MagicLinkService)
        svc.verify_magic_link.return_value = None
        app.dependency_overrides[get_magic_link_service] = lambda: svc
        try:
            async with _client(app) as c:
                codes = [
                    (
                        await c.post(
                            "/api/v1/auth/public/magic-link/verify",
                            json={"email": "a@example.org", "token": f"guess-{i}"},
                        )
                    ).status_code
                    for i in range(12)
                ]
        finally:
            app.dependency_overrides.pop(get_magic_link_service, None)
        assert codes[:10] == [400] * 10
        assert 429 in codes[10:]

    async def test_activation_is_limited(self, app, monkeypatch, db) -> None:
        import src.auth.activation_routes as act_routes

        monkeypatch.setattr(act_routes, "db", db)
        async with _client(app) as c:
            codes = [
                (
                    await c.post(
                        "/api/v1/auth/activate-owner",
                        json={
                            "email": "owner@example.com",
                            "token": f"guess-{i}",
                            "password": "Strong-Passphrase-99!",
                        },
                    )
                ).status_code
                for i in range(12)
            ]
        assert codes[:10] == [400] * 10
        assert 429 in codes[10:]
