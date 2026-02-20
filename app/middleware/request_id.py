"""Middleware to propagate X-Request-ID through the request lifecycle."""

import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Module-level ContextVar so background tasks can read the current request ID
request_id_var: ContextVar[str] = ContextVar("request_id", default="")


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Reads or generates an X-Request-ID for every request.
    Sets it on request.state.request_id and echoes it back in the response header.
    Also stores it in a ContextVar so background tasks launched during the request
    can include it in log messages.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = req_id
        token = request_id_var.set(req_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = req_id
            return response
        finally:
            request_id_var.reset(token)
