"""Middleware that persists one audit record per inbound HTTP request.

Write is fire-and-forget (daemon thread) to avoid adding latency to the
request/response cycle. Request body is captured for POST/DELETE only,
capped at 64 KB, with sensitive fields redacted using the same rules as
logging_filters.py.
"""

import json
import logging
import threading
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

_BODY_CAPTURE_METHODS = {"POST", "DELETE"}
_MAX_BODY_BYTES = 64 * 1024  # 64 KB cap


def _redact_body(raw_bytes: bytes) -> str | None:
    """Parse JSON body, redact sensitive keys, return JSON string or None."""
    from app.core.logging_filters import _is_sensitive_key, _redact_string

    if not raw_bytes:
        return None
    try:
        data = json.loads(raw_bytes[:_MAX_BODY_BYTES])
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    def _scrub(obj: object) -> object:
        if isinstance(obj, dict):
            return {
                k: "[REDACTED]" if _is_sensitive_key(k) else _scrub(v)
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [_scrub(item) for item in obj]
        if isinstance(obj, str):
            return _redact_string(obj)
        return obj

    return json.dumps(_scrub(data))


def _persist_audit(
    *,
    request_id: str | None,
    timestamp: datetime,
    method: str,
    path: str,
    status_code: int | None,
    api_key_id: str | None,
    api_key_role: str | None,
    client_ip: str | None,
    user_agent: str | None,
    request_body: str | None,
) -> None:
    """Write one AuditLogRecord to the DB. Called on a daemon thread."""
    try:
        from app.db.database import SessionLocal
        from app.db.models import AuditLogRecord

        db = SessionLocal()
        try:
            record = AuditLogRecord(
                request_id=request_id,
                timestamp=timestamp,
                method=method,
                path=path,
                status_code=status_code,
                api_key_id=api_key_id,
                api_key_role=api_key_role,
                client_ip=client_ip,
                user_agent=user_agent,
                request_body=request_body,
            )
            db.add(record)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
    except Exception:
        pass  # Never let audit failures surface to the caller


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Persists one audit record per request after the response is sent."""

    async def dispatch(self, request: Request, call_next) -> Response:
        timestamp = datetime.now(timezone.utc).replace(tzinfo=None)

        # Capture body before routing consumes it (POST/DELETE only).
        # Starlette caches result of await request.body() in request._body,
        # so downstream route handlers read from the cache — body is not lost.
        raw_body: bytes = b""
        if request.method in _BODY_CAPTURE_METHODS:
            raw_body = await request.body()

        response = await call_next(request)

        # Depends(verify_api_key) has now run — auth state is populated
        api_key_id = getattr(request.state, "api_key_id", None)
        api_key_role = getattr(request.state, "api_key_role", None)
        request_id = getattr(request.state, "request_id", None)
        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")

        redacted_body = _redact_body(raw_body) if raw_body else None

        threading.Thread(
            target=_persist_audit,
            kwargs=dict(
                request_id=request_id,
                timestamp=timestamp,
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                api_key_id=api_key_id,
                api_key_role=api_key_role,
                client_ip=client_ip,
                user_agent=user_agent,
                request_body=redacted_body,
            ),
            daemon=True,
        ).start()

        return response
