"""Unit tests for app/worker.py arq job worker."""

import sys
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings


def _import_worker():
    """Import app.worker with settings.run_queue_url temporarily set to a valid URL."""
    sys.modules.pop("app.worker", None)
    original_url = settings.run_queue_url
    try:
        settings.run_queue_url = "redis://localhost:6379"
        import app.worker
        return app.worker
    finally:
        settings.run_queue_url = original_url


@pytest.mark.unit
class TestWorker:
    """Tests for app/worker.py arq job worker."""

    def test_worker_functions_includes_run_planner(self):
        """WorkerSettings.functions should include the run_planner job handler."""
        worker = _import_worker()
        assert worker.run_planner in worker.WorkerSettings.functions

    def test_redis_settings_raises_on_empty_url(self):
        """_redis_settings() raises ValueError when run_queue_url is empty."""
        worker = _import_worker()
        original = settings.run_queue_url
        try:
            settings.run_queue_url = ""
            with pytest.raises(ValueError, match="RUN_QUEUE_URL"):
                worker._redis_settings()
        finally:
            settings.run_queue_url = original

    def test_redis_settings_returns_object_for_valid_url(self):
        """_redis_settings() returns a RedisSettings object for a valid URL."""
        worker = _import_worker()
        original = settings.run_queue_url
        try:
            settings.run_queue_url = "redis://localhost:6379"
            result = worker._redis_settings()
            assert result is not None
        finally:
            settings.run_queue_url = original

    @pytest.mark.asyncio
    async def test_run_planner_calls_loop(self):
        """run_planner job handler calls run_planner_loop with the right args."""
        worker = _import_worker()
        mock_loop = AsyncMock()
        with patch.object(
            sys.modules.get("app.planner.loop", type("M", (), {})()),
            "run_planner_loop",
            mock_loop,
            create=True,
        ):
            # Patch inside the function's lazy import path
            with patch("app.planner.loop.run_planner_loop", mock_loop):
                await worker.run_planner(
                    ctx={},
                    run_id="run-1",
                    goal="check network",
                    agent_profile_id="default",
                    context={"host": "example.com"},
                )
        mock_loop.assert_called_once_with(
            run_id="run-1",
            goal="check network",
            agent_profile_id="default",
            context={"host": "example.com"},
        )
