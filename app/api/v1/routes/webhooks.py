"""Webhook endpoints for external systems (Prometheus Alertmanager, etc.)."""

import asyncio
import hashlib
import hmac
import logging
import time
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.core.rate_limit import limiter
from app.core.run_store import create_run, list_runs
from app.core.validation import validate_goal
from app.planner.loop import run_planner_loop

router = APIRouter(prefix="/api/v1", tags=["webhooks"])
logger = logging.getLogger(__name__)

# In-memory deduplication cache: alert_fingerprint -> timestamp of last accepted run
# Key: sha256 of sorted label key=value pairs; Value: unix timestamp
_dedup_cache: Dict[str, float] = {}


async def _fire_dex_self_healing(alert_data: Dict[str, Any], summary: str) -> None:
    """Background task: create a DexAlert for a Prometheus alert and trigger self-healing.

    Resolves the hostname from the alert labels, checks whether it is a registered
    DEX endpoint, deduplicates against existing active prometheus alerts, and then
    calls handle_alert() to auto-remediate or escalate to a ticket.
    Safe to call fire-and-forget; all errors are logged, never propagated.
    """
    from app.core.dex.endpoint_registry import get_endpoint
    from app.core.dex.self_healing import handle_alert
    from app.db.database import SessionLocal
    from app.db.models import DexAlert

    labels = alert_data.get("labels") or {}
    # Prefer explicit "hostname" label; fall back to instance (strip port if present)
    hostname = labels.get("hostname") or labels.get("instance", "").split(":")[0]
    if not hostname:
        return

    alert_name = labels.get("alertname", "PrometheusAlert")
    severity = labels.get("severity", "warning")
    annotations = alert_data.get("annotations") or {}
    message = annotations.get("summary") or annotations.get("description") or summary

    db = SessionLocal()
    try:
        endpoint = get_endpoint(db, hostname)
        if not endpoint or not endpoint.is_active:
            return  # Not a managed DEX endpoint — nothing to do

        # Deduplicate: skip if an active prometheus alert for this name already exists
        existing = (
            db.query(DexAlert)
            .filter(
                DexAlert.hostname == hostname,
                DexAlert.alert_name == alert_name,
                DexAlert.alert_type == "prometheus",
                DexAlert.status == "active",
            )
            .first()
        )
        if existing:
            logger.info(
                "DEX: skipping duplicate prometheus alert %s for hostname=%s (alert_id=%d)",
                alert_name,
                hostname,
                existing.id,
            )
            return

        dex_alert = DexAlert(
            hostname=hostname,
            alert_name=alert_name,
            severity=severity,
            alert_type="prometheus",
            message=message,
        )
        db.add(dex_alert)
        db.commit()
        db.refresh(dex_alert)

        logger.info(
            "DEX: created prometheus DexAlert alert_id=%d hostname=%s alert_name=%s",
            dex_alert.id,
            hostname,
            alert_name,
        )

        await handle_alert(db, dex_alert)

    except Exception as exc:
        logger.error("DEX: prometheus self-healing hook failed: %s", exc, exc_info=True)
    finally:
        db.close()


def _alert_summary(alert: Dict[str, Any]) -> str:
    """Build a short summary from an alert for use in a run goal."""
    labels = alert.get("labels") or {}
    annotations = alert.get("annotations") or {}
    name = labels.get("alertname", "Alert")
    summary = annotations.get("summary") or annotations.get("description") or name
    instance = labels.get("instance", "")
    if instance:
        summary = f"{summary} (instance={instance})"
    return summary


def _alert_fingerprint(alert: Dict[str, Any]) -> str:
    """Compute a stable fingerprint for an alert based on its labels."""
    labels = alert.get("labels") or {}
    # Sort for determinism; join as key=value pairs
    parts = sorted(f"{k}={v}" for k, v in labels.items())
    fingerprint_input = "|".join(parts).encode("utf-8")
    return hashlib.sha256(fingerprint_input).hexdigest()


def _is_duplicate(fingerprint: str, ttl_seconds: int) -> bool:
    """Return True if this alert fingerprint was seen within the TTL window."""
    now = time.monotonic()
    last_seen = _dedup_cache.get(fingerprint)
    if last_seen is not None and (now - last_seen) < ttl_seconds:
        return True
    return False


def _record_alert(fingerprint: str) -> None:
    """Record that an alert with this fingerprint was processed now."""
    _dedup_cache[fingerprint] = time.monotonic()
    # Prune stale entries to prevent unbounded growth (keep cache bounded to ~1000 entries)
    if len(_dedup_cache) > 1000:
        now = time.monotonic()
        ttl = settings.webhook_dedup_ttl_seconds
        stale = [k for k, v in _dedup_cache.items() if (now - v) > ttl]
        for k in stale:
            _dedup_cache.pop(k, None)


def _verify_webhook_signature(body_bytes: bytes, request: Request) -> bool:
    """
    Verify the X-Webhook-Token header using HMAC-SHA256.
    Returns True if valid or if no webhook_secret is configured (auth disabled).
    Returns False if secret is configured but token is missing or wrong.
    """
    secret = getattr(settings, "webhook_secret", "")
    if not secret:
        if settings.webhook_require_auth:
            logger.error(
                "WEBHOOK_SECRET is not set but WEBHOOK_REQUIRE_AUTH=True. "
                "Rejecting webhook request. Set WEBHOOK_SECRET or set "
                "WEBHOOK_REQUIRE_AUTH=False to allow unauthenticated webhooks."
            )
            return False
        # Auth explicitly disabled — allow but warn
        logger.warning(
            "WEBHOOK_SECRET not configured and WEBHOOK_REQUIRE_AUTH=False — "
            "webhook endpoint is unauthenticated. Not recommended for production."
        )
        return True

    token = request.headers.get("X-Webhook-Token", "")
    if not token:
        return False

    expected = hmac.new(
        secret.encode("utf-8"), body_bytes, hashlib.sha256
    ).hexdigest()
    # Constant-time comparison to prevent timing attacks
    return hmac.compare_digest(expected, token)


