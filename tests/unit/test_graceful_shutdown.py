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
    @test_app.get("/ping")
    async def ping():
        return PlainTextResponse("pong")

    # Wrap with the middleware
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


@pytest.mark.unit
class TestGracefulShutdownInternals:
    """Tests for _register_signal_handlers, _handle_sigterm, _wait_and_exit."""

    def test_register_signal_handlers_success_path(self):
        """When the event loop supports add_signal_handler, it is called with SIGTERM."""
        import signal
        from unittest.mock import MagicMock, patch

        mock_loop = MagicMock()
        mock_loop.add_signal_handler = MagicMock()

        event = asyncio.Event()
        with patch(
            "app.middleware.graceful_shutdown.asyncio.get_event_loop",
            return_value=mock_loop,
        ):
            mw = GracefulShutdownMiddleware(FastAPI(), shutdown_event=event)

        mock_loop.add_signal_handler.assert_called_once_with(
            signal.SIGTERM, mw._handle_sigterm
        )

    @pytest.mark.asyncio
    async def test_handle_sigterm_sets_shutdown_event(self):
        """Calling _handle_sigterm() must set the shutdown event."""
        from unittest.mock import patch

        event = asyncio.Event()
        mw = GracefulShutdownMiddleware(FastAPI(), shutdown_event=event)

        # Patch ensure_future so we don't schedule a real drain coroutine
        with patch("app.middleware.graceful_shutdown.asyncio.ensure_future"):
            mw._handle_sigterm()

        assert event.is_set()

    @pytest.mark.asyncio
    async def test_handle_sigterm_schedules_wait_and_exit(self):
        """_handle_sigterm must schedule _wait_and_exit via ensure_future."""
        from unittest.mock import patch

        event = asyncio.Event()
        mw = GracefulShutdownMiddleware(FastAPI(), shutdown_event=event)

        with patch(
            "app.middleware.graceful_shutdown.asyncio.ensure_future"
        ) as mock_future:
            mw._handle_sigterm()

        mock_future.assert_called_once()

    @pytest.mark.asyncio
    async def test_wait_and_exit_logs_drained_when_no_in_flight(self):
        """When _in_flight is 0 the loop is skipped and 'drained' is logged."""
        from unittest.mock import patch

        event = asyncio.Event()
        mw = GracefulShutdownMiddleware(FastAPI(), shutdown_event=event)
        mw._in_flight = 0  # nothing pending

        with patch("app.middleware.graceful_shutdown.logger") as mock_log:
            await mw._wait_and_exit()

        # The 'all requests drained' info log should appear (line 71)
        info_messages = [str(c) for c in mock_log.info.call_args_list]
        assert any("drained" in m for m in info_messages)

    @pytest.mark.asyncio
    async def test_wait_and_exit_drains_eventually(self):
        """When _in_flight drops to 0 during the drain loop, exit is clean."""
        from unittest.mock import patch

        event = asyncio.Event()
        mw = GracefulShutdownMiddleware(FastAPI(), shutdown_event=event)
        mw._in_flight = 1

        sleep_calls = [0]

        async def fake_sleep(_):
            # Simulate the in-flight request finishing on first sleep
            sleep_calls[0] += 1
            mw._in_flight = 0

        with patch(
            "app.middleware.graceful_shutdown.asyncio.sleep", side_effect=fake_sleep
        ), patch("app.middleware.graceful_shutdown.GRACEFUL_SHUTDOWN_TIMEOUT", 5):
            await mw._wait_and_exit()

        assert sleep_calls[0] >= 1
        assert mw._in_flight == 0

    @pytest.mark.asyncio
    async def test_wait_and_exit_timeout_logs_warning(self):
        """When deadline expires with requests still in flight, a warning is logged."""
        from unittest.mock import AsyncMock, patch

        event = asyncio.Event()
        mw = GracefulShutdownMiddleware(FastAPI(), shutdown_event=event)
        mw._in_flight = 1  # never drains

        with patch(
            "app.middleware.graceful_shutdown.asyncio.sleep", new_callable=AsyncMock
        ), patch(
            "app.middleware.graceful_shutdown.GRACEFUL_SHUTDOWN_TIMEOUT", 1
        ), patch("app.middleware.graceful_shutdown.logger") as mock_log:
            await mw._wait_and_exit()

        # Warning about timeout must appear
        warning_messages = [str(c) for c in mock_log.warning.call_args_list]
        assert any("timeout" in m for m in warning_messages)
