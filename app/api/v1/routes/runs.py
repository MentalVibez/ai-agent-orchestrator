"""API routes for MCP-centric runs (POST /run, GET /runs, GET /runs/:id, cancel, agent-profiles, mcp/servers)."""

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.core.auth import verify_api_key
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.run_queue import enqueue_run
from app.core.run_store import create_run, get_run_by_id, get_run_events, list_runs
from app.core.validation import validate_agent_profile_id, validate_goal, validate_run_context
from app.mcp.config_loader import get_enabled_agent_profiles, load_mcp_servers_config
from app.models.run import ApproveRunRequest, RunDetailResponse, RunRequest, RunResponse, RunStatus
from app.planner.loop import execute_approved_tool_and_update_run, resume_planner_loop, run_planner_loop

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
    if body.stream_tokens:
        context = {**(context or {}), "_stream_tokens": True}
    profile_id = validate_agent_profile_id(body.agent_profile_id)
    run = await create_run(
        goal=goal,
        agent_profile_id=profile_id,
        context=context,
    )
    enqueued = await enqueue_run(
        run_id=run.run_id,
        goal=goal,
        agent_profile_id=profile_id,
        context=context,
    )
    if not enqueued:
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
    summary="Approve or reject pending tool call (HITL)",
    description="When a run is awaiting_approval, approve (execute the tool and resume) or reject (fail the run).",
)
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def approve_run(
    request: Request,
    run_id: str,
    body: ApproveRunRequest,
    api_key: str = Depends(verify_api_key),
) -> dict:
    """Approve or reject a run that is awaiting human approval (HITL)."""
    run = await get_run_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    if run.status != "awaiting_approval":
        return {"run_id": run_id, "status": run.status, "message": "Run is not awaiting approval."}
    from app.core.run_store import update_run as do_update

    if not body.approved:
        await do_update(
            run_id,
            status="failed",
            error="Tool call rejected by user",
            _clear_pending_tool_call=True,
        )
        return {"run_id": run_id, "status": "failed", "message": "Rejected."}
    ok = await execute_approved_tool_and_update_run(
        run_id,
        modified_arguments=body.modified_arguments,
    )
    if not ok:
        return {"run_id": run_id, "status": run.status, "message": "Could not execute approved tool."}
    asyncio.create_task(resume_planner_loop(run_id))
    return {"run_id": run_id, "status": "running", "message": "Approved; planner resuming."}


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
    run = await get_run_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    if run.status != "awaiting_approval":
        return {"run_id": run_id, "status": run.status, "message": "Run is not awaiting approval."}
    from app.core.run_store import update_run as do_update

    await do_update(
        run_id,
        status="failed",
        error="Tool call rejected by user",
        _clear_pending_tool_call=True,
    )
    return {"run_id": run_id, "status": "failed", "message": "Rejected."}


@router.post("/runs/{run_id}/cancel")
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def cancel_run(
    request: Request,
    run_id: str,
    api_key: str = Depends(verify_api_key),
) -> dict:
    """Cancel a run. Sets status to cancelled; the planner will exit at the next step check."""
    run = await get_run_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    if run.status in ("completed", "failed", "cancelled"):
        return {"run_id": run_id, "status": run.status, "message": "Run already ended."}
    from app.core.run_store import update_run as do_update

    await do_update(run_id, status="cancelled")
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
    runs = await list_runs(limit=limit, offset=offset, status=status)
    return {
        "runs": [r.to_dict() for r in runs],
        "limit": limit,
        "offset": offset,
        "count": len(runs),
    }


@router.get(
    "/runs/{run_id}/stream",
    summary="Stream run progress (SSE)",
    description="Server-Sent Events stream for run status, steps, answer, and optionally token chunks. When the run was started with stream_tokens=true, event type 'token' carries LLM output chunks. Best-effort; poll GET /runs/{run_id} for authoritative final state.",
    responses={404: {"description": "Run not found"}},
)
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def stream_run(
    request: Request,
    run_id: str,
    api_key: str = Depends(verify_api_key),
) -> StreamingResponse:
    """Stream run progress as SSE. Events: status, step, answer. Stops when run is completed/failed/cancelled."""
    run = await get_run_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    async def event_generator():
        last_event_id: Optional[int] = None
        poll_interval = 0.5
        while True:
            events = await get_run_events(run_id, after_id=last_event_id)
            for eid, etype, payload in events:
                last_event_id = eid
                data = json.dumps({"event_id": eid, "type": etype, **payload}, default=str)
                yield f"event: {etype}\ndata: {data}\n\n"
            run_state = await get_run_by_id(run_id)
            if run_state and run_state.status in ("completed", "failed", "cancelled"):
                yield f"event: end\ndata: {json.dumps({'status': run_state.status})}\n\n"
                break
            await asyncio.sleep(poll_interval)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
    run = await get_run_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    pending_approval = None
    if run.status == "awaiting_approval":
        pending_approval = getattr(run, "pending_tool_call", None)
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
        pending_approval=pending_approval,
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
