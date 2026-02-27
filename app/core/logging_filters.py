"""Logging filter that redacts sensitive field values before they reach any log sink.

The filter operates on the LogRecord's message string and on ``extra`` keyword
fields injected via ``logger.info(..., extra={...})``.  It replaces the VALUE of
any key that matches the sensitive-name list with ``[REDACTED]``.

Usage::

    import logging
    from app.core.logging_filters import SensitiveDataFilter

    logging.getLogger().addFilter(SensitiveDataFilter())
"""

import logging
import re
from typing import ClassVar

# Keys whose values are always redacted (case-insensitive substring match on field name)
_SENSITIVE_FIELD_NAMES: tuple[str, ...] = (
    "api_key",
    "apikey",
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "auth",
    "credential",
    "private_key",
    "access_key",
    "aws_secret",
    "openai_api_key",
    "bearer",
)

# Regex patterns that match sensitive data embedded in log *message strings*
_SENSITIVE_PATTERNS: list[re.Pattern] = [
    # HTTP Authorization header value
    re.compile(r"(Authorization:\s*)(Bearer\s+\S+)", re.IGNORECASE),
    # X-API-Key header value in log lines
    re.compile(r"(X-API-Key:\s*)(\S+)", re.IGNORECASE),
    # Key-value pairs like api_key=abc123 or "api_key": "abc123"
    re.compile(
        r'("?(?:api_key|apikey|password|secret|token|authorization)"?\s*[=:]\s*["\']?)([^"\'&\s,}{]+)',
        re.IGNORECASE,
    ),
    # Raw bearer tokens (orc_...) in messages — matches the KEY_PREFIX from api_keys.py
    re.compile(r"\borc_[A-Za-z0-9_\-]{10,}\b"),
]


def _redact_string(value: str) -> str:
    """Apply all pattern-based redactions to a string."""
    for pattern in _SENSITIVE_PATTERNS:
        if pattern.groups == 0:
            value = pattern.sub("[REDACTED]", value)
        else:
            # Replace only the capturing group that holds the secret value (group 2)
            value = pattern.sub(lambda m: m.group(1) + "[REDACTED]" if m.lastindex and m.lastindex >= 2 else "[REDACTED]", value)
    return value


def _is_sensitive_key(key: str) -> bool:
    key_lower = key.lower()
    return any(name in key_lower for name in _SENSITIVE_FIELD_NAMES)


class SensitiveDataFilter(logging.Filter):
    """Logging filter that scrubs secrets from log records before emission.

    Attach to the root logger or specific handlers::

        logging.getLogger().addFilter(SensitiveDataFilter())
    """

    # Fields on LogRecord that hold the formatted message
    _MESSAGE_ATTRS: ClassVar[tuple[str, ...]] = ("msg", "message")

    def filter(self, record: logging.LogRecord) -> bool:
        # Redact the message string
        if isinstance(record.msg, str):
            record.msg = _redact_string(record.msg)

        # Redact positional args that will be interpolated into msg
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: "[REDACTED]" if _is_sensitive_key(k) else (
                        _redact_string(v) if isinstance(v, str) else v
                    )
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    _redact_string(a) if isinstance(a, str) else a for a in record.args
                )

        # Redact extra fields injected via logger.info(..., extra={...})
        for attr in list(vars(record).keys()):
            if attr.startswith("_") or attr in logging.LogRecord.__dict__:
                continue
            if _is_sensitive_key(attr):
                setattr(record, attr, "[REDACTED]")
            elif isinstance(getattr(record, attr), str):
                setattr(record, attr, _redact_string(getattr(record, attr)))

        return True  # Never suppress — only mutate
