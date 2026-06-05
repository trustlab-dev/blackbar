"""Tests for ``src.utils.welcome_email_service``.

``WelcomeEmailService`` covers two flows:

1. ``send_owner_welcome`` — sends an activation link to the
   organization owner. Uses SendGrid directly (does NOT delegate to
   the provided ``email_service`` instance); the constructor argument
   is only stored for use by ``send_public_request_confirmation``.

2. ``send_public_request_confirmation`` — confirms a public FOI
   request submission. Delegates to ``email_service.send_email``.

Plus three token helpers (generate / hash / verify) used by the
activation pipeline.

Some flows were partially exercised by Sub-phase 2.1.B magic-link
service tests; this file fills gaps to ≥80% line + branch.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _import_fresh_module():
    import importlib

    import src.utils.welcome_email_service as mod

    return importlib.reload(mod)


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------


class TestTokenHelpers:
    def test_generate_activation_token_returns_url_safe_string(self) -> None:
        mod = _import_fresh_module()
        svc = mod.WelcomeEmailService(email_service=None)
        token = svc.generate_activation_token()
        assert isinstance(token, str)
        # token_urlsafe(32) -> ~43 base64-url chars
        assert len(token) > 40
        # URL-safe alphabet only
        for ch in token:
            assert ch.isalnum() or ch in "-_"

    def test_generate_activation_token_is_unique(self) -> None:
        mod = _import_fresh_module()
        svc = mod.WelcomeEmailService(email_service=None)
        a = svc.generate_activation_token()
        b = svc.generate_activation_token()
        assert a != b

    def test_hash_and_verify_token_roundtrip(self) -> None:
        mod = _import_fresh_module()
        svc = mod.WelcomeEmailService(email_service=None)
        token = svc.generate_activation_token()
        hashed = svc.hash_token(token)
        # bcrypt hashes always start with $2 and are NOT the original token
        assert hashed != token
        assert hashed.startswith("$2")
        assert svc.verify_token(token, hashed) is True

    def test_verify_token_rejects_wrong_token(self) -> None:
        mod = _import_fresh_module()
        svc = mod.WelcomeEmailService(email_service=None)
        token = svc.generate_activation_token()
        hashed = svc.hash_token(token)
        assert svc.verify_token("not-the-token", hashed) is False

    def test_verify_token_returns_false_on_exception(self) -> None:
        mod = _import_fresh_module()
        svc = mod.WelcomeEmailService(email_service=None)
        # Invalid hash format -> bcrypt raises -> caught -> False
        assert svc.verify_token("any-token", "not-a-bcrypt-hash") is False

    def test_token_expiration_hours_is_48(self) -> None:
        """Pinned: 48 hours per Sub-phase 2.1.B activation service tests."""
        mod = _import_fresh_module()
        svc = mod.WelcomeEmailService(email_service=None)
        assert svc.token_expiration_hours == 48


# ---------------------------------------------------------------------------
# send_owner_welcome
# ---------------------------------------------------------------------------


class TestSendOwnerWelcome:
    def test_no_api_key_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
        mod = _import_fresh_module()
        svc = mod.WelcomeEmailService(email_service=None)
        result = svc.send_owner_welcome(
            owner_email="owner@example.test",
            owner_name="Owner",
            org_name="Test Org",
            activation_token="abc123",
        )
        assert result is False

    def test_no_api_key_dev_mode_log_outside_production(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If ENVIRONMENT != 'production', the dev-mode log branch fires."""
        monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "development")
        mod = _import_fresh_module()
        svc = mod.WelcomeEmailService(email_service=None)
        assert (
            svc.send_owner_welcome(
                owner_email="owner@example.test",
                owner_name="Owner",
                org_name="Test Org",
                activation_token="abc123",
            )
            is False
        )

    def test_no_api_key_production_skips_dev_log(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "production")
        mod = _import_fresh_module()
        svc = mod.WelcomeEmailService(email_service=None)
        assert (
            svc.send_owner_welcome(
                owner_email="owner@example.test",
                owner_name="Owner",
                org_name="Test Org",
                activation_token="abc123",
            )
            is False
        )

    def test_success_2xx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SENDGRID_API_KEY", "SG.test")
        monkeypatch.setenv("FRONTEND_URL", "https://app.example.test")
        mod = _import_fresh_module()
        svc = mod.WelcomeEmailService(email_service=None)

        client_instance = MagicMock()
        response = MagicMock()
        response.status_code = 202
        response.body = b""
        client_instance.send.return_value = response

        # SendGridAPIClient is imported INSIDE send_owner_welcome via
        # `from sendgrid import SendGridAPIClient`, so we patch the symbol
        # on the `sendgrid` module itself.
        with patch("sendgrid.SendGridAPIClient", return_value=client_instance):
            ok = svc.send_owner_welcome(
                owner_email="owner@example.test",
                owner_name="Owner",
                org_name="Test Org",
                activation_token="token-xyz",
            )

        assert ok is True
        client_instance.send.assert_called_once()

    def test_non_2xx_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SENDGRID_API_KEY", "SG.test")
        mod = _import_fresh_module()
        svc = mod.WelcomeEmailService(email_service=None)

        client_instance = MagicMock()
        response = MagicMock()
        response.status_code = 500
        response.body = b"server error"
        client_instance.send.return_value = response

        with patch("sendgrid.SendGridAPIClient", return_value=client_instance):
            ok = svc.send_owner_welcome(
                owner_email="owner@example.test",
                owner_name="Owner",
                org_name="Test Org",
                activation_token="token-xyz",
            )

        assert ok is False

    def test_exception_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SENDGRID_API_KEY", "SG.test")
        mod = _import_fresh_module()
        svc = mod.WelcomeEmailService(email_service=None)

        with patch("sendgrid.SendGridAPIClient", side_effect=RuntimeError("boom")):
            ok = svc.send_owner_welcome(
                owner_email="owner@example.test",
                owner_name="Owner",
                org_name="Test Org",
                activation_token="token-xyz",
            )

        assert ok is False


