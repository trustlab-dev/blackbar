"""
Structured Logging Configuration for BlackBar

Provides JSON-formatted structured logging with:
- Correlation ID injection
- Log level filtering
- Consistent format for log aggregation (Loki)
"""

import logging
import os
import sys

import structlog
from structlog.types import Processor

from src.core.correlation import get_correlation_id

# Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = os.getenv("LOG_FORMAT", "json")  # json or console
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
SERVICE_NAME = "blackbar-backend"


def add_correlation_id(logger, method_name, event_dict):
    """Add correlation ID to log entries."""
    correlation_id = get_correlation_id()
    if correlation_id:
        event_dict["correlation_id"] = correlation_id
    return event_dict


def add_service_context(logger, method_name, event_dict):
    """Add service context to log entries."""
    event_dict["service"] = SERVICE_NAME
    event_dict["environment"] = ENVIRONMENT
    return event_dict


def filter_sensitive_data(logger, method_name, event_dict):
    """Filter sensitive data from logs."""
    sensitive_keys = {
        "password",
        "token",
        "api_key",
        "secret",
        "authorization",
        "cookie",
        "session",
        "credit_card",
        "ssn",
        "email",
    }

    def _filter_dict(d):
        if not isinstance(d, dict):
            return d
        return {
            k: "[FILTERED]" if any(s in k.lower() for s in sensitive_keys) else _filter_dict(v)
            for k, v in d.items()
        }

    return _filter_dict(event_dict)


def configure_logging():
    """
    Configure structured logging for the application.
    Call this during application startup.
    """
    # Determine processors based on format
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        add_correlation_id,
        add_service_context,
        filter_sensitive_data,
    ]

    if LOG_FORMAT == "json":
        # JSON format for production/log aggregation
        shared_processors.append(structlog.processors.format_exc_info)
        renderer = structlog.processors.JSONRenderer()
    else:
        # Console format for development
        shared_processors.append(structlog.dev.set_exc_info)
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(getattr(logging, LOG_LEVEL))

    # Reduce noise from third-party libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("opentelemetry").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    return structlog.get_logger()


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """
    Get a structured logger instance.

    Usage:
        logger = get_logger(__name__)
        logger.info("Processing document", document_id=doc_id, case_id=case_id)
    """
    return structlog.get_logger(name)


# Context manager for adding temporary context
class LogContext:
    """
    Context manager for adding temporary logging context.

    Usage:
        with LogContext(case_id="abc", user_id="xyz"):
            logger.info("Processing request")
    """

    def __init__(self, **kwargs):
        self.context = kwargs
        self._token = None

    def __enter__(self):
        self._token = structlog.contextvars.bind_contextvars(**self.context)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._token:
            structlog.contextvars.unbind_contextvars(*self.context.keys())
        return False


def bind_context(**kwargs):
    """
    Bind context variables for all subsequent log calls in this context.

    Usage:
        bind_context(case_id="abc", user_id="xyz")
        logger.info("This will include case_id and user_id")
    """
    structlog.contextvars.bind_contextvars(**kwargs)


def unbind_context(*keys):
    """Remove context variables."""
    structlog.contextvars.unbind_contextvars(*keys)


def clear_context():
    """Clear all context variables."""
    structlog.contextvars.clear_contextvars()
