"""
Minimal planner loop: given goal and allowed MCP tools, prompt LLM for next action
(tool call or FINISH); execute tool, append to context, repeat until FINISH or max steps.
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.prompt_injection import (
    STRUCTURAL_INSTRUCTION,
    USER_GOAL_END,
    USER_GOAL_START,
    apply_prompt_injection_filter,
)
from app.core.run_store import get_run_by_id, update_run
from app.mcp.client_manager import get_mcp_client_manager
from app.mcp.config_loader import get_agent_profile

logger = logging.getLogger(__name__)

MAX_PLANNER_STEPS = 15


def _format_tools_for_prompt(tools: List[Dict[str, Any]]) -> str:
    """Format MCP tools as text for the planner prompt."""
    if not tools:
        return "No tools available."
    lines = []
    for t in tools:
        lines.append(f"- Server: {t['server_id']}, Tool: {t['name']}: {t.get('description', '')}")
    return "\n".join(lines)


def _parse_planner_response(response: str) -> Optional[Dict[str, Any]]:
    """
    Parse LLM output for either tool_call or finish.
    Expected JSON block: {"action": "tool_call", "server_id": "...", "tool_name": "...", "arguments": {...}}
    or {"action": "finish", "answer": "..."}
    """
    # Try to find a JSON object in the response
    response = response.strip()
    # Look for {...}
    match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", response, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            action = data.get("action")
            if action == "tool_call":
                server_id = data.get("server_id")
                tool_name = data.get("tool_name")
                arguments = data.get("arguments") or {}
                if server_id and tool_name:
                    return {
                        "action": "tool_call",
                        "server_id": server_id,
                        "tool_name": tool_name,
                        "arguments": arguments,
                    }
            elif action == "finish":
                answer = data.get("answer", "")
                return {"action": "finish", "answer": answer}
        except json.JSONDecodeError:
            pass
    # Fallback: look for FINISH or TOOL_CALL lines
    if "FINISH" in response.upper():
        idx = response.upper().find("FINISH")
        rest = response[idx + 6 :].strip()
        return {"action": "finish", "answer": rest or response}
    return None


async def run_planner_loop(
    run_id: str,
    goal: str,
    agent_profile_id: str,
    context: Optional[Dict[str, Any]] = None,
    llm_generate: Optional[Any] = None,
) -> None:
    """
    Run the planner loop for the given run. Updates run in DB (steps, tool_calls, status, answer).
    If no MCP tools are available for the profile, falls back to legacy orchestrator and sets answer.
    llm_generate: async callable(prompt, system_prompt) -> str
    """
    if llm_generate is None:
        from app.core.services import get_service_container

        container = get_service_container()
        llm = container._llm_manager.get_provider()

        async def _gen(prompt: str, system_prompt: Optional[str] = None) -> str:
            return await llm.generate(prompt=prompt, system_prompt=system_prompt)

        llm_generate = _gen

    # Apply anti-prompt-injection filter to user-controlled goal (best-effort)
    goal_for_prompt = apply_prompt_injection_filter(
        goal, getattr(settings, "prompt_injection_filter_enabled", True)
    )

    profile = get_agent_profile(agent_profile_id)
    role_prompt = (profile or {}).get(
        "role_prompt"
    ) or "You are a helpful assistant. Output next action as JSON."

    mcp_manager = get_mcp_client_manager()
    tools = mcp_manager.get_tools_for_profile(agent_profile_id) if mcp_manager._initialized else []

    # If no MCP tools, delegate to legacy orchestrator (use filtered goal for consistency)
    if not tools:
        from app.core.services import get_service_container
        from app.models.agent import AgentResult

        container = get_service_container()
        orchestrator = container.get_orchestrator()
        result: AgentResult = await orchestrator.route_task(goal_for_prompt, context)
        answer = ""
        if result.success and result.output:
            answer = (
                str(result.output)
                if not isinstance(result.output, dict)
                else json.dumps(result.output, default=str)
            )
        else:
            answer = result.error or "Orchestrator did not return a result."
        update_run(
            run_id,
            status="completed",
            answer=answer,
            steps=[
                {
                    "step_index": 1,
                    "kind": "finish",
                    "finish_answer": answer,
                    "raw_response": "Legacy orchestrator",
                }
            ],
            tool_calls=[],
            completed_at=datetime.utcnow(),
        )
        return

    update_run(run_id, status="running")
    steps: List[Dict[str, Any]] = []
    tool_calls_records: List[Dict[str, Any]] = []
    conversation: List[str] = []
    tools_text = _format_tools_for_prompt(tools)
    llm_timeout = getattr(settings, "planner_llm_timeout_seconds", 120) or 0

    for step in range(1, MAX_PLANNER_STEPS + 1):
        # Check for cancellation before each step
        run = get_run_by_id(run_id)
        if run and run.status == "cancelled":
            logger.info("Run %s was cancelled", run_id)
            return

        system = f"""{role_prompt}

