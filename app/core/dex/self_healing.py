"""Self-Healing Engine — maps DEX alerts to automated remediation actions.

When a DexAlert fires, this module:
  1. Looks up the alert name in config/dex_remediation_map.yaml
  2. If a mapping exists and DEX_SELF_HEALING_ENABLED=True:
     - Triggers a planner run (ansible playbook, service restart, etc.)
     - Updates the alert status to "remediating"
  3. If no mapping or self-healing disabled:
     - POSTs the alert to DEX_TICKET_WEBHOOK_URL (pre-emptive ticket creation)
     - Updates alert status to "needs_human"
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
import yaml

from app.core.config import settings
from app.db.models import DexAlert

logger = logging.getLogger(__name__)

_REMEDIATION_MAP_PATH = Path(__file__).resolve().parent.parent.parent.parent / "config" / "dex_remediation_map.yaml"
_remediation_map_cache: Optional[Dict[str, Any]] = None


def _load_remediation_map() -> Dict[str, Any]:
    """Load and cache the remediation map from YAML. Re-reads on each call for hot-reload support."""
    global _remediation_map_cache
    if not _REMEDIATION_MAP_PATH.exists():
        logger.warning("DEX: remediation map not found at %s", _REMEDIATION_MAP_PATH)
        return {}
    try:
        with open(_REMEDIATION_MAP_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("remediation_map", {}) if data else {}
    except Exception as e:
        logger.error("DEX: failed to load remediation map: %s", e)
        return {}


def _build_goal(action_config: Dict[str, Any], alert: DexAlert) -> str:
    """Build a natural-language goal for the remediation run."""
    action = action_config.get("action", "diagnose")
    hostname = alert.hostname

    if action == "ansible":
        playbook = action_config.get("playbook", "remediate")
        return f"Run Ansible playbook '{playbook}' on endpoint '{hostname}' to resolve: {alert.message}"
    elif action == "restart":
        service = action_config.get("service", "the affected service")
        return f"Restart service '{service}' on endpoint '{hostname}' to resolve: {alert.message}"
    elif action == "clear_cache":
        return f"Clear temporary files and application cache on endpoint '{hostname}' to free disk space."
    else:
        return (
            f"Diagnose and resolve the following issue on endpoint '{hostname}': {alert.message}"
        )


async def _trigger_remediation_run(
    alert: DexAlert,
    action_config: Dict[str, Any],
) -> Optional[str]:
    """Start a remediation planner run and return the run_id."""
    from app.core.run_store import create_run
    from app.planner.loop import run_planner_loop

    goal = _build_goal(action_config, alert)
    profile = "dex_proactive"
    run = await create_run(
        goal=goal,
        agent_profile_id=profile,
        context={
            "dex_hostname": alert.hostname,
            "dex_alert_id": alert.id,
            "source": "dex_self_healing",
        },
    )

    # Import LLM manager lazily to avoid circular imports
    try:
        from app.core.services import get_service_container
        container = get_service_container()
        llm_manager = container.get_llm_manager()
    except Exception:
        llm_manager = None

    asyncio.create_task(
        run_planner_loop(
            run_id=run.run_id,
            goal=goal,
            agent_profile_id=profile,
            context={"dex_hostname": alert.hostname, "dex_alert_id": alert.id},
            llm_manager=llm_manager,
        )
    )
    logger.info(
        "DEX self-healing: started run run_id=%s for alert_id=%s hostname=%s",
        run.run_id,
        alert.id,
        alert.hostname,
    )
    return run.run_id


async def _send_ticket_webhook(alert: DexAlert, dex_score: Optional[float] = None) -> None:
    """POST a pre-emptive ticket creation payload to DEX_TICKET_WEBHOOK_URL."""
    url = settings.dex_ticket_webhook_url
    if not url:
        return

    payload = {
        "source": "dex_platform",
        "hostname": alert.hostname,
        "alert_name": alert.alert_name,
        "severity": alert.severity,
        "alert_type": alert.alert_type,
        "message": alert.message,
        "predicted_time_to_impact": alert.predicted_time_to_impact,
        "dex_score": dex_score,
        "alert_id": alert.id,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
        "recovery_hint": (
            "A DEX alert was detected that could not be auto-remediated. "
            "Please review the diagnostic data and take manual action."
        ),
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code < 300:
                logger.info(
                    "DEX: ticket webhook called for alert_id=%s hostname=%s",
                    alert.id,
                    alert.hostname,
                )
            else:
                logger.warning(
                    "DEX: ticket webhook returned HTTP %d for alert_id=%s",
                    resp.status_code,
                    alert.id,
                )
    except Exception as exc:
        logger.error("DEX: ticket webhook failed for alert_id=%s: %s", alert.id, exc)


async def handle_alert(
    db: Any,  # SQLAlchemy Session
    alert: DexAlert,
    dex_score: Optional[float] = None,
) -> Dict[str, Any]:
    """Evaluate a DexAlert and take the appropriate action.

    Returns a dict describing what action was taken.
    """
    if alert.status not in ("active",):
        return {"action": "skipped", "reason": f"alert status is '{alert.status}'"}

    remediation_map = _load_remediation_map()
    action_config = remediation_map.get(alert.alert_name)

    if action_config and action_config.get("action") == "ticket":
        # Explicit "always escalate" mapping
        alert.status = "needs_human"
        db.commit()
        await _send_ticket_webhook(alert, dex_score)
        return {"action": "ticket", "alert_id": alert.id, "reason": "explicit_ticket_mapping"}

    if action_config and settings.dex_self_healing_enabled:
        # Auto-remediate
        try:
            run_id = await _trigger_remediation_run(alert, action_config)
            if run_id:
                alert.status = "remediating"
                alert.remediation_run_id = run_id
                db.commit()
                return {
                    "action": "remediation_started",
                    "alert_id": alert.id,
                    "run_id": run_id,
                }
        except Exception as exc:
            logger.error(
                "DEX self-healing: failed to start remediation for alert_id=%d: %s",
                alert.id,
                exc,
            )

    # No mapping or self-healing disabled — escalate to ticket system
    alert.status = "needs_human"
    db.commit()
    await _send_ticket_webhook(alert, dex_score)
    reason = (
        "no_remediation_mapping"
        if not action_config
        else "self_healing_disabled"
    )
    return {"action": "ticket", "alert_id": alert.id, "reason": reason}
