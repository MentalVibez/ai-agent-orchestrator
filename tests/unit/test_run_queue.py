"""Unit tests for optional run queue (enqueue_run, close_pool)."""

from unittest.mock import AsyncMock, patch

import pytest

import app.core.run_queue as run_queue_module


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enqueue_run_returns_false_when_queue_url_empty():
    """When RUN_QUEUE_URL is empty, enqueue_run returns False (in-process)."""
    with patch("app.core.run_queue.settings") as mock_settings:
        mock_settings.run_queue_url = ""
        result = await run_queue_module.enqueue_run("run-1", "goal", "default", None)
    assert result is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enqueue_run_calls_enqueue_job_when_url_set():
    """When RUN_QUEUE_URL is set and create_pool succeeds, enqueue_job is called."""
    pytest.importorskip("arq")
    run_queue_module._pool = None
    mock_pool = AsyncMock()
    with patch("app.core.run_queue.settings") as mock_settings:
        mock_settings.run_queue_url = "redis://localhost:6379"
        with patch("arq.create_pool", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_pool
            result = await run_queue_module.enqueue_run(
                "run-1", "my goal", "default", {"k": "v"}
            )
    assert result is True
    mock_pool.enqueue_job.assert_called_once()
    call = mock_pool.enqueue_job.call_args
    assert call[0][0] == "run_planner"
    assert call[0][1] == "run-1"
    assert call[0][2] == "my goal"
    assert call[0][3] == "default"
    assert call[0][4] == {"k": "v"}
