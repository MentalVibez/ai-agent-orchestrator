"""
Arq worker for processing enqueued runs. Run with:

  RUN_QUEUE_URL=redis://localhost:6379 arq app.worker.WorkerSettings

Requires: pip install arq
"""

import logging

from app.core.config import settings
from app.core.dex.scheduled_jobs import dex_check_predictive_alerts, dex_scan_all_endpoints

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
    try:
        await run_planner_loop(
            run_id=run_id,
            goal=goal,
            agent_profile_id=agent_profile_id,
            context=context or None,
        )
    except Exception as exc:
        logger.error("Worker: run %s raised unhandled exception: %s: %s", run_id, type(exc).__name__, exc)
        try:
            from app.core.run_store import update_run
            await update_run(run_id, status="failed", error=str(exc))
        except Exception:
            pass
        raise
    logger.info("Worker finished run %s", run_id)


async def _on_job_error(ctx: dict, job_id: str, exc: Exception) -> None:
    """Arq callback: invoked when any job raises an unhandled exception.

    Logs a structured error with the arq job_id so failures can be traced
    in the application logs even when the job-level handler didn't catch them.
    """
    logger.error(
        "Worker: arq job %s failed with %s: %s",
        job_id,
        type(exc).__name__,
        exc,
    )


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


def _dex_scan_cron_minutes() -> set:
    """Compute the cron minute set from DEX_SCAN_INTERVAL_MINUTES.

    The interval must be a positive divisor of 60 (1, 2, 3, 4, 5, 6, 10, 12,
    15, 20, 30, 60).  Falls back to 15 if the configured value doesn't qualify.
    """
    interval = getattr(settings, "dex_scan_interval_minutes", 15)
    if interval <= 0 or 60 % interval != 0:
        logger.warning(
            "DEX_SCAN_INTERVAL_MINUTES=%d is not a positive divisor of 60; defaulting to 15",
            interval,
        )
        interval = 15
    return set(range(0, 60, interval))


def _build_cron_jobs() -> list:
    """Build arq CronJob list for DEX scheduled jobs."""
    try:
        from arq.cron import cron as arq_cron
    except ImportError:
        logger.warning("arq.cron not available — DEX scheduled jobs not registered")
        return []

    scan_minutes = _dex_scan_cron_minutes()
    jobs = [
        arq_cron(dex_scan_all_endpoints, minute=scan_minutes),
        arq_cron(dex_check_predictive_alerts, minute=0),  # top of every hour
    ]
    logger.info(
        "DEX scheduled jobs registered: fleet scan every %d min (minutes=%s), "
        "predictive check every hour",
        settings.dex_scan_interval_minutes,
        sorted(scan_minutes),
    )
    return jobs


class WorkerSettings:
    redis_settings = None
    functions = [run_planner]
    cron_jobs = _build_cron_jobs()

    # Do not retry unique planner runs on failure — retrying would start a
    # second execution with the same run_id, causing duplicate DB writes.
    max_tries = 1

    # Kill jobs that run longer than 10 minutes to prevent worker stalls.
    job_timeout = 600

    # Keep result data in Redis for 2 hours so failures are inspectable.
    keep_result = 7200

    # Structured error logging for any job that escapes its own exception handling.
    on_job_error = _on_job_error


WorkerSettings.redis_settings = _redis_settings()
