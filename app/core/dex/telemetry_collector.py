"""Telemetry Collector — triggers agent runs for endpoint health scans and stores snapshots.

Flow:
  trigger_endpoint_scan(app, hostname) → POST /api/v1/run (dex_proactive profile)
  store_snapshot_from_run(db, hostname, run_id, answer_json) → EndpointMetricSnapshot
  process_completed_scan(db, hostname, run_id, answer) → score + alert evaluation
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.db.models import EndpointMetricSnapshot

logger = logging.getLogger(__name__)

_DEX_PROFILE = "dex_proactive"


async def trigger_endpoint_scan(app: Any, hostname: str) -> str:
    """Start a dex_proactive planner run for this endpoint. Returns the run_id.

    The caller should poll GET /api/v1/runs/{run_id} until status=completed,
    then call process_completed_scan() with the answer.
    """
    from app.core.run_store import create_run
    from app.planner.loop import run_planner_loop

    goal = (
        f"Collect health telemetry for endpoint '{hostname}': "
        "report CPU usage, memory pressure, disk utilization, network latency and packet loss, "
        "status of critical services, and recent log error count. "
        "Return results as structured JSON only."
    )
    run = await create_run(
        goal=goal,
        agent_profile_id=_DEX_PROFILE,
        context={"dex_hostname": hostname, "source": "dex_telemetry_collector"},
    )

    llm_manager = app.state.container.get_llm_manager()
    asyncio.create_task(
        run_planner_loop(
            run_id=run.run_id,
            goal=goal,
            agent_profile_id=_DEX_PROFILE,
            context={"dex_hostname": hostname},
            llm_manager=llm_manager,
        )
    )
    logger.info("DEX: triggered scan for hostname=%s run_id=%s", hostname, run.run_id)
    return run.run_id


def _extract_json_from_answer(answer: str) -> Optional[Dict[str, Any]]:
    """Try to parse JSON from a planner answer string.

    The dex_proactive profile is instructed to return JSON only, but the LLM
    may wrap it in markdown code blocks. Handle both cases.
    """
    if not answer:
        return None
    # Strip markdown code fences if present
    stripped = re.sub(r"```(?:json)?\s*", "", answer).strip().rstrip("`").strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        # Try to find a JSON object within the text
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    logger.warning("DEX: could not parse JSON from agent answer (len=%d)", len(answer))
    return None


def store_snapshot(
    db: Session,
    hostname: str,
    run_id: Optional[str],
    data: Dict[str, Any],
) -> EndpointMetricSnapshot:
    """Persist a metric snapshot from parsed telemetry data."""
    snapshot = EndpointMetricSnapshot(
        hostname=hostname,
        run_id=run_id,
        cpu_pct=data.get("cpu_pct"),
        memory_pct=data.get("memory_pct"),
        disk_pct=data.get("disk_pct"),
        network_latency_ms=data.get("network_latency_ms"),
        packet_loss_pct=data.get("packet_loss_pct"),
        services_down=data.get("services_down") or [],
        log_error_count=data.get("log_error_count") or 0,
        raw_output=data,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    logger.info(
        "DEX: snapshot stored hostname=%s snapshot_id=%d cpu=%.1f mem=%.1f disk=%.1f",
        hostname,
        snapshot.id,
        snapshot.cpu_pct or 0,
        snapshot.memory_pct or 0,
        snapshot.disk_pct or 0,
    )
    return snapshot


def process_completed_scan(
    db: Session,
    hostname: str,
    run_id: str,
    answer: str,
    alert_threshold: int = 60,
    critical_threshold: int = 40,
) -> Dict[str, Any]:
    """Parse a completed scan answer, store snapshot, calculate DEX score, evaluate alerts.

    Returns a dict with snapshot_id, score, and alert (if any).
    """
    from app.core.dex.dex_score import calculate_score, evaluate_thresholds
    from app.core.dex.endpoint_registry import touch_last_scanned

    data = _extract_json_from_answer(answer)
    if not data:
        logger.warning(
            "DEX: scan for %s (run=%s) returned unparseable answer; skipping snapshot",
            hostname,
            run_id,
        )
        return {"ok": False, "reason": "unparseable_answer"}

    snapshot = store_snapshot(db, hostname, run_id, data)
    score_record = calculate_score(db, hostname, snapshot)
    alert = evaluate_thresholds(
        db,
        hostname,
        score_record,
        alert_threshold=alert_threshold,
        critical_threshold=critical_threshold,
    )
    touch_last_scanned(db, hostname)

    return {
        "ok": True,
        "hostname": hostname,
        "snapshot_id": snapshot.id,
        "score": score_record.score,
        "alert": alert.to_dict() if alert else None,
    }
