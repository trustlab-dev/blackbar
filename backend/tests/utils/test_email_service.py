"""Tests for ``src.utils.email_service``.

The ``EmailService`` class wraps SendGrid for four flows:
- send_magic_link (RFC-007)
- send_contributor_invitation (RFC-010)
- send_transfer_notification (RFC-010)
- send_contributor_reminder (RFC-010)

All four follow the same shape: no api_key -> dev-mode log, else build
Mail, call ``client.send``, branch on 2xx vs other status, catch
exceptions. We test the env-driven constructor, every dev-mode branch,
every 2xx success, every non-2xx failure, and every exception swallow.

Audit Section 1 fix (Phase 1.6) renamed all keyword args to ``org_name``
(no more ``tenant_*``); the tests pin that naming.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _import_fresh_module():
    """Import ``src.utils.email_service`` fresh so monkeypatched env vars
    are read at __init__ time per test."""
    import importlib

    import src.utils.email_service as mod

    return importlib.reload(mod)


# ---------------------------------------------------------------------------
# Constructor / env handling
# ---------------------------------------------------------------------------


class TestEmailServiceInit:
    def test_no_api_key_disables_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
        mod = _import_fresh_module()
        svc = mod.EmailService()
        assert svc.client is None
        # Default from_email/from_name are wired
        assert svc.from_email == "noreply@blackbar.app"
        assert svc.from_name == "Blackbar FOI System"

    def test_with_api_key_creates_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SENDGRID_API_KEY", "SG.test-key")
        mod = _import_fresh_module()
        svc = mod.EmailService()
        assert svc.client is not None

    def test_custom_from_email_and_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SENDGRID_API_KEY", "SG.test")
        monkeypatch.setenv("SENDGRID_FROM_EMAIL", "foi@org.example")
        monkeypatch.setenv("SENDGRID_FROM_NAME", "Org FOI")
        mod = _import_fresh_module()
        svc = mod.EmailService()
        assert svc.from_email == "foi@org.example"
        assert svc.from_name == "Org FOI"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_svc_with_mocked_client(status_code: int = 202, body: str | None = None):
    """Build an EmailService whose ``client.send`` returns a stub Response."""
    import importlib

    import src.utils.email_service as mod

    importlib.reload(mod)
    svc = mod.EmailService.__new__(mod.EmailService)
    svc.api_key = "SG.test"
    svc.from_email = "noreply@blackbar.app"
    svc.from_name = "Blackbar FOI System"
    client = MagicMock()
    response = MagicMock()
    response.status_code = status_code
    response.body = body or ""
    client.send.return_value = response
    svc.client = client
    return svc, mod, client


# ---------------------------------------------------------------------------
# send_magic_link
# ---------------------------------------------------------------------------


class TestSendMagicLink:
    def test_no_client_returns_false_dev_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
        mod = _import_fresh_module()
        svc = mod.EmailService()
        result = svc.send_magic_link(
            to_email="dev@example.test",
            magic_link_url="https://app/magic/abc",
        )
        assert result is False

    def test_success_2xx(self) -> None:
        svc, _mod, client = _make_svc_with_mocked_client(status_code=202)
        ok = svc.send_magic_link(
            to_email="a@b.com",
            magic_link_url="https://app/magic/xyz",
            org_name="Test Org",
            expires_minutes=15,
        )
        assert ok is True
        client.send.assert_called_once()
        # Inspect the Mail object passed in
        sent_mail = client.send.call_args[0][0]
        # The subject is set on sent_mail.subject; SendGrid stores it as a Subject object.
        # We just verify call happened — full Mail.get attributes are private.
        assert sent_mail is not None

    def test_success_with_default_org_name(self) -> None:
        svc, _mod, client = _make_svc_with_mocked_client()
        ok = svc.send_magic_link(
            to_email="a@b.com",
            magic_link_url="https://app/magic/xyz",
        )
        assert ok is True

    def test_non_2xx_returns_false(self) -> None:
        svc, _mod, client = _make_svc_with_mocked_client(status_code=500, body="server error")
        ok = svc.send_magic_link(
            to_email="a@b.com",
            magic_link_url="https://app/magic/xyz",
        )
        assert ok is False
        client.send.assert_called_once()

    def test_exception_returns_false(self) -> None:
        svc, _mod, client = _make_svc_with_mocked_client()
        client.send.side_effect = RuntimeError("network down")
        ok = svc.send_magic_link(
            to_email="a@b.com",
            magic_link_url="https://app/magic/xyz",
        )
        assert ok is False


class TestMagicLinkTemplates:
    """The HTML/text template builders are private but worth exercising
    directly — they're pure string builders so any logic regression
    surfaces immediately."""

    def test_html_template_includes_org_name_url_and_expiry(self) -> None:
        svc, _mod, _client = _make_svc_with_mocked_client()
        html = svc._build_html_template(
            magic_link_url="https://app/m/zzz",
            org_name="Acme Org",
            expires_minutes=30,
        )
        assert "Acme Org" in html
        assert "https://app/m/zzz" in html
        assert "30 minutes" in html
        assert "<!DOCTYPE html>" in html

    def test_text_template_includes_org_name_url_and_expiry(self) -> None:
        svc, _mod, _client = _make_svc_with_mocked_client()
        text = svc._build_text_template(
            magic_link_url="https://app/m/yyy",
            org_name="Acme Org",
            expires_minutes=5,
        )
        assert "Acme Org" in text
        assert "https://app/m/yyy" in text
        assert "5 minutes" in text


# ---------------------------------------------------------------------------
# send_contributor_invitation
# ---------------------------------------------------------------------------


class TestSendContributorInvitation:
    def test_no_client_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
        mod = _import_fresh_module()
        svc = mod.EmailService()
        ok = svc.send_contributor_invitation(
            to_email="c@example.test",
            contributor_name="Charlie",
            upload_url="https://app/upload/xyz",
            case_tracking_number="FOI-2026-0001",
        )
        assert ok is False

    def test_success_2xx(self) -> None:
        svc, _mod, client = _make_svc_with_mocked_client()
        ok = svc.send_contributor_invitation(
            to_email="c@example.test",
            contributor_name="Charlie",
            upload_url="https://app/upload/xyz",
            case_tracking_number="FOI-2026-0001",
            org_name="Test Org",
            expires_days=14,
        )
        assert ok is True
        client.send.assert_called_once()

    def test_non_2xx_returns_false(self) -> None:
        svc, _mod, client = _make_svc_with_mocked_client(status_code=403)
        ok = svc.send_contributor_invitation(
            to_email="c@example.test",
            contributor_name="Charlie",
            upload_url="https://app/upload/xyz",
            case_tracking_number="FOI-2026-0001",
        )
        assert ok is False

    def test_exception_returns_false(self) -> None:
        svc, _mod, client = _make_svc_with_mocked_client()
        client.send.side_effect = RuntimeError("boom")
        ok = svc.send_contributor_invitation(
            to_email="c@example.test",
            contributor_name="Charlie",
            upload_url="https://app/upload/xyz",
            case_tracking_number="FOI-2026-0001",
        )
        assert ok is False


# ---------------------------------------------------------------------------
# send_transfer_notification
# ---------------------------------------------------------------------------


class TestSendTransferNotification:
    def test_no_client_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
        mod = _import_fresh_module()
        svc = mod.EmailService()
        ok = svc.send_transfer_notification(
            to_email="r@example.test",
            recipient_name="Recipient",
            recipient_organization="Other Org",
            transfer_url="https://app/transfer/abc",
            case_tracking_number="FOI-2026-0002",
            transfer_reason="Wrong jurisdiction",
        )
        assert ok is False

    def test_success_2xx_with_recipient_name(self) -> None:
        svc, _mod, client = _make_svc_with_mocked_client()
        ok = svc.send_transfer_notification(
            to_email="r@example.test",
            recipient_name="Recipient",
            recipient_organization="Other Org",
            transfer_url="https://app/transfer/abc",
            case_tracking_number="FOI-2026-0002",
            transfer_reason="Wrong jurisdiction",
            sender_organization="My Org",
        )
        assert ok is True

    def test_success_2xx_without_recipient_name(self) -> None:
        """The greeting branches on recipient_name being truthy."""
        svc, _mod, client = _make_svc_with_mocked_client()
        ok = svc.send_transfer_notification(
            to_email="r@example.test",
            recipient_name="",  # falsy -> "Hello," branch
            recipient_organization="Other Org",
            transfer_url="https://app/transfer/abc",
            case_tracking_number="FOI-2026-0002",
            transfer_reason="Wrong jurisdiction",
        )
        assert ok is True

    def test_non_2xx_returns_false(self) -> None:
        svc, _mod, client = _make_svc_with_mocked_client(status_code=400)
        ok = svc.send_transfer_notification(
            to_email="r@example.test",
            recipient_name="Recipient",
            recipient_organization="Other Org",
            transfer_url="https://app/transfer/abc",
            case_tracking_number="FOI-2026-0002",
            transfer_reason="Wrong jurisdiction",
        )
        assert ok is False

    def test_exception_returns_false(self) -> None:
        svc, _mod, client = _make_svc_with_mocked_client()
        client.send.side_effect = RuntimeError("network")
        ok = svc.send_transfer_notification(
            to_email="r@example.test",
            recipient_name="Recipient",
            recipient_organization="Other Org",
            transfer_url="https://app/transfer/abc",
            case_tracking_number="FOI-2026-0002",
            transfer_reason="Wrong jurisdiction",
        )
        assert ok is False


# ---------------------------------------------------------------------------
# send_contributor_reminder
# ---------------------------------------------------------------------------


class TestSendContributorReminder:
    def test_no_client_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
        mod = _import_fresh_module()
        svc = mod.EmailService()
        ok = svc.send_contributor_reminder(
            to_email="c@example.test",
            contributor_name="Charlie",
            upload_url="https://app/upload/xyz",
            case_tracking_number="FOI-2026-0001",
        )
        assert ok is False

    def test_success_2xx(self) -> None:
        svc, _mod, client = _make_svc_with_mocked_client()
        ok = svc.send_contributor_reminder(
            to_email="c@example.test",
            contributor_name="Charlie",
            upload_url="https://app/upload/xyz",
            case_tracking_number="FOI-2026-0001",
            org_name="Test Org",
            expires_days=7,
        )
        assert ok is True

    def test_non_2xx_returns_false(self) -> None:
        svc, _mod, client = _make_svc_with_mocked_client(status_code=429)
        ok = svc.send_contributor_reminder(
            to_email="c@example.test",
            contributor_name="Charlie",
            upload_url="https://app/upload/xyz",
            case_tracking_number="FOI-2026-0001",
        )
        assert ok is False

    def test_exception_returns_false(self) -> None:
        svc, _mod, client = _make_svc_with_mocked_client()
        client.send.side_effect = RuntimeError("boom")
        ok = svc.send_contributor_reminder(
            to_email="c@example.test",
            contributor_name="Charlie",
            upload_url="https://app/upload/xyz",
            case_tracking_number="FOI-2026-0001",
        )
        assert ok is False
