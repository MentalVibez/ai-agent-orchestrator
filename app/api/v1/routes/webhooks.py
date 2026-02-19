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
        # Webhook auth not configured — allow (but log a warning)
        logger.warning(
            "WEBHOOK_SECRET not configured — webhook endpoint is unauthenticated. "
            "Set WEBHOOK_SECRET in environment for production use."
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
    asyncio.create_task(
        run_planner_loop(
            run_id=run.run_id,
            goal=goal,
            agent_profile_id=agent_profile_id,
            context=run.context or {},
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
