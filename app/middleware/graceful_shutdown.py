"""Graceful shutdown middleware: tracks in-flight requests and drains them on SIGTERM.

On SIGTERM (e.g. ``docker stop``, Kubernetes pod eviction):
  1. The shutdown flag is set — new requests receive 503 Service Unavailable.
  2. The signal handler waits up to GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS for all
     in-flight requests to finish.
  3. The process then exits cleanly, preventing half-written DB rows and stuck runs.

Usage: add to app in main.py BEFORE other middleware so it sees every request.
"""

import asyncio
import logging
import os
import signal

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# How long (seconds) to wait for in-flight requests before forcing exit
GRACEFUL_SHUTDOWN_TIMEOUT = int(os.getenv("GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS", "30"))


class GracefulShutdownMiddleware(BaseHTTPMiddleware):
    """Tracks in-flight requests and rejects new ones after SIGTERM."""

    def __init__(self, app, shutdown_event: asyncio.Event | None = None):
        super().__init__(app)
        self._in_flight: int = 0
        self._shutdown_event: asyncio.Event = shutdown_event or asyncio.Event()
        self._register_signal_handlers()

    def _register_signal_handlers(self) -> None:
        """Register SIGTERM handler (Unix only; Windows ignores SIGTERM)."""
        try:
            loop = asyncio.get_event_loop()
            loop.add_signal_handler(signal.SIGTERM, self._handle_sigterm)
            logger.debug("graceful_shutdown: SIGTERM handler registered")
        except (NotImplementedError, RuntimeError):
            # Windows or no running event loop at import time — skip
            logger.debug("graceful_shutdown: SIGTERM handler not available on this platform")

    def _handle_sigterm(self) -> None:
        logger.info(
            "graceful_shutdown: SIGTERM received — draining %d in-flight request(s) "
            "(timeout: %ds)",
            self._in_flight,
            GRACEFUL_SHUTDOWN_TIMEOUT,
        )
        self._shutdown_event.set()
        asyncio.ensure_future(self._wait_and_exit())

    async def _wait_and_exit(self) -> None:
        """Wait for in-flight requests to finish, then allow uvicorn to shut down."""
        deadline = GRACEFUL_SHUTDOWN_TIMEOUT
        while self._in_flight > 0 and deadline > 0:
            await asyncio.sleep(1)
            deadline -= 1
            if self._in_flight > 0:
                logger.info("graceful_shutdown: waiting — %d request(s) still in flight", self._in_flight)

        if self._in_flight > 0:
            logger.warning(
                "graceful_shutdown: timeout reached with %d request(s) still in flight — exiting",
                self._in_flight,
            )
        else:
            logger.info("graceful_shutdown: all requests drained — ready for shutdown")

    async def dispatch(self, request: Request, call_next):
        if self._shutdown_event.is_set():
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "SERVICE_SHUTTING_DOWN",
                        "message": "The server is shutting down. Please retry your request.",
                        "recovery_hint": "Wait a few seconds and retry. If the problem persists, contact support.",
                    }
                },
                headers={"Retry-After": "10"},
            )

        self._in_flight += 1
        try:
            response = await call_next(request)
            return response
        finally:
            self._in_flight -= 1