class TestOwnerWelcomeTemplates:
    def test_html_template_includes_org_name_and_url(self) -> None:
        mod = _import_fresh_module()
        svc = mod.WelcomeEmailService(email_service=None)
        html = svc._build_html_template(
            owner_name="Alice",
            org_name="Acme Org",
            activation_url="https://app/activate?token=x&email=y",
            expires_hours=48,
        )
        assert "Acme Org" in html
        assert "Alice" in html
        assert (
            "https://app/activate?token=x&amp;email=y" in html
            or "https://app/activate?token=x&email=y" in html
        )
        assert "48 hours" in html
        assert "<!DOCTYPE html>" in html

    def test_text_template_includes_org_name_and_url(self) -> None:
        mod = _import_fresh_module()
        svc = mod.WelcomeEmailService(email_service=None)
        text = svc._build_text_template(
            owner_name="Alice",
            org_name="Acme Org",
            activation_url="https://app/activate?token=x&email=y",
            expires_hours=48,
        )
        assert "Acme Org" in text
        assert "Alice" in text
        assert "https://app/activate?token=x&email=y" in text
        assert "48 hours" in text


# ---------------------------------------------------------------------------
# send_public_request_confirmation
# ---------------------------------------------------------------------------


class TestSendPublicRequestConfirmation:
    """This flow delegates to ``email_service.send_email`` (NOT the
    SendGrid client directly).
    """

    def test_success_2xx(self) -> None:
        mod = _import_fresh_module()
        email_svc = MagicMock()
        response = MagicMock()
        response.status_code = 200
        email_svc.send_email.return_value = response

        svc = mod.WelcomeEmailService(email_service=email_svc)
        ok = svc.send_public_request_confirmation(
            requester_email="requester@example.test",
            requester_name="Requester",
            tracking_number="FOI-2026-0099",
            request_title="Records about X",
            org_name="Test Org",
            contact_email="foi@example.test",
        )
        assert ok is True
        email_svc.send_email.assert_called_once()
        call_kwargs = email_svc.send_email.call_args.kwargs
        assert call_kwargs["to"] == "requester@example.test"
        assert "FOI-2026-0099" in call_kwargs["subject"]
        assert "Records about X" in call_kwargs["html_content"]
        assert "Records about X" in call_kwargs["text_content"]
        assert "foi@example.test" in call_kwargs["html_content"]

    def test_success_without_contact_email(self) -> None:
        """The contact-email block is conditional on contact_email being
        truthy — the no-contact branch must also fire."""
        mod = _import_fresh_module()
        email_svc = MagicMock()
        response = MagicMock()
        response.status_code = 202
        email_svc.send_email.return_value = response

        svc = mod.WelcomeEmailService(email_service=email_svc)
        ok = svc.send_public_request_confirmation(
            requester_email="r@example.test",
            requester_name="R",
            tracking_number="FOI-2026-0100",
            request_title="Records about Y",
            org_name="Test Org",
            contact_email=None,
        )
        assert ok is True
        # Neither HTML nor text should contain a mailto link
        call_kwargs = email_svc.send_email.call_args.kwargs
        assert "mailto:" not in call_kwargs["html_content"]

    def test_non_2xx_returns_false(self) -> None:
        mod = _import_fresh_module()
        email_svc = MagicMock()
        response = MagicMock()
        response.status_code = 500
        email_svc.send_email.return_value = response

        svc = mod.WelcomeEmailService(email_service=email_svc)
        ok = svc.send_public_request_confirmation(
            requester_email="r@example.test",
            requester_name="R",
            tracking_number="FOI-2026-0101",
            request_title="X",
            org_name="Test Org",
        )
        assert ok is False

    def test_exception_returns_false(self) -> None:
        mod = _import_fresh_module()
        email_svc = MagicMock()
        email_svc.send_email.side_effect = RuntimeError("network")

        svc = mod.WelcomeEmailService(email_service=email_svc)
        ok = svc.send_public_request_confirmation(
            requester_email="r@example.test",
            requester_name="R",
            tracking_number="FOI-2026-0102",
            request_title="X",
            org_name="Test Org",
        )
        assert ok is False


