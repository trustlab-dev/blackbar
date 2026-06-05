"""Smoke tests for `src.core.telemetry`.

Target: ≥60% coverage. The module is mostly initialization wrappers
around external services (Sentry, OTel exporters, Prometheus). We mock
the SDK calls so no real network/auth is required.

Covers:
- `init_telemetry(app)` — runs without exceptions; sets service_info
- `_init_tracing` — no-op when ENVIRONMENT=='test' (the default in tests)
- `_init_sentry` — early return when SENTRY_DSN unset
- `_init_sentry` — sentry_sdk.init invoked when DSN provided (mocked)
- `_instrument_fastapi` — calls FastAPIInstrumentor.instrument_app
- `get_tracer` — returns a tracer, caches it
- `create_span` / `add_span_attributes` — exercise span helpers
- `record_exception` — span + Sentry capture (mocked)
- `set_sentry_user` / `set_sentry_context` / `add_sentry_breadcrumb` —
  early-return when DSN unset

Because module-level constants like `SENTRY_DSN` are captured at import
time, we monkeypatch the module's own attribute, not `os.environ`.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI


class TestInitTelemetry:
    def test_runs_without_exceptions_no_app(self, monkeypatch: pytest.MonkeyPatch):
        """In ENVIRONMENT=='test' with no DSN, init is a no-op."""
        from src.core import telemetry

        monkeypatch.setattr(telemetry, "SENTRY_DSN", "")
        monkeypatch.setattr(telemetry, "ENVIRONMENT", "test")
        telemetry.init_telemetry()  # no app

    def test_runs_without_exceptions_with_app(self, monkeypatch: pytest.MonkeyPatch):
        from src.core import telemetry

        monkeypatch.setattr(telemetry, "SENTRY_DSN", "")
        monkeypatch.setattr(telemetry, "ENVIRONMENT", "test")
        # FastAPIInstrumentor must not actually instrument (would mutate
        # global state). Mock the instrumentor inside the module.
        mock_instr = MagicMock()
        monkeypatch.setattr(telemetry, "FastAPIInstrumentor", mock_instr)

        app = FastAPI()
        telemetry.init_telemetry(app)
        mock_instr.instrument_app.assert_called_once_with(app, excluded_urls="health,metrics")

    def test_init_with_sentry_dsn_calls_sdk_init(self, monkeypatch: pytest.MonkeyPatch):
        from src.core import telemetry

        monkeypatch.setattr(telemetry, "SENTRY_DSN", "https://fake@sentry.io/1")
        monkeypatch.setattr(telemetry, "ENVIRONMENT", "test")
        with patch.object(telemetry.sentry_sdk, "init") as mock_init:
            telemetry.init_telemetry()
        mock_init.assert_called_once()
        # The init kwargs should include the DSN
        _, kwargs = mock_init.call_args
        assert kwargs["dsn"] == "https://fake@sentry.io/1"


class TestInitTracing:
    def test_skips_otlp_in_test_environment(self, monkeypatch: pytest.MonkeyPatch):
        """ENVIRONMENT='test' bypasses the OTLP exporter path."""
        from src.core import telemetry

        monkeypatch.setattr(telemetry, "ENVIRONMENT", "test")
        telemetry._init_tracing()
        assert telemetry._tracer is not None

    def test_otlp_init_failure_is_swallowed(self, monkeypatch: pytest.MonkeyPatch):
        """When OTLP exporter constructor raises, the exception is logged
        and swallowed (try/except in `_init_tracing`)."""
        from src.core import telemetry

        monkeypatch.setattr(telemetry, "ENVIRONMENT", "production")
        monkeypatch.setattr(telemetry, "OTLP_ENDPOINT", "http://nope:4317")

        def boom(*args, **kwargs):
            raise RuntimeError("exporter unreachable")

        monkeypatch.setattr(telemetry, "OTLPSpanExporter", boom)
        telemetry._init_tracing()  # should not raise


class TestInstrumentFastAPI:
    def test_failure_is_logged_and_swallowed(self, monkeypatch: pytest.MonkeyPatch):
        """`_instrument_fastapi` wraps the instrumentor call in try/except;
        an exception must not propagate."""
        from src.core import telemetry

        mock_instr = MagicMock()
        mock_instr.instrument_app.side_effect = RuntimeError("nope")
        monkeypatch.setattr(telemetry, "FastAPIInstrumentor", mock_instr)
        app = FastAPI()
        telemetry._instrument_fastapi(app)  # should not raise


class TestSentryBeforeSend:
    def test_filters_sensitive_headers(self):
        from src.core.telemetry import _sentry_before_send

        event = {
            "request": {
                "headers": {
                    "authorization": "Bearer secret",
                    "cookie": "session=abc",
                    "x-api-key": "topsecret",
                    "user-agent": "test",
                }
            }
        }
        result = _sentry_before_send(event, hint=None)
        assert result["request"]["headers"]["authorization"] == "[FILTERED]"
        assert result["request"]["headers"]["cookie"] == "[FILTERED]"
        assert result["request"]["headers"]["x-api-key"] == "[FILTERED]"
        # Non-sensitive header untouched
        assert result["request"]["headers"]["user-agent"] == "test"

    def test_no_request_headers_returns_event_unchanged(self):
        from src.core.telemetry import _sentry_before_send

        event = {"foo": "bar"}
        assert _sentry_before_send(event, hint=None) is event


class TestTracingHelpers:
    def test_get_tracer_returns_tracer(self):
        from src.core import telemetry

        t = telemetry.get_tracer()
        assert t is not None

    def test_get_tracer_initializes_when_unset(self, monkeypatch: pytest.MonkeyPatch):
        from src.core import telemetry

        monkeypatch.setattr(telemetry, "_tracer", None)
        t = telemetry.get_tracer()
        assert t is not None

    def test_create_span_with_attributes(self):
        from src.core.telemetry import create_span

        with create_span("test-span", {"key": "val", "skip": None}):
            pass  # span lifecycle exercised

    def test_create_span_without_attributes(self):
        from src.core.telemetry import create_span

        with create_span("no-attrs"):
            pass

    def test_add_span_attributes_outside_span(self):
        """Calling `add_span_attributes` outside an active span must not crash."""
        from src.core.telemetry import add_span_attributes

        add_span_attributes({"k": "v", "skip": None})


class TestRecordException:
    def test_records_in_span_and_sentry(self, monkeypatch: pytest.MonkeyPatch):
        from src.core import telemetry

        monkeypatch.setattr(telemetry, "SENTRY_DSN", "https://fake@sentry.io/1")
        mock_capture = MagicMock()
        monkeypatch.setattr(telemetry.sentry_sdk, "capture_exception", mock_capture)
        # push_scope is a context manager; preserve that protocol.
        scope = MagicMock()
        ctx_mgr = MagicMock()
        ctx_mgr.__enter__ = MagicMock(return_value=scope)
        ctx_mgr.__exit__ = MagicMock(return_value=False)
        monkeypatch.setattr(telemetry.sentry_sdk, "push_scope", MagicMock(return_value=ctx_mgr))

        err = ValueError("test-error")
        telemetry.record_exception(err, {"context": "test"})
        mock_capture.assert_called_once_with(err)
        scope.set_tag.assert_called_with("context", "test")

    def test_no_sentry_dsn_skips_capture(self, monkeypatch: pytest.MonkeyPatch):
        from src.core import telemetry

        monkeypatch.setattr(telemetry, "SENTRY_DSN", "")
        mock_capture = MagicMock()
        monkeypatch.setattr(telemetry.sentry_sdk, "capture_exception", mock_capture)
        telemetry.record_exception(ValueError("oh"))
        mock_capture.assert_not_called()

    def test_no_attributes_skips_set_tag(self, monkeypatch: pytest.MonkeyPatch):
        """attributes=None should skip the for-loop branch entirely."""
        from src.core import telemetry

        monkeypatch.setattr(telemetry, "SENTRY_DSN", "https://fake@sentry.io/1")
        scope = MagicMock()
        ctx_mgr = MagicMock()
        ctx_mgr.__enter__ = MagicMock(return_value=scope)
        ctx_mgr.__exit__ = MagicMock(return_value=False)
        monkeypatch.setattr(telemetry.sentry_sdk, "push_scope", MagicMock(return_value=ctx_mgr))
        monkeypatch.setattr(telemetry.sentry_sdk, "capture_exception", MagicMock())

        telemetry.record_exception(ValueError("oh"))
        scope.set_tag.assert_not_called()


class TestSentryContextHelpers:
    def test_set_sentry_user_skips_without_dsn(self, monkeypatch: pytest.MonkeyPatch):
        from src.core import telemetry

        monkeypatch.setattr(telemetry, "SENTRY_DSN", "")
        mock = MagicMock()
        monkeypatch.setattr(telemetry.sentry_sdk, "set_user", mock)
        telemetry.set_sentry_user("u-1")
        mock.assert_not_called()

    def test_set_sentry_user_calls_when_dsn_set(self, monkeypatch: pytest.MonkeyPatch):
        from src.core import telemetry

        monkeypatch.setattr(telemetry, "SENTRY_DSN", "https://fake@sentry.io/1")
        mock = MagicMock()
        monkeypatch.setattr(telemetry.sentry_sdk, "set_user", mock)
        telemetry.set_sentry_user("u-1", email="u@example.com")
        mock.assert_called_once_with({"id": "u-1", "email": "u@example.com"})

    def test_set_sentry_context_skips_without_dsn(self, monkeypatch: pytest.MonkeyPatch):
        from src.core import telemetry

        monkeypatch.setattr(telemetry, "SENTRY_DSN", "")
        mock = MagicMock()
        monkeypatch.setattr(telemetry.sentry_sdk, "set_context", mock)
        telemetry.set_sentry_context("k", {"v": 1})
        mock.assert_not_called()

    def test_set_sentry_context_calls_when_dsn_set(self, monkeypatch: pytest.MonkeyPatch):
        from src.core import telemetry

        monkeypatch.setattr(telemetry, "SENTRY_DSN", "https://fake@sentry.io/1")
        mock = MagicMock()
        monkeypatch.setattr(telemetry.sentry_sdk, "set_context", mock)
        telemetry.set_sentry_context("k", {"v": 1})
        mock.assert_called_once_with("k", {"v": 1})

    def test_add_sentry_breadcrumb_skips_without_dsn(self, monkeypatch: pytest.MonkeyPatch):
        from src.core import telemetry

        monkeypatch.setattr(telemetry, "SENTRY_DSN", "")
        mock = MagicMock()
        monkeypatch.setattr(telemetry.sentry_sdk, "add_breadcrumb", mock)
        telemetry.add_sentry_breadcrumb("msg")
        mock.assert_not_called()

    def test_add_sentry_breadcrumb_with_dsn_passes_data(self, monkeypatch: pytest.MonkeyPatch):
        from src.core import telemetry

        monkeypatch.setattr(telemetry, "SENTRY_DSN", "https://fake@sentry.io/1")
        mock = MagicMock()
        monkeypatch.setattr(telemetry.sentry_sdk, "add_breadcrumb", mock)
        telemetry.add_sentry_breadcrumb("msg", category="db", data={"x": 1})
        mock.assert_called_once()
        _, kwargs = mock.call_args
        assert kwargs["message"] == "msg"
        assert kwargs["category"] == "db"
        assert kwargs["data"] == {"x": 1}

    def test_add_sentry_breadcrumb_default_data_is_empty_dict(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        from src.core import telemetry

        monkeypatch.setattr(telemetry, "SENTRY_DSN", "https://fake@sentry.io/1")
        mock = MagicMock()
        monkeypatch.setattr(telemetry.sentry_sdk, "add_breadcrumb", mock)
        telemetry.add_sentry_breadcrumb("msg")
        _, kwargs = mock.call_args
        assert kwargs["data"] == {}
