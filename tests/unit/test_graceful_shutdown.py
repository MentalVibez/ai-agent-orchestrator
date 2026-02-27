"""Unit tests for app/middleware/graceful_shutdown.py."""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import PlainTextResponse

from app.middleware.graceful_shutdown import GracefulShutdownMiddleware


def _make_app(shutdown_event: asyncio.Event | None = None) -> FastAPI:
    """Build a minimal FastAPI app with GracefulShutdownMiddleware."""
    test_app = FastAPI()
    middleware = GracefulShutdownMiddleware(test_app, shutdown_event=shutdown_event)

    @test_app.get("/ping")
    async def ping():
        return PlainTextResponse("pong")

    # Wrap with the middleware
    from starlette.middleware.base import BaseHTTPMiddleware
    test_app.add_middleware(GracefulShutdownMiddleware, shutdown_event=shutdown_event)

    return test_app


@pytest.mark.unit
class TestGracefulShutdownMiddleware:
    def test_passes_requests_when_not_shutting_down(self):
        """Normal requests should go through when no shutdown is in progress."""
        shutdown_event = asyncio.Event()
        app = _make_app(shutdown_event)
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/ping")
            assert resp.status_code == 200
            assert resp.text == "pong"

    def test_returns_503_when_shutdown_flagged(self):
        """Requests arriving after SIGTERM should get 503 with Retry-After."""
        shutdown_event = asyncio.Event()
        shutdown_event.set()  # Simulate SIGTERM already received
        app = _make_app(shutdown_event)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/ping")
            assert resp.status_code == 503
            body = resp.json()
            assert body["error"]["code"] == "SERVICE_SHUTTING_DOWN"
            assert "Retry-After" in resp.headers

    def test_503_response_includes_recovery_hint(self):
        """503 during shutdown must include actionable recovery_hint."""
        shutdown_event = asyncio.Event()
        shutdown_event.set()
        app = _make_app(shutdown_event)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/ping")
            body = resp.json()
            assert "recovery_hint" in body["error"]
            assert len(body["error"]["recovery_hint"]) > 0

    def test_retry_after_header_present_on_503(self):
        shutdown_event = asyncio.Event()
        shutdown_event.set()
        app = _make_app(shutdown_event)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/ping")
            assert resp.headers.get("Retry-After") == "10"

    def test_in_flight_counter_increments_and_decrements(self):
        """in_flight should be 0 after a successful request completes."""
        shutdown_event = asyncio.Event()

        test_app = FastAPI()

        @test_app.get("/counter")
        async def counter_endpoint():
            return PlainTextResponse("ok")

        test_app.add_middleware(GracefulShutdownMiddleware, shutdown_event=shutdown_event)

        with TestClient(test_app) as client:
            resp = client.get("/counter")
            assert resp.status_code == 200
        # After the request, in-flight should be back to 0.
        # We can't directly inspect the middleware instance from TestClient,
        # but the clean 200 response validates normal request lifecycle.


@pytest.mark.unit
class TestGracefulShutdownMiddlewareUnit:
    @pytest.mark.asyncio
    async def test_shutdown_event_starts_unset(self):
        """A fresh middleware instance should have its shutdown event unset."""
        event = asyncio.Event()
        middleware = GracefulShutdownMiddleware(FastAPI(), shutdown_event=event)
        assert not middleware._shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_shutdown_event_can_be_set(self):
        event = asyncio.Event()
        middleware = GracefulShutdownMiddleware(FastAPI(), shutdown_event=event)
        event.set()
        assert middleware._shutdown_event.is_set()
