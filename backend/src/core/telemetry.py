"""
Telemetry and Observability Module for BlackBar

This module provides:
- OpenTelemetry instrumentation for traces
- Prometheus metrics for monitoring
- Structured logging with correlation IDs
- Sentry error tracking integration
"""

import logging
import os
from contextlib import contextmanager

# Sentry
import sentry_sdk

# OpenTelemetry imports
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# Prometheus metrics
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    Info,
)
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

# Configuration
OTLP_ENDPOINT = os.getenv("OTLP_ENDPOINT", "http://tempo:4317")
SENTRY_DSN = os.getenv("SENTRY_DSN", "")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
SERVICE_NAME_VALUE = "blackbar-backend"
SERVICE_VERSION_VALUE = os.getenv("SERVICE_VERSION", "1.0.0")

# Global tracer
_tracer: trace.Tracer | None = None


# =============================================================================
# Prometheus Metrics Definitions
# =============================================================================

# HTTP Request metrics
http_requests_total = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "endpoint", "status"]
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    buckets=(0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0),
)

http_requests_in_progress = Gauge(
    "http_requests_in_progress", "Number of HTTP requests in progress", ["method", "endpoint"]
)

# Database metrics
db_operation_duration_seconds = Histogram(
    "db_operation_duration_seconds",
    "Database operation duration in seconds",
    ["operation", "collection"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)

db_operations_total = Counter(
    "db_operations_total", "Total database operations", ["operation", "collection", "status"]
)

# Authentication metrics
auth_attempts_total = Counter(
    "auth_attempts_total", "Total authentication attempts", ["status", "method"]
)

auth_failures_total = Counter(
    "auth_failures_total", "Total authentication failures", ["reason", "ip_address"]
)

# LLM/AI metrics
llm_requests_total = Counter(
    "llm_requests_total", "Total LLM API requests", ["provider", "model", "operation", "status"]
)

llm_request_duration_seconds = Histogram(
    "llm_request_duration_seconds",
    "LLM request duration in seconds",
    ["provider", "model", "operation"],
    buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 15.0, 30.0, 60.0, 120.0),
)

# type label distinguishes input vs output tokens.
llm_tokens_total = Counter(
    "llm_tokens_total", "Total LLM tokens used", ["provider", "model", "type"]
)

llm_cost_dollars_total = Counter(
    "llm_cost_dollars_total", "Total LLM cost in dollars", ["provider", "model"]
)

# Business metrics
cases_created_total = Counter("cases_created_total", "Total cases created", [])

documents_processed_total = Counter(
    "documents_processed_total",
    "Total documents processed",
    ["operation"],  # operation: upload, redact, export
)

ai_suggestions_total = Counter("ai_suggestions_total", "Total AI suggestions generated", [])

ai_suggestions_accepted_total = Counter(
    "ai_suggestions_accepted_total", "Total AI suggestions accepted by users", []
)

# Background job metrics
background_jobs_total = Counter(
    "background_jobs_total", "Total background jobs", ["job_type", "status"]
)

background_job_duration_seconds = Histogram(
    "background_job_duration_seconds",
    "Background job duration in seconds",
    ["job_type"],
    buckets=(0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 600.0),
)

background_job_queue_depth = Gauge(
    "background_job_queue_depth", "Number of jobs in queue", ["queue_name"]
)

# Service info
service_info = Info("blackbar_service", "BlackBar service information")


# =============================================================================
# Initialization Functions
# =============================================================================


def init_telemetry(app=None):
    """
    Initialize all telemetry systems.
    Call this during application startup.
    """
    global _tracer

    # Set service info
    service_info.info(
        {
            "version": SERVICE_VERSION_VALUE,
            "environment": ENVIRONMENT,
            "service": SERVICE_NAME_VALUE,
        }
    )

    # Initialize OpenTelemetry tracing
    _init_tracing()

    # Initialize Sentry (if DSN provided)
    _init_sentry()

    # Instrument FastAPI (if app provided)
    if app:
        _instrument_fastapi(app)

    logging.info(f"Telemetry initialized for {SERVICE_NAME_VALUE} v{SERVICE_VERSION_VALUE}")