Available MCP tools (server_id, tool_name, description):
{tools_text}

{STRUCTURAL_INSTRUCTION}

Respond with exactly one JSON object, no other text. Choose one:
1. To call a tool: {{"action": "tool_call", "server_id": "<id>", "tool_name": "<name>", "arguments": {{...}}}}
2. To finish: {{"action": "finish", "answer": "<final answer to the user>"}}
"""

        user_prompt = f"""{USER_GOAL_START}
{goal_for_prompt}
{USER_GOAL_END}

"""
        if conversation:
            user_prompt += "Previous steps and results:\n" + "\n".join(conversation[-10:]) + "\n\n"
        user_prompt += "What is the next action? Reply with one JSON object only."

        try:
            if llm_timeout > 0:
                response = await asyncio.wait_for(
                    llm_generate(user_prompt, system),
                    timeout=float(llm_timeout),
                )
            else:
                response = await llm_generate(user_prompt, system)
        except asyncio.TimeoutError as e:
            logger.exception("Planner LLM call timed out after %ss: %s", llm_timeout, e)
            update_run(
                run_id,
                status="failed",
                error=f"LLM call timed out after {llm_timeout}s",
                steps=steps,
                tool_calls=tool_calls_records,
            )
            return
        except Exception as e:
            logger.exception("Planner LLM call failed: %s", e)
            update_run(
                run_id, status="failed", error=str(e), steps=steps, tool_calls=tool_calls_records
            )
            return

        parsed = _parse_planner_response(response)
        if not parsed:
            conversation.append(f"Step {step} (parse failed): {response[:500]}")
            steps.append({"step_index": step, "kind": "unknown", "raw_response": response[:500]})
            continue

        if parsed.get("action") == "finish":
            answer = parsed.get("answer", "")
            steps.append(
                {
                    "step_index": step,
                    "kind": "finish",
                    "finish_answer": answer,
                    "raw_response": response[:300],
                }
            )
            update_run(
                run_id,
                status="completed",
                answer=answer,
                steps=steps,
                tool_calls=tool_calls_records,
                completed_at=datetime.utcnow(),
            )
            return

        if parsed.get("action") == "tool_call":
            server_id = parsed.get("server_id", "")
            tool_name = parsed.get("tool_name", "")
            arguments = parsed.get("arguments") or {}
            try:
                result = await mcp_manager.call_tool(server_id, tool_name, arguments)
            except Exception as e:
                result = {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}
            result_text = ""
            if isinstance(result.get("content"), list):
                for c in result["content"]:
                    if isinstance(c, dict) and c.get("type") == "text":
                        result_text += c.get("text", "")
            else:
                result_text = str(result)
            is_error = result.get("isError", False)
            tool_calls_records.append(
                {
                    "server_id": server_id,
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "result_summary": result_text[:500],
                    "is_error": is_error,
                }
            )
            steps.append(
                {
                    "step_index": step,
                    "kind": "tool_call",
                    "tool_call": {
                        "server_id": server_id,
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "result_summary": result_text[:500],
                        "is_error": is_error,
                    },
                    "raw_response": response[:300],
                }
            )
            conversation.append(f"Tool call: {server_id}/{tool_name} -> {result_text[:300]}")
            if is_error:
                conversation.append(
                    "(Tool returned an error; consider finishing with what we have or trying another action.)"
                )

    # Max steps reached
    update_run(
        run_id,
        status="completed",
        answer="Reached maximum steps without explicit finish.",
        steps=steps,
        tool_calls=tool_calls_records,
        completed_at=datetime.utcnow(),
    )
