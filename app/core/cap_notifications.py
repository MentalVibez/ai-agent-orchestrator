"""Outbound webhook notification for per-API-key monthly spend cap breaches.

When a key's monthly LLM spend exceeds its cap, the planner fires:
    asyncio.create_task(notify_cap_breach(api_key_id, monthly_spend, cap))

The webhook payload is compatible with Slack Incoming Webhooks, Microsoft Teams
Incoming Webhooks (via the ``text`` field), and generic HTTP endpoints.

Set SPEND_CAP_WEBHOOK_URL in the environment to enable. Leave empty to disable.
"""

import logging
from datetime import datetime, timezone

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


async def notify_cap_breach(api_key_id: str, monthly_spend: float, cap: float) -> None:
    """POST a JSON breach event to SPEND_CAP_WEBHOOK_URL.

    No-op when the URL is not configured. Errors are logged and swallowed so
    the caller (planner) is never blocked by a notification failure.
    """
    try:
        url = getattr(settings, "spend_cap_webhook_url", "")
        if not url:
            return

        payload = {
            "event": "spend_cap_breach",
            "api_key_id": api_key_id,
            "monthly_spend_usd": round(monthly_spend, 4),
            "cap_usd": cap,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "text": (
                f"API key {api_key_id} exceeded ${cap:.2f} monthly LLM budget "
                f"(spent ${monthly_spend:.4f})."
            ),
        }

        async with httpx.AsyncClient(timeout=5.0) as _client:
            resp = await _client.post(url, json=payload)
            resp.raise_for_status()

        logger.info(
            "Spend cap breach notification sent for key %s (spend=%.4f cap=%.2f)",
            api_key_id, monthly_spend, cap,
        )
    except Exception as exc:
        logger.warning(
            "Spend cap breach notification failed for key %s: %s",
            api_key_id, exc,
        )