def _init_tracing():
    """Initialize OpenTelemetry tracing."""
    global _tracer

    resource = Resource.create(
        {
            SERVICE_NAME: SERVICE_NAME_VALUE,
            SERVICE_VERSION: SERVICE_VERSION_VALUE,
            "deployment.environment": ENVIRONMENT,
        }
    )

    provider = TracerProvider(resource=resource)

    # Only add OTLP exporter if endpoint is configured and not in test mode
    if OTLP_ENDPOINT and ENVIRONMENT != "test":
        try:
            otlp_exporter = OTLPSpanExporter(endpoint=OTLP_ENDPOINT, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
            logging.info(f"OTLP tracing enabled, exporting to {OTLP_ENDPOINT}")
        except Exception as e:
            logging.warning(f"Failed to initialize OTLP exporter: {e}")

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(SERVICE_NAME_VALUE, SERVICE_VERSION_VALUE)


def _init_sentry():
    """Initialize Sentry error tracking."""
    if not SENTRY_DSN:
        logging.info("Sentry DSN not configured, error tracking disabled")
        return

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=ENVIRONMENT,
        release=f"{SERVICE_NAME_VALUE}@{SERVICE_VERSION_VALUE}",
        traces_sample_rate=0.1 if ENVIRONMENT == "production" else 1.0,
        profiles_sample_rate=0.1 if ENVIRONMENT == "production" else 1.0,
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            StarletteIntegration(transaction_style="endpoint"),
        ],
        # Don't send PII
        send_default_pii=False,
        # Attach request data
        request_bodies="medium",
        # Filter sensitive data
        before_send=_sentry_before_send,
    )
    logging.info("Sentry error tracking initialized")


def _sentry_before_send(event, hint):
    """Filter sensitive data before sending to Sentry."""
    # Remove sensitive headers
    if "request" in event and "headers" in event["request"]:
        headers = event["request"]["headers"]
        sensitive_headers = ["authorization", "cookie", "x-api-key"]
        for header in sensitive_headers:
            if header in headers:
                headers[header] = "[FILTERED]"

    return event


def _instrument_fastapi(app):
    """Instrument FastAPI with OpenTelemetry."""
    try:
        FastAPIInstrumentor.instrument_app(
            app,
            excluded_urls="health,metrics",
        )
        logging.info("FastAPI instrumentation enabled")
    except Exception as e:
        logging.warning(f"Failed to instrument FastAPI: {e}")


# =============================================================================
# Tracing Utilities
# =============================================================================


def get_tracer() -> trace.Tracer:
    """Get the global tracer instance."""
    global _tracer
    if _tracer is None:
        _tracer = trace.get_tracer(SERVICE_NAME_VALUE, SERVICE_VERSION_VALUE)
    return _tracer


@contextmanager
def create_span(name: str, attributes: dict = None):
    """
    Create a new trace span.

    Usage:
        with create_span("process_document", {"document_id": doc_id}):
            # do work
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                if value is not None:
                    span.set_attribute(key, str(value))
        yield span


def add_span_attributes(attributes: dict):
    """Add attributes to the current span."""
    span = trace.get_current_span()
    if span:
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, str(value))


def record_exception(exception: Exception, attributes: dict = None):
    """Record an exception in the current span and Sentry."""
    span = trace.get_current_span()
    if span:
        span.record_exception(exception)
        span.set_status(trace.Status(trace.StatusCode.ERROR, str(exception)))
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, str(value))

    # Also capture in Sentry
    if SENTRY_DSN:
        with sentry_sdk.push_scope() as scope:
            if attributes:
                for key, value in attributes.items():
                    scope.set_tag(key, str(value))
            sentry_sdk.capture_exception(exception)


# =============================================================================
# Sentry Context Utilities
# =============================================================================


def set_sentry_user(user_id: str, email: str = None):
    """Set user context for Sentry."""
    if not SENTRY_DSN:
        return

    sentry_sdk.set_user(
        {
            "id": user_id,
            "email": email,
        }
    )


def set_sentry_context(name: str, data: dict):
    """Set additional context for Sentry."""
    if not SENTRY_DSN:
        return

    sentry_sdk.set_context(name, data)


def add_sentry_breadcrumb(message: str, category: str = "info", data: dict = None):
    """Add a breadcrumb for Sentry."""
    if not SENTRY_DSN:
        return

    sentry_sdk.add_breadcrumb(message=message, category=category, data=data or {}, level="info")
