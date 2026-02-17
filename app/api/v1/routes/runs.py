"""API routes for MCP-centric runs (POST /run, GET /runs, GET /runs/:id, cancel, agent-profiles, mcp/servers)."""

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.auth import verify_api_key
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.run_store import create_run, get_run_by_id, list_runs
from app.core.validation import validate_agent_profile_id, validate_goal, validate_run_context
from app.mcp.config_loader import get_enabled_agent_profiles, load_mcp_servers_config
from app.models.run import RunDetailResponse, RunRequest, RunResponse, RunStatus
from app.planner.loop import run_planner_loop

router = APIRouter(prefix="/api/v1", tags=["runs"])


@router.post(
    "/run",
    response_model=RunResponse,
    status_code=201,
    summary="Start a run",
)
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def start_run(
    request: Request,
    body: RunRequest,
    api_key: str = Depends(verify_api_key),
) -> RunResponse:
    """
    Start a new MCP-centric run. Returns immediately with run_id; execution continues in background.
    Use GET /runs/{run_id} to poll for status and result.
    """
    goal = validate_goal(body.goal)
    context = validate_run_context(body.context)
    profile_id = validate_agent_profile_id(body.agent_profile_id)
    run = create_run(
        goal=goal,
        agent_profile_id=profile_id,
        context=context,
    )
    # Run planner in background so we return quickly
    asyncio.create_task(
        run_planner_loop(
            run_id=run.run_id,
            goal=goal,
            agent_profile_id=profile_id,
            context=context,
        )
    )
    return RunResponse(
        run_id=run.run_id,
        status=RunStatus(run.status),
        goal=run.goal,
        agent_profile_id=run.agent_profile_id,
        created_at=run.created_at.isoformat() if run.created_at else None,
        message="Run started. Poll GET /runs/{run_id} for status and result.",
    )


@router.post(
    "/runs/{run_id}/approve",
    summary="Approve pending tool call (HITL stub)",
    description="When a run is awaiting_approval, approve the pending tool call to continue. Stub: sets status back to running.",
)
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def approve_run(
    request: Request,
    run_id: str,
    api_key: str = Depends(verify_api_key),
) -> dict:
    """Approve a run that is awaiting human approval (HITL). Stub implementation."""
    run = get_run_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    if run.status != "awaiting_approval":
        return {"run_id": run_id, "status": run.status, "message": "Run is not awaiting approval."}
    from app.core.run_store import update_run as do_update

    do_update(run_id, status="running")
    return {"run_id": run_id, "status": "running", "message": "Approved."}


@router.post(
    "/runs/{run_id}/reject",
    summary="Reject pending tool call (HITL stub)",
    description="When a run is awaiting_approval, reject to fail the run. Stub: sets status to failed.",
)
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def reject_run(
    request: Request,
    run_id: str,
    api_key: str = Depends(verify_api_key),
) -> dict:
    """Reject a run that is awaiting human approval (HITL). Stub implementation."""
    run = get_run_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    if run.status != "awaiting_approval":
        return {"run_id": run_id, "status": run.status, "message": "Run is not awaiting approval."}
    from app.core.run_store import update_run as do_update

    do_update(run_id, status="failed", error="Tool call rejected by user")
    return {"run_id": run_id, "status": "failed", "message": "Rejected."}


@router.post("/runs/{run_id}/cancel")
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def cancel_run(
    request: Request,
    run_id: str,
    api_key: str = Depends(verify_api_key),
) -> dict:
    """Cancel a run. Sets status to cancelled; the planner will exit at the next step check."""
    run = get_run_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    if run.status in ("completed", "failed", "cancelled"):
        return {"run_id": run_id, "status": run.status, "message": "Run already ended."}
    from app.core.run_store import update_run as do_update

    do_update(run_id, status="cancelled")
    return {"run_id": run_id, "status": "cancelled", "message": "Cancel requested."}


@router.get(
    "/runs",
    summary="List runs",
    description="Paginated list of runs, newest first. Optional filter by status.",
)
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def list_runs_route(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(
        None, description="Filter by status: pending, running, completed, failed, cancelled"
    ),
    api_key: str = Depends(verify_api_key),
) -> dict:
    """List runs with optional status filter."""
    runs = list_runs(limit=limit, offset=offset, status=status)
    return {
        "runs": [r.to_dict() for r in runs],
        "limit": limit,
        "offset": offset,
        "count": len(runs),
    }


@router.get(
    "/runs/{run_id}",
    response_model=RunDetailResponse,
    summary="Get run details",
    responses={404: {"description": "Run not found"}},
)
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def get_run(
    request: Request,
    run_id: str,
    api_key: str = Depends(verify_api_key),
) -> RunDetailResponse:
    """Get run status, steps, tool calls, and final answer."""
    run = get_run_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return RunDetailResponse(
        run_id=run.run_id,
        status=RunStatus(run.status),
        goal=run.goal,
        agent_profile_id=run.agent_profile_id,
        created_at=run.created_at.isoformat() if run.created_at else None,
        updated_at=run.updated_at.isoformat() if run.updated_at else None,
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        error=run.error,
        answer=run.answer,
        steps=run.steps or [],
        tool_calls=run.tool_calls or [],
    )


@router.get("/agent-profiles")
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def list_agent_profiles(
    request: Request,
    api_key: str = Depends(verify_api_key),
) -> dict:
    """List enabled agent profiles (from config/agent_profiles.yaml)."""
    profiles = get_enabled_agent_profiles()
    return {
        "profiles": [
            {"id": pid, "name": cfg.get("name", pid), "description": cfg.get("description", "")}
            for pid, cfg in profiles
        ],
    }


@router.get("/mcp/servers")
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def list_mcp_servers(
    request: Request,
    api_key: str = Depends(verify_api_key),
) -> dict:
    """
    List connected MCP servers and their exposed tools (exposed actions map for governance/transparency).
    """
    config = load_mcp_servers_config()
    server_configs = config.get("mcp_servers") or {}
    try:
        from app.mcp.client_manager import get_mcp_client_manager

        manager = get_mcp_client_manager()
        connected = manager._initialized and len(manager._sessions) > 0
        servers = []
        for server_id, tools in (manager._tools_cache or {}).items():
            cfg = server_configs.get(server_id) or {}
            servers.append(
                {
                    "server_id": server_id,
                    "name": cfg.get("name", server_id),
                    "connected": True,
                    "tools": [
                        {"name": t["name"], "description": (t.get("description") or "")[:200]}
                        for t in tools
                    ],
                }
            )
        return {"connected": connected, "servers": servers}
    except Exception:
        return {"connected": False, "servers": []}