class TestPublicRequestConfirmationTemplates:
    def test_html_includes_tracking_and_request_title(self) -> None:
        mod = _import_fresh_module()
        svc = mod.WelcomeEmailService(email_service=None)
        html = svc._build_confirmation_html(
            requester_name="Alice",
            tracking_number="FOI-2026-0001",
            request_title="Records about contracts",
            org_name="Acme Org",
            tracking_url="https://app/track/FOI-2026-0001",
            contact_email="foi@example.test",
        )
        assert "FOI-2026-0001" in html
        assert "Records about contracts" in html
        assert "Acme Org" in html
        assert "Alice" in html
        assert "foi@example.test" in html
        assert "https://app/track/FOI-2026-0001" in html

    def test_html_without_contact_email_omits_contact_section(self) -> None:
        mod = _import_fresh_module()
        svc = mod.WelcomeEmailService(email_service=None)
        html = svc._build_confirmation_html(
            requester_name="Alice",
            tracking_number="FOI-2026-0001",
            request_title="X",
            org_name="Acme Org",
            tracking_url="https://app/track/FOI-2026-0001",
            contact_email=None,
        )
        assert "mailto:" not in html

    def test_text_includes_tracking_and_request_title(self) -> None:
        mod = _import_fresh_module()
        svc = mod.WelcomeEmailService(email_service=None)
        text = svc._build_confirmation_text(
            requester_name="Alice",
            tracking_number="FOI-2026-0001",
            request_title="Records about contracts",
            org_name="Acme Org",
            tracking_url="https://app/track/FOI-2026-0001",
            contact_email="foi@example.test",
        )
        assert "FOI-2026-0001" in text
        assert "Records about contracts" in text
        assert "Acme Org" in text
        assert "foi@example.test" in text

    def test_text_without_contact_email_omits_contact_section(self) -> None:
        mod = _import_fresh_module()
        svc = mod.WelcomeEmailService(email_service=None)
        text = svc._build_confirmation_text(
            requester_name="Alice",
            tracking_number="FOI-2026-0001",
            request_title="X",
            org_name="Acme Org",
            tracking_url="https://app/track/FOI-2026-0001",
            contact_email=None,
        )
        # No contact line present
        assert "contact us at" not in text
