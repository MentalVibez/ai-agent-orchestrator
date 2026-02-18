"""
Optional job queue for runs. When RUN_QUEUE_URL is set, runs are enqueued
and processed by a worker; otherwise the planner runs in-process.
SSE remains valid because run events are stored in the DB (run_events).
"""

import logging
from typing import Any, Dict, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_pool: Any = None


async def enqueue_run(
    run_id: str,
    goal: str,
    agent_profile_id: str,
    context: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Enqueue a run for the worker to process. Returns True if enqueued,
    False if queue is disabled (caller should run planner in-process).
    """
    url = (getattr(settings, "run_queue_url", None) or "").strip()
    if not url:
        return False
    try:
        from arq import create_pool
        from arq.connections import RedisSettings
    except ImportError:
        logger.warning("arq not installed. Set RUN_QUEUE_URL only if arq is installed. Running in-process.")
        return False
    try:

        global _pool
        if _pool is None:
            _pool = await create_pool(RedisSettings.from_dsn(url))
        await _pool.enqueue_job(
            "run_planner",
            run_id,
            goal,
            agent_profile_id,
            context or {},
        )
        logger.info("Enqueued run %s for worker", run_id)
        return True
    except Exception as e:
        logger.warning("Failed to enqueue run %s: %s. Run will not be executed.", run_id, e)
        return False


async def close_pool() -> None:
    """Close the Redis pool if it was created."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
