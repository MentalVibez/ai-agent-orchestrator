"""
Arq worker for processing enqueued runs. Run with:

  RUN_QUEUE_URL=redis://localhost:6379 arq app.worker.WorkerSettings

Requires: pip install arq
"""

import logging

from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_planner(
    ctx: dict,
    run_id: str,
    goal: str,
    agent_profile_id: str,
    context: dict,
) -> None:
    """Job handler: run the planner loop for the given run."""
    from app.planner.loop import run_planner_loop

    logger.info("Worker processing run %s", run_id)
    await run_planner_loop(
        run_id=run_id,
        goal=goal,
        agent_profile_id=agent_profile_id,
        context=context or None,
    )
    logger.info("Worker finished run %s", run_id)


def _redis_settings():
    from arq.connections import RedisSettings

    url = (getattr(settings, "run_queue_url", None) or "").strip()
    if not url:
        raise ValueError("RUN_QUEUE_URL must be set to run the worker")
    if hasattr(RedisSettings, "from_dsn"):
        return RedisSettings.from_dsn(url)
    from urllib.parse import urlparse

    p = urlparse(url)
    return RedisSettings(
        host=p.hostname or "localhost",
        port=p.port or 6379,
        password=p.password if p.password else None,
    )


class WorkerSettings:
    redis_settings = None
    functions = [run_planner]


WorkerSettings.redis_settings = _redis_settings()
