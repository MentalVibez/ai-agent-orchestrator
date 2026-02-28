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

    def test_cron_jobs_registered(self):
        """WorkerSettings.cron_jobs should include both DEX scheduled jobs."""
        worker = _import_worker()
        cron_jobs = worker.WorkerSettings.cron_jobs
        # arq CronJob objects expose a .coroutine attribute
        job_coroutines = [j.coroutine for j in cron_jobs]
        from app.core.dex.scheduled_jobs import (
            dex_check_predictive_alerts,
            dex_scan_all_endpoints,
        )
        assert dex_scan_all_endpoints in job_coroutines
        assert dex_check_predictive_alerts in job_coroutines

    def test_dex_scan_cron_minutes_default(self):
        """Default 15-minute interval yields {0, 15, 30, 45}."""
        worker = _import_worker()
        original = settings.dex_scan_interval_minutes
        try:
            settings.dex_scan_interval_minutes = 15
            minutes = worker._dex_scan_cron_minutes()
            assert minutes == {0, 15, 30, 45}
        finally:
            settings.dex_scan_interval_minutes = original

    def test_dex_scan_cron_minutes_30(self):
        """30-minute interval yields {0, 30}."""
        worker = _import_worker()
        original = settings.dex_scan_interval_minutes
        try:
            settings.dex_scan_interval_minutes = 30
            minutes = worker._dex_scan_cron_minutes()
            assert minutes == {0, 30}
        finally:
            settings.dex_scan_interval_minutes = original

    def test_dex_scan_cron_minutes_fallback_for_invalid(self):
        """Non-divisor interval (e.g. 7) falls back to 15-minute schedule."""
        worker = _import_worker()
        original = settings.dex_scan_interval_minutes
        try:
            settings.dex_scan_interval_minutes = 7
            minutes = worker._dex_scan_cron_minutes()
            assert minutes == {0, 15, 30, 45}
        finally:
            settings.dex_scan_interval_minutes = original

    @pytest.mark.asyncio
    async def test_run_planner_marks_failed_on_exception(self):
        """When run_planner_loop raises, run is marked failed and exception is re-raised."""
        from unittest.mock import AsyncMock, patch

        worker = _import_worker()
        mock_loop = AsyncMock(side_effect=RuntimeError("planner exploded"))
        mock_update = AsyncMock()

        with patch("app.planner.loop.run_planner_loop", mock_loop), \
             patch("app.core.run_store.update_run", mock_update):
            with pytest.raises(RuntimeError, match="planner exploded"):
                await worker.run_planner(
                    ctx={},
                    run_id="fail-run-1",
                    goal="diagnose host",
                    agent_profile_id="default",
                    context={},
                )
        mock_update.assert_awaited_once_with(
            "fail-run-1", status="failed", error="planner exploded"
        )

    @pytest.mark.asyncio
    async def test_on_job_error_does_not_raise(self):
        """_on_job_error should log and return silently regardless of exception type."""
        worker = _import_worker()
        await worker._on_job_error(ctx={}, job_id="arq-job-abc", exc=ValueError("boom"))
        await worker._on_job_error(ctx={}, job_id="arq-job-xyz", exc=RuntimeError("oops"))

    def test_worker_settings_max_tries_is_one(self):
        """max_tries=1 prevents arq from retrying unique runs with the same run_id."""
        worker = _import_worker()
        assert worker.WorkerSettings.max_tries == 1

    def test_worker_settings_job_timeout(self):
        """job_timeout should be 600 seconds (10 minutes)."""
        worker = _import_worker()
        assert worker.WorkerSettings.job_timeout == 600

    def test_worker_settings_keep_result(self):
        """keep_result should be set so failed job results remain inspectable in Redis."""
        worker = _import_worker()
        assert worker.WorkerSettings.keep_result == 7200

    def test_worker_settings_on_job_error_is_set(self):
        """WorkerSettings.on_job_error should be the _on_job_error callback."""
        worker = _import_worker()
        assert worker.WorkerSettings.on_job_error is worker._on_job_error
