"""
Expose the AI Agent Orchestrator as an MCP Server.

This allows any MCP-compatible AI assistant (Claude Desktop, Cursor, Windsurf, etc.)
to call orchestrator capabilities as tools — turning the orchestrator into a
first-class citizen in the MCP ecosystem.

Run modes:
  stdio (Claude Desktop / local):
    python -m app.mcp.server

  SSE HTTP (remote / LAN):
    python -m app.mcp.server --transport sse --port 8001

Claude Desktop config (~/.config/claude/claude_desktop_config.json):
  {
    "mcpServers": {
      "orchestrator": {
        "command": "python",
        "args": ["-m", "app.mcp.server"],
        "cwd": "/path/to/ai-agent-orchestrator"
      }
    }
  }
"""

import argparse
import asyncio
import logging
import sys
from typing import Any, Dict, Optional

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# FastMCP instance — tools are registered below.
mcp = FastMCP(
    "AI Agent Orchestrator",
    instructions=(
        "This server exposes the AI Agent Orchestrator. "
        "Use start_run to kick off a multi-step IT operations task, "
        "poll get_run_status for results, or use run_from_template for "
        "pre-built recipes (disk checks, service restarts, SSL audits, etc.)."
    ),
)


def _init_db() -> None:
    """Initialise the database (create tables if missing) for standalone runs."""
    try:
        from app.db.database import init_db

        init_db()
    except Exception as exc:  # noqa: BLE001
        logger.warning("DB init skipped: %s", exc)


def _get_llm_manager():
    """Return a minimal LLM manager for standalone planner runs."""
    from app.llm.manager import LLMManager

    return LLMManager()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def start_run(
    goal: str,
    agent_profile_id: str = "default",
    wait: bool = False,
    timeout_seconds: int = 120,
) -> Dict[str, Any]:
    """
    Start a new orchestrator run for the given goal.

    The orchestrator plans and executes multi-step IT operations using its
    configured MCP tools and LLM.

    Args:
        goal: What you want the orchestrator to accomplish (plain English).
        agent_profile_id: Agent profile to use (default = general purpose).
            Use list_agent_profiles() to discover options.
        wait: If True, block until the run completes (up to timeout_seconds).
        timeout_seconds: Maximum seconds to wait when wait=True.

    Returns:
        dict with run_id, status, and (when wait=True) the answer.
    """
    from app.core.run_store import create_run, get_run_by_id
    from app.planner.loop import run_planner_loop

    _init_db()
    run = await create_run(goal=goal, agent_profile_id=agent_profile_id, context={})
    run_id = run.run_id

    llm_manager = _get_llm_manager()

    if wait:
        # Run inline and wait for completion
        await asyncio.wait_for(
            run_planner_loop(
                run_id=run_id,
                goal=goal,
                agent_profile_id=agent_profile_id,
                context={},
                llm_manager=llm_manager,
            ),
            timeout=float(timeout_seconds),
        )
        finished = await get_run_by_id(run_id)
        return {
            "run_id": run_id,
            "status": finished.status if finished else "unknown",
            "answer": finished.answer if finished else None,
            "error": finished.error if finished else None,
        }
    else:
        # Fire and forget — caller should poll get_run_status
        asyncio.create_task(
            run_planner_loop(
                run_id=run_id,
                goal=goal,
                agent_profile_id=agent_profile_id,
                context={},
                llm_manager=llm_manager,
            )
        )
        return {
            "run_id": run_id,
            "status": "pending",
            "message": "Run started. Call get_run_status(run_id) to poll for results.",
        }


@mcp.tool()
async def get_run_status(run_id: str) -> Dict[str, Any]:
    """
    Get the current status and result of a run.

    Args:
        run_id: Run ID returned by start_run or run_from_template.

    Returns:
        dict with status, answer (when completed), error (when failed),
        and step_count for progress tracking.
    """
    from app.core.run_store import get_run_by_id

    _init_db()
    run = await get_run_by_id(run_id)
    if run is None:
        return {"error": f"Run '{run_id}' not found."}

    steps = run.steps or []
    return {
        "run_id": run_id,
        "status": run.status,
        "goal": run.goal,
        "agent_profile_id": run.agent_profile_id,
        "step_count": len(steps),
        "answer": run.answer,
        "error": run.error,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "completed_at": run.completed_at.isoformat() if getattr(run, "completed_at", None) else None,
        "pending_approval": getattr(run, "pending_tool_call", None) if run.status == "awaiting_approval" else None,
    }


