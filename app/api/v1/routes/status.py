"""Operational status page — no auth required.

GET /api/v1/status

Returns a JSON snapshot of system health for IT ops dashboards and monitoring tools.
Useful as a "public" (within the internal network) status page — no API key needed.

Response fields:
  service       App name
  version       App version string
  uptime_seconds  Seconds since the first request to this module
  timestamp     Current UTC ISO-8601
  database      "ok" or "error: <message>"
  llm_provider  Configured LLM provider name
  llm_model     Configured model identifier
  mcp_servers   List of {server_id, connected} dicts
  queue         {enabled: bool}
  runs_last_24h {completed, failed, running, pending, cancelled, awaiting_approval, ...}
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.rate_limit import limiter

router = APIRouter(prefix="/api/v1", tags=["status"])
logger = logging.getLogger(__name__)

# Module-level start time — set on first import; used for uptime calculation
_start_time = datetime.now(timezone.utc)


@router.get(
    "/status",
    summary="Operational status",
    description=(
        "No authentication required. Returns a JSON snapshot of system health: "
        "database, LLM provider, MCP servers, queue, and run counts for the last 24 hours."
    ),
)
@limiter.limit("60/minute")
async def status_page(request: Request) -> JSONResponse:
    """Return operational status without requiring an API key."""
    now = datetime.now(timezone.utc)

    # ── Database ──────────────────────────────────────────────────────────────
    db_status = "ok"
    try:
        from sqlalchemy import text

        from app.db.database import SessionLocal
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
    except Exception as exc:
        db_status = f"error: {exc}"

    # ── MCP servers ───────────────────────────────────────────────────────────
    mcp_servers = []
    try:
        from app.mcp.client_manager import get_mcp_client_manager
        from app.mcp.config_loader import load_mcp_servers_config

        mgr = get_mcp_client_manager()
        cfg = load_mcp_servers_config().get("mcp_servers") or {}
        for server_id in cfg:
            mcp_servers.append({
                "server_id": server_id,
                "connected": server_id in mgr._sessions,
            })
    except Exception as exc:
        logger.debug("Status page: MCP info unavailable: %s", exc)

    # ── Queue ─────────────────────────────────────────────────────────────────
    queue_enabled = bool((getattr(settings, "run_queue_url", "") or "").strip())

    # ── Runs last 24 h ────────────────────────────────────────────────────────
    runs_last_24h: dict = {}
    try:
        from collections import Counter

        from app.db.database import SessionLocal
        from app.db.models import Run

        cutoff = now - timedelta(hours=24)
        cutoff_naive = cutoff.replace(tzinfo=None)
        db = SessionLocal()
        try:
            try:
                rows = db.query(Run).filter(Run.created_at >= cutoff).all()
            except Exception:
                rows = db.query(Run).filter(Run.created_at >= cutoff_naive).all()
            runs_last_24h = dict(Counter(r.status for r in rows))
        finally:
            db.close()
    except Exception as exc:
        logger.debug("Status page: runs_last_24h unavailable: %s", exc)

    payload = {
        "service": settings.app_name,
        "version": settings.app_version,
        "uptime_seconds": int((now - _start_time).total_seconds()),
        "timestamp": now.isoformat(),
        "database": db_status,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "mcp_servers": mcp_servers,
        "queue": {"enabled": queue_enabled},
        "runs_last_24h": runs_last_24h,
    }
    return JSONResponse(content=payload)