@router.post(
    "/webhooks/prometheus",
    summary="Prometheus Alertmanager webhook",
    description=(
        "Accepts Alertmanager webhook payloads. Optionally triggers an AI run to diagnose "
        "firing alerts. Requires X-Webhook-Token header (HMAC-SHA256 of body) when "
        "WEBHOOK_SECRET is configured."
    ),
)
@limiter.limit("20/minute")
async def prometheus_webhook(
    request: Request,
    trigger_run: bool = Query(
        False,
        description="If true, start a background run to diagnose the first firing alert",
    ),
    agent_profile_id: str = Query(
        "default",
        description="Agent profile to use when trigger_run=true",
    ),
) -> dict:
    """
    Receive Prometheus Alertmanager webhook (DEX stack: Alerts → Action).
    Payload: Alertmanager v4 JSON (version, status, alerts[], commonLabels, commonAnnotations).
    When trigger_run=true, starts a run with goal derived from the first firing alert.

    Security:
    - Requires X-Webhook-Token: <HMAC-SHA256(body, WEBHOOK_SECRET)> when WEBHOOK_SECRET is set.
    - Rate limited to 20 requests/minute.
    - Deduplicates identical alerts within WEBHOOK_DEDUP_TTL_SECONDS (default 300s).
    - Caps concurrent webhook-triggered runs at WEBHOOK_MAX_CONCURRENT_RUNS (default 5).
    """
    # Read raw body for signature verification before parsing JSON
    try:
        body_bytes = await request.body()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to read request body")

    # Security: verify webhook signature
    if not _verify_webhook_signature(body_bytes, request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Webhook-Token. Expected HMAC-SHA256(body, WEBHOOK_SECRET).",
        )

    # Parse JSON
    try:
        import json
        body = json.loads(body_bytes)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload")

    webhook_status = body.get("status", "")
    alerts: List[Dict[str, Any]] = body.get("alerts") or []

    # Only consider firing alerts for auto-run
    firing = [a for a in alerts if a.get("status") == "firing"]
    if not firing and trigger_run:
        return {
            "ok": True,
            "message": "No firing alerts; no run started",
            "status": webhook_status,
            "alerts_count": len(alerts),
        }

    # DEX self-healing hook: always fires for registered endpoints, independent of trigger_run
    if firing:
        asyncio.create_task(
            _fire_dex_self_healing(firing[0], _alert_summary(firing[0]))
        )

    if not trigger_run:
        return {
            "ok": True,
            "message": "Webhook received (trigger_run=false)",
            "status": webhook_status,
            "alerts_count": len(alerts),
        }

    # Use first firing alert to generate the run goal
    first = firing[0]
    fingerprint = _alert_fingerprint(first)
    dedup_ttl = getattr(settings, "webhook_dedup_ttl_seconds", 300)

    # Security: deduplicate — same alert within TTL window → skip
    if _is_duplicate(fingerprint, dedup_ttl):
        logger.info("Webhook: deduplicated alert (fingerprint=%s)", fingerprint[:16])
        return {
            "ok": True,
            "message": f"Alert deduplicated — identical alert processed within last {dedup_ttl}s. No new run started.",
            "status": webhook_status,
            "alerts_count": len(firing),
            "deduplicated": True,
        }

    # Security: concurrency cap — prevent alert storms from spawning unlimited runs
    max_concurrent = getattr(settings, "webhook_max_concurrent_runs", 5)
    try:
        active_runs = await list_runs(status="running", limit=max_concurrent + 1)
        if len(active_runs) >= max_concurrent:
            logger.warning(
                "Webhook: concurrency cap hit (%d active runs >= max %d)", len(active_runs), max_concurrent
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Too many concurrent runs ({len(active_runs)} active). "
                    f"Maximum is {max_concurrent}. Retry after some runs complete."
                ),
                headers={"Retry-After": "60"},
            )
    except HTTPException:
        raise
    except Exception:
        # list_runs failure shouldn't block the webhook — proceed without cap check
        logger.warning("Webhook: failed to check active run count; proceeding without cap check")

    summary = _alert_summary(first)
    goal = f"Diagnose and suggest remediation for: {summary}"
    try:
        goal = validate_goal(goal)
    except ValidationError as e:
        return {"ok": False, "error": str(e), "alerts_count": len(firing)}

    # Record dedup entry before starting run (prevents race condition duplicate)
    _record_alert(fingerprint)

    run = await create_run(
        goal=goal,
        agent_profile_id=agent_profile_id,
        context={"source": "prometheus_webhook", "alerts": firing[:3]},
    )
    req_id = getattr(request.state, "request_id", None)
    llm_manager = request.app.state.container.get_llm_manager()
    asyncio.create_task(
        run_planner_loop(
            run_id=run.run_id,
            goal=goal,
            agent_profile_id=agent_profile_id,
            context=run.context or {},
            request_id=req_id,
            llm_manager=llm_manager,
        )
    )

    logger.info(
        "Webhook: started run run_id=%s for alert fingerprint=%s goal=%r",
        run.run_id,
        fingerprint[:16],
        goal[:100],
    )

    return {
        "ok": True,
        "message": "Run started for firing alert",
        "run_id": run.run_id,
        "goal": goal,
        "status": webhook_status,
        "alerts_count": len(firing),
    }