@mcp.tool()
async def run_from_template(
    template_name: str,
    params: Optional[Dict[str, str]] = None,
    wait: bool = False,
    timeout_seconds: int = 120,
) -> Dict[str, Any]:
    """
    Start a run from a pre-built template with parameter substitution.

    Templates are pre-tested IT operations recipes. Call list_templates() first
    to discover available templates and their required parameters.

    Args:
        template_name: Template ID (e.g. "disk-health-check", "service-restart").
        params: Parameter values to fill into the template (e.g. {"host": "prod-01"}).
        wait: If True, block until the run completes.
        timeout_seconds: Maximum seconds to wait when wait=True.

    Returns:
        Same as start_run — run_id, status, and optionally the answer.
    """
    from app.core.run_store import create_run, get_run_by_id
    from app.core.run_templates import get_run_template, render_template_goal
    from app.planner.loop import run_planner_loop

    _init_db()
    template = get_run_template(template_name)
    if template is None:
        available = list((__import__("app.core.run_templates", fromlist=["load_run_templates"]).load_run_templates()).keys())
        return {"error": f"Template '{template_name}' not found. Available: {available}"}

    try:
        goal, agent_profile_id = render_template_goal(template, params or {})
    except ValueError as exc:
        return {"error": str(exc)}

    run = await create_run(goal=goal, agent_profile_id=agent_profile_id, context={})
    run_id = run.run_id
    llm_manager = _get_llm_manager()

    if wait:
        await asyncio.wait_for(
            run_planner_loop(
                run_id=run_id,
                goal=goal,
                agent_profile_id=agent_profile_id,
                context={},
                llm_manager=llm_manager,
            ),
            timeout=float(timeout_seconds),
        )
        finished = await get_run_by_id(run_id)
        return {
            "run_id": run_id,
            "template": template_name,
            "status": finished.status if finished else "unknown",
            "answer": finished.answer if finished else None,
            "error": finished.error if finished else None,
        }
    else:
        asyncio.create_task(
            run_planner_loop(
                run_id=run_id,
                goal=goal,
                agent_profile_id=agent_profile_id,
                context={},
                llm_manager=llm_manager,
            )
        )
        return {
            "run_id": run_id,
            "template": template_name,
            "goal": goal,
            "status": "pending",
            "message": "Run started. Call get_run_status(run_id) to poll for results.",
        }


@mcp.tool()
async def list_templates() -> Dict[str, Any]:
    """
    List all available run templates with their parameter schemas.

    Returns a list of templates, each with:
    - id: the template_name to pass to run_from_template
    - name: human-readable name
    - description: what it does
    - params: required and optional parameters with descriptions
    """
    from app.core.run_templates import list_run_templates

    return {"templates": list_run_templates()}


@mcp.tool()
async def list_agent_profiles() -> Dict[str, Any]:
    """
    List available agent profiles (specialist configurations for different task types).

    Use the profile id as agent_profile_id in start_run.
    """
    from app.mcp.config_loader import get_enabled_agent_profiles

    profiles = [
        {
            "id": pid,
            "name": cfg.get("name", pid),
            "description": cfg.get("description", ""),
        }
        for pid, cfg in get_enabled_agent_profiles()
    ]
    return {"profiles": profiles}


@mcp.tool()
async def list_runs(
    limit: int = 20,
    status_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """
    List recent orchestrator runs, optionally filtered by status.

    Args:
        limit: Maximum number of runs to return (1-100).
        status_filter: Filter by status: pending | running | completed | failed | cancelled.

    Returns:
        List of runs with id, status, goal excerpt, and timestamps.
    """
    from app.core.run_store import list_runs as _list_runs

    _init_db()
    limit = max(1, min(100, limit))
    runs = await _list_runs(limit=limit, status=status_filter)
    return {
        "runs": [
            {
                "run_id": r.run_id,
                "status": r.status,
                "goal": (r.goal or "")[:120],
                "agent_profile_id": r.agent_profile_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in runs
        ]
    }


@mcp.tool()
async def cancel_run(run_id: str) -> Dict[str, Any]:
    """
    Cancel an in-progress run.

    Args:
        run_id: Run ID to cancel.

    Returns:
        dict with run_id and new status.
    """
    from app.core.run_store import get_run_by_id, update_run

    _init_db()
    run = await get_run_by_id(run_id)
    if run is None:
        return {"error": f"Run '{run_id}' not found."}
    if run.status not in ("pending", "running"):
        return {"run_id": run_id, "status": run.status, "message": "Run is not cancellable."}

    await update_run(run_id, status="cancelled")
    return {"run_id": run_id, "status": "cancelled"}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point: python -m app.mcp.server [--transport stdio|sse] [--port PORT]"""
    parser = argparse.ArgumentParser(description="AI Agent Orchestrator MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport to use: stdio (Claude Desktop) or sse (HTTP remote). Default: stdio.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8001,
        help="Port for SSE transport. Default: 8001.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for SSE transport. Default: 127.0.0.1 (loopback only).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    _init_db()

    if args.transport == "sse":
        mcp.run(transport="sse", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
