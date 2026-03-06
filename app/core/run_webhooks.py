"""Outbound run-event webhooks.

When a run reaches a terminal state (completed, failed, cancelled) or needs
human approval (awaiting_approval), a JSON payload is POSTed to the webhook
URL registered on the API key that owns the run.

Fire-and-forget: the caller wraps this in asyncio.create_task() so failures
never block the planner. Errors are logged and swallowed.

TODO (future): add HMAC-SHA256 request signing (X-Signature-256 header) so
receivers can verify payloads originate from this service.
"""

import logging
from typing import Optional

import httpx

from app.db.database import SessionLocal

logger = logging.getLogger(__name__)


async def notify_run_terminal(
    run_id: str,
    goal: str,
    status: str,
    api_key_id: Optional[str],
    answer: Optional[str] = None,
    error: Optional[str] = None,
    created_at: Optional[str] = None,
    completed_at: Optional[str] = None,
) -> None:
    """POST a run event to the webhook URL registered for api_key_id.

    No-op when:
    - api_key_id is None (legacy/unowned run)
    - the key has no webhook_url configured
    Errors are caught and logged so the caller is never blocked.
    """
    try:
        if not api_key_id:
            return

        db = SessionLocal()
        try:
            from app.db.models import ApiKeyRecord

            rec = db.query(ApiKeyRecord).filter(ApiKeyRecord.key_id == api_key_id).first()
            webhook_url = rec.webhook_url if rec else None
        finally:
            db.close()

        if not webhook_url:
            return

        payload = {
            "event": f"run.{status}",
            "run_id": run_id,
            "goal": goal,
            "status": status,
            "answer": answer,
            "error": error,
            "api_key_id": api_key_id,
            "created_at": created_at,
            "completed_at": completed_at,
            "text": f"Run {run_id} {status}.",
        }

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()

    except Exception as exc:
        logger.warning("Run webhook delivery failed for run %s: %s", run_id, exc)
