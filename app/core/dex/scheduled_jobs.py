"""DEX Scheduled Jobs — arq background job functions for periodic fleet scanning.

Register these in app/core/worker.py under the arq WorkerSettings.
Requires RUN_QUEUE_URL (Redis) to be configured.

Jobs:
  dex_scan_all_endpoints   — every DEX_SCAN_INTERVAL_MINUTES (default 15)
  dex_check_predictive_alerts — every hour
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def dex_scan_all_endpoints(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Arq job: scan all active DEX endpoints for health telemetry.

    For each registered endpoint, waits for the planner run to complete,
    then processes the result (snapshot + score + alert evaluation).
    Runs on schedule every DEX_SCAN_INTERVAL_MINUTES.
    """
    import asyncio

    from app.core.config import settings
    from app.core.dex.endpoint_registry import list_endpoints
    from app.core.dex.telemetry_collector import process_completed_scan, trigger_endpoint_scan
    from app.db.database import SessionLocal

    db = SessionLocal()
    try:
        endpoints = list_endpoints(db, active_only=True)
    finally:
        db.close()

    if not endpoints:
        logger.info("DEX scan job: no active endpoints registered")
        return {"scanned": 0}

    logger.info("DEX scan job: scanning %d endpoints", len(endpoints))

    # We need the FastAPI app to trigger runs.
    # In arq worker context, access app via ctx["app"] if wired up, or use httpx.
    # For now, trigger runs via internal API call using httpx to localhost.
    import httpx

    base_url = f"http://127.0.0.1:{settings.port}"
    api_key = settings.api_key  # use the server's own API key

    results: Dict[str, Any] = {"scanned": 0, "errors": 0, "skipped": 0}
    timeout = httpx.Timeout(settings.planner_tool_timeout_seconds or 60.0)

    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
        headers = {"X-API-Key": api_key} if api_key else {}

        for endpoint in endpoints:
            hostname = endpoint.hostname
            try:
                # Trigger scan
                resp = await client.post(
                    f"/api/v1/dex/endpoints/{hostname}/scan",
                    headers=headers,
                )
                if resp.status_code != 200:
                    logger.warning(
                        "DEX scan: failed to trigger scan for %s (HTTP %d)",
                        hostname,
                        resp.status_code,
                    )
                    results["errors"] += 1
                    continue

                run_id = resp.json().get("run_id")
                if not run_id:
                    results["errors"] += 1
                    continue

                # Poll for completion (max 5 minutes)
                max_polls = 60
                answer = None
                for _ in range(max_polls):
                    await asyncio.sleep(5)
                    run_resp = await client.get(f"/api/v1/runs/{run_id}", headers=headers)
                    if run_resp.status_code != 200:
                        break
                    run_data = run_resp.json()
                    if run_data.get("status") == "completed":
                        answer = run_data.get("answer", "")
                        break
                    if run_data.get("status") in ("failed", "cancelled"):
                        break

                if answer is not None:
                    db = SessionLocal()
                    try:
                        process_completed_scan(
                            db=db,
                            hostname=hostname,
                            run_id=run_id,
                            answer=answer,
                            alert_threshold=settings.dex_score_alert_threshold,
                            critical_threshold=settings.dex_score_critical_threshold,
                        )
                    finally:
                        db.close()
                    results["scanned"] += 1
                else:
                    logger.warning("DEX scan: run %s did not complete for %s", run_id, hostname)
                    results["skipped"] += 1

            except Exception as exc:
                logger.error("DEX scan: error scanning %s: %s", hostname, exc)
                results["errors"] += 1

    logger.info("DEX scan job complete: %s", results)
    return results


async def dex_check_predictive_alerts(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Arq job: run predictive trend analysis across all active endpoints.

    Analyzes the last 7 days of metric snapshots to detect metrics trending
    toward critical thresholds (e.g. disk filling up, memory leak).
    Creates or updates DexAlerts with time-to-impact estimates.
    Runs on schedule every hour.
    """
    from app.core.dex.endpoint_registry import list_endpoints
    from app.core.dex.predictive_analysis import analyze_trends
    from app.db.database import SessionLocal

    db = SessionLocal()
    try:
        endpoints = list_endpoints(db, active_only=True)
        total_alerts = 0

        for endpoint in endpoints:
            try:
                trends = analyze_trends(db, endpoint.hostname)
                new_alerts = sum(1 for t in trends if t.get("status") == "alert")
                total_alerts += new_alerts
                if new_alerts:
                    logger.info(
                        "DEX predictive: %d new/updated alerts for hostname=%s",
                        new_alerts,
                        endpoint.hostname,
                    )
            except Exception as exc:
                logger.error(
                    "DEX predictive: error analyzing %s: %s", endpoint.hostname, exc
                )

    finally:
        db.close()

    logger.info("DEX predictive job complete: %d alerts created/updated", total_alerts)
    return {"endpoints_analyzed": len(endpoints), "alerts_created_or_updated": total_alerts}
