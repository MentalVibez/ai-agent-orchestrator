"""
Minimal planner loop: given goal and allowed MCP tools, prompt LLM for next action
(tool call or FINISH); execute tool, append to context, repeat until FINISH or max steps.
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.prompt_injection import (
    STRUCTURAL_INSTRUCTION,
    USER_GOAL_END,
    USER_GOAL_START,
    apply_prompt_injection_filter,
    sanitize_user_input,
)
from app.core.run_store import append_run_event, get_run_by_id, update_run
from app.mcp.client_manager import get_mcp_client_manager
from app.mcp.config_loader import get_agent_profile
from app.observability.tracing import trace_run, trace_step, trace_tool_call

logger = logging.getLogger(__name__)

MAX_PLANNER_STEPS = 15


def _conversation_from_steps_and_tool_calls(
    steps: List[Dict[str, Any]], tool_calls_records: List[Dict[str, Any]]
) -> List[str]:
    """Build conversation history from steps and tool_calls for resume."""
    lines: List[str] = []
    for i, step in enumerate(steps):
        if step.get("kind") == "tool_call" and "tool_call" in step:
            tc = step["tool_call"]
            server_id = tc.get("server_id", "")
            tool_name = tc.get("tool_name", "")
            summary = (tc.get("result_summary") or "")[:300]
            lines.append(f"Tool call: {server_id}/{tool_name} -> {summary}")
    return lines


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


async def _run_planner_steps(
    run_id: str,
    goal_for_prompt: str,
    role_prompt: str,
    tools_text: str,
    tools: List[Dict[str, Any]],
    filter_enabled: bool,
    llm_generate: Any,
    llm_timeout: int,
    steps: List[Dict[str, Any]],
    tool_calls_records: List[Dict[str, Any]],
    conversation: List[str],
    mcp_manager: Any,
    approval_required_tools: Optional[List[str]] = None,
    start_step: int = 1,
    stream_tokens: bool = False,
) -> None:
    """Execute planner steps (LLM + tool calls) with tracing. Mutates steps, tool_calls_records, conversation.
    approval_required_tools: tool names that require HITL approval before execution.
    start_step: step index to start from (for resume after approval).
    stream_tokens: when True, stream LLM output and emit token events for SSE."""
    if approval_required_tools is None:
        approval_required_tools = []
    for step in range(start_step, MAX_PLANNER_STEPS + 1):
        run = await get_run_by_id(run_id)
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

        async def _get_llm_response() -> str:
            if stream_tokens:
                from app.core.services import get_service_container
                llm = get_service_container()._llm_manager.get_provider()
                full: List[str] = []
                try:
                    async for chunk in llm.stream(user_prompt, system_prompt=system):
                        await append_run_event(run_id, "token", {"text": chunk})
                        full.append(chunk)
                    return "".join(full)
                except Exception as e:
                    logger.warning("LLM stream failed, falling back to generate: %s", e)
                    return await llm_generate(user_prompt, system)
            return await llm_generate(user_prompt, system)

        with trace_step(run_id, step):
            try:
                if llm_timeout > 0:
                    response = await asyncio.wait_for(
                        _get_llm_response(),
                        timeout=float(llm_timeout),
                    )
                else:
                    response = await _get_llm_response()
            except asyncio.TimeoutError as e:
                logger.exception("Planner LLM call timed out after %ss: %s", llm_timeout, e)
                await update_run(
                    run_id,
                    status="failed",
                    error=f"LLM call timed out after {llm_timeout}s",
                    steps=steps,
                    tool_calls=tool_calls_records,
                )
                await append_run_event(
                    run_id,
                    "status",
                    {"status": "failed", "error": f"LLM call timed out after {llm_timeout}s"},
                )
                return
            except Exception as e:
                logger.exception("Planner LLM call failed: %s", e)
                await update_run(
                    run_id,
                    status="failed",
                    error=str(e),
                    steps=steps,
                    tool_calls=tool_calls_records,
                )
                await append_run_event(run_id, "status", {"status": "failed", "error": str(e)})
                return

            parsed = _parse_planner_response(response)
            if not parsed:
                conversation.append(f"Step {step} (parse failed): {response[:500]}")
                step_data = {"step_index": step, "kind": "unknown", "raw_response": response[:500]}
                steps.append(step_data)
                await append_run_event(run_id, "step", step_data)
                continue

            if parsed.get("action") == "finish":
                answer = parsed.get("answer", "")
                step_data = {
                    "step_index": step,
                    "kind": "finish",
                    "finish_answer": answer,
                    "raw_response": response[:300],
                }
                steps.append(step_data)
                await update_run(
                    run_id,
                    status="completed",
                    answer=answer,
                    steps=steps,
                    tool_calls=tool_calls_records,
                    completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
                await append_run_event(run_id, "step", step_data)
                await append_run_event(run_id, "status", {"status": "completed"})
                await append_run_event(run_id, "answer", {"answer": answer})
                return

            if parsed.get("action") == "tool_call":
                server_id = parsed.get("server_id", "")
                tool_name = parsed.get("tool_name", "")
                arguments = parsed.get("arguments") or {}
                if tool_name in approval_required_tools:
                    pending = {
                        "server_id": server_id,
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "step_index": step,
                    }
                    await update_run(
                        run_id,
                        status="awaiting_approval",
                        steps=steps,
                        tool_calls=tool_calls_records,
                        pending_tool_call=pending,
                    )
                    await append_run_event(
                        run_id,
                        "status",
                        {"status": "awaiting_approval", "pending_tool_call": pending},
                    )
                    return
                with trace_tool_call(run_id, server_id, tool_name):
                    try:
                        tool_timeout = settings.planner_tool_timeout_seconds
                        if tool_timeout > 0:
                            result = await asyncio.wait_for(
                                mcp_manager.call_tool(server_id, tool_name, arguments),
                                timeout=float(tool_timeout),
                            )
                        else:
                            result = await mcp_manager.call_tool(server_id, tool_name, arguments)
                    except asyncio.TimeoutError:
                        timeout_msg = (
                            f"[TIMEOUT] Tool {tool_name} did not respond within "
                            f"{settings.planner_tool_timeout_seconds}s"
                        )
                        result = {"content": [{"type": "text", "text": timeout_msg}], "isError": True}
                    except Exception as e:
                        result = {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}
                result_text = ""
                if isinstance(result.get("content"), list):
                    for c in result["content"]:
                        if isinstance(c, dict) and c.get("type") == "text":
                            result_text += c.get("text", "")
                else:
                    result_text = str(result)
                if filter_enabled:
                    result_text = sanitize_user_input(result_text)
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
                step_data = {
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
                steps.append(step_data)
                await append_run_event(run_id, "step", step_data)
                # Checkpoint: persist step index so resume can skip completed steps
                await update_run(
                    run_id,
                    checkpoint_step_index=step,
                    steps=steps,
                    tool_calls=tool_calls_records,
                )
                conversation.append(f"Tool call: {server_id}/{tool_name} -> {result_text[:300]}")
                if is_error:
                    conversation.append(
                        "(Tool returned an error; consider finishing with what we have or trying another action.)"
                    )

    answer_max = "Reached maximum steps without explicit finish."
    await update_run(
        run_id,
        status="completed",
        answer=answer_max,
        steps=steps,
        tool_calls=tool_calls_records,
        completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    await append_run_event(run_id, "status", {"status": "completed"})
    await append_run_event(run_id, "answer", {"answer": answer_max})


async def run_planner_loop(
    run_id: str,
    goal: str,
    agent_profile_id: str,
    context: Optional[Dict[str, Any]] = None,
    llm_generate: Optional[Any] = None,
    request_id: Optional[str] = None,
    llm_manager: Optional[Any] = None,
) -> None:
    """
    Run the planner loop for the given run. Updates run in DB (steps, tool_calls, status, answer).
    If no MCP tools are available for the profile, fails the run with a descriptive error.
    llm_generate: async callable(prompt, system_prompt) -> str
    request_id: optional correlation ID from the originating HTTP request (for log tracing)
    llm_manager: optional LLMManager instance; used when llm_generate is not provided.
                 Falls back to the global service container for backward compat (e.g. arq worker).
    """
    _req_tag = f"[req:{request_id}] " if request_id else ""
    if llm_generate is None:
        if llm_manager is None:
            from app.core.services import get_service_container  # backward compat for arq worker

            llm_manager = get_service_container().get_llm_manager()
        llm = llm_manager.get_provider()

        async def _gen(prompt: str, system_prompt: Optional[str] = None) -> str:
            return await llm.generate(prompt=prompt, system_prompt=system_prompt)

        llm_generate = _gen

    filter_enabled = getattr(settings, "prompt_injection_filter_enabled", True)

    # Apply anti-prompt-injection filter to user-controlled goal (best-effort)
    goal_for_prompt = apply_prompt_injection_filter(goal, filter_enabled)

    # Security: sanitize all string values in context — context can come from alert payloads,
    # user input, or other external sources and must not reach the LLM unsanitized.
    if context and filter_enabled:
        sanitized_context: Dict[str, Any] = {}
        for k, v in context.items():
            if isinstance(v, str):
                sanitized_context[k] = sanitize_user_input(v)
            else:
                sanitized_context[k] = v
        context = sanitized_context

    profile = get_agent_profile(agent_profile_id)
    role_prompt = (profile or {}).get(
        "role_prompt"
    ) or "You are a helpful assistant. Output next action as JSON."

    mcp_manager = get_mcp_client_manager()
    tools = mcp_manager.get_tools_for_profile(agent_profile_id) if mcp_manager._initialized else []

    # No MCP tools configured for this profile — fail immediately with a clear error
    if not tools:
        logger.error(
            "No MCP tools available for profile '%s'. "
            "Add MCP server IDs to allowed_mcp_servers in config/agent_profiles.yaml.",
            agent_profile_id,
        )
        await update_run(
            run_id,
            status="failed",
            error=(
                f"No MCP tools available for agent profile '{agent_profile_id}'. "
                "Configure allowed_mcp_servers in config/agent_profiles.yaml."
            ),
        )
        return

    logger.info("%sStarting planner loop run_id=%s profile=%s", _req_tag, run_id, agent_profile_id)
    await update_run(run_id, status="running")
    await append_run_event(run_id, "status", {"status": "running"})
    steps: List[Dict[str, Any]] = []
    tool_calls_records: List[Dict[str, Any]] = []
    conversation: List[str] = []
    tools_text = _format_tools_for_prompt(tools)
    llm_timeout = getattr(settings, "planner_llm_timeout_seconds", 120) or 0

    approval_required_tools = (profile or {}).get("approval_required_tools") or []
    stream_tokens = (context or {}).get("_stream_tokens") is True
    with trace_run(run_id, goal):
        await _run_planner_steps(
            run_id=run_id,
            goal_for_prompt=goal_for_prompt,
            role_prompt=role_prompt,
            tools_text=tools_text,
            tools=tools,
            filter_enabled=filter_enabled,
            llm_generate=llm_generate,
            llm_timeout=llm_timeout,
            steps=steps,
            tool_calls_records=tool_calls_records,
            conversation=conversation,
            mcp_manager=mcp_manager,
            approval_required_tools=approval_required_tools,
            stream_tokens=stream_tokens,
        )


async def execute_approved_tool_and_update_run(
    run_id: str,
    modified_arguments: Optional[Dict[str, Any]] = None,
    approver_id: str = "unknown",
) -> bool:
    """
    Execute the pending tool call (with optional modified_arguments), append to run steps/tool_calls,
    clear pending_tool_call, set status running. Returns True on success.
    approver_id: identifier of the approver (e.g. API key prefix) for audit logging.
    """
    run = await get_run_by_id(run_id)
    if not run or run.status != "awaiting_approval" or not run.pending_tool_call:
        return False
    pending = run.pending_tool_call
    server_id = pending.get("server_id", "")
    tool_name = pending.get("tool_name", "")
    arguments = modified_arguments if modified_arguments is not None else pending.get("arguments") or {}
    mcp_manager = get_mcp_client_manager()
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
    filter_enabled = getattr(settings, "prompt_injection_filter_enabled", True)
    if filter_enabled:
        result_text = sanitize_user_input(result_text)
    is_error = result.get("isError", False)
    step_index = pending.get("step_index", len((run.steps or [])) + 1)
    tool_call_record = {
        "server_id": server_id,
        "tool_name": tool_name,
        "arguments": arguments,
        "result_summary": result_text[:500],
        "is_error": is_error,
    }
    step_data = {
        "step_index": step_index,
        "kind": "tool_call",
        "tool_call": {
            "server_id": server_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "result_summary": result_text[:500],
            "is_error": is_error,
        },
        "raw_response": "(approved)",
    }
    steps_new = list(run.steps or [])
    tool_calls_new = list(run.tool_calls or [])
    steps_new.append(step_data)
    tool_calls_new.append(tool_call_record)
    await update_run(
        run_id,
        status="running",
        steps=steps_new,
        tool_calls=tool_calls_new,
        _clear_pending_tool_call=True,
    )
    await append_run_event(run_id, "step", step_data)
    await append_run_event(run_id, "status", {"status": "running"})
    # Audit trail: record who approved, when, and whether arguments were modified
    await append_run_event(
        run_id,
        "audit",
        {
            "action": "tool_approved",
            "tool_name": tool_name,
            "server_id": server_id,
            "approver_id": approver_id,
            "arguments_modified": modified_arguments is not None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
    return True


async def resume_planner_loop(run_id: str, llm_manager: Optional[Any] = None) -> None:
    """
    Resume the planner after a pending tool call was approved and executed.
    Loads run state (steps, tool_calls), reconstructs conversation, and continues from the next step.
    llm_manager: optional LLMManager; falls back to global service container (for arq worker compat).
    """
    run = await get_run_by_id(run_id)
    if not run or run.status != "running":
        logger.warning("resume_planner_loop: run %s not found or not running", run_id)
        return
    goal = run.goal
    agent_profile_id = run.agent_profile_id
    profile = get_agent_profile(agent_profile_id)
    role_prompt = (profile or {}).get("role_prompt") or "You are a helpful assistant. Output next action as JSON."
    filter_enabled = getattr(settings, "prompt_injection_filter_enabled", True)
    goal_for_prompt = apply_prompt_injection_filter(goal, filter_enabled)
    mcp_manager = get_mcp_client_manager()
    tools = mcp_manager.get_tools_for_profile(agent_profile_id) if mcp_manager._initialized else []
    if not tools:
        logger.warning("resume_planner_loop: no MCP tools for profile %s", agent_profile_id)
        return
    tools_text = _format_tools_for_prompt(tools)
    llm_timeout = getattr(settings, "planner_llm_timeout_seconds", 120) or 0
    steps = list(run.steps or [])
    tool_calls_records = list(run.tool_calls or [])
    conversation = _conversation_from_steps_and_tool_calls(steps, tool_calls_records)
    approval_required_tools = (profile or {}).get("approval_required_tools") or []
    stream_tokens = (run.context or {}).get("_stream_tokens") is True
    if llm_manager is None:
        from app.core.services import get_service_container  # backward compat for arq worker

        llm_manager = get_service_container().get_llm_manager()
    llm = llm_manager.get_provider()

    async def _gen(prompt: str, system_prompt: Optional[str] = None) -> str:
        return await llm.generate(prompt=prompt, system_prompt=system_prompt)

    llm_generate = _gen
    # Resume from last checkpoint, not just len(steps)+1, to handle mid-step crashes
    checkpoint = run.checkpoint_step_index or 0
    start_step = max(checkpoint + 1, len(steps) + 1)
    with trace_run(run_id, goal):
        await _run_planner_steps(
            run_id=run_id,
            goal_for_prompt=goal_for_prompt,
            role_prompt=role_prompt,
            tools_text=tools_text,
            tools=tools,
            filter_enabled=filter_enabled,
            llm_generate=llm_generate,
            llm_timeout=llm_timeout,
            steps=steps,
            tool_calls_records=tool_calls_records,
            conversation=conversation,
            mcp_manager=mcp_manager,
            approval_required_tools=approval_required_tools,
            start_step=start_step,
            stream_tokens=stream_tokens,
        )
