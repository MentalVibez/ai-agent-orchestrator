"""Centralized logging configuration.

When LOG_FORMAT=json (default in production), emits structured JSON records with
consistent fields that log aggregators (ELK, Datadog, CloudWatch) can parse without
regex.

When LOG_FORMAT=text (default when DEBUG=true), falls back to human-readable format
for local development.

The SensitiveDataFilter is always attached to the root logger regardless of format.
"""

import logging
import os
import sys


def _build_handler() -> logging.Handler:
    """Return a StreamHandler with the appropriate formatter."""
    log_format = os.getenv("LOG_FORMAT", "json" if os.getenv("DEBUG", "false").lower() != "true" else "text")

    handler = logging.StreamHandler(sys.stdout)

    if log_format == "json":
        try:
            from pythonjsonlogger.jsonlogger import JsonFormatter

            formatter = JsonFormatter(
                fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
                rename_fields={"levelname": "level", "asctime": "timestamp"},
            )
        except ImportError:
            # python-json-logger not installed — fall back to text gracefully
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

    handler.setFormatter(formatter)
    return handler


def configure_logging(log_level: str = "INFO") -> None:
    """Configure root logger with structured output and secrets redaction.

    Call once at application startup (in main.py lifespan or module level).
    """
    from app.core.logging_filters import SensitiveDataFilter

    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Remove any existing handlers to avoid duplicate output
    root.handlers.clear()

    handler = _build_handler()
    handler.addFilter(SensitiveDataFilter())
    root.addHandler(handler)

    # Reduce noise from third-party libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
