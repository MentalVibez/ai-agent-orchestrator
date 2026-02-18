"""Unit tests for HITL (approval-required tools, approve/resume)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.planner.loop import _run_planner_steps, execute_approved_tool_and_update_run


@pytest.mark.unit
class TestApprovalRequiredTools:
    """When a tool is in approval_required_tools, planner sets awaiting_approval and stops."""

    @pytest.mark.asyncio
    async def test_tool_in_approval_list_sets_awaiting_approval(self):
        run_id = "run-hitl-1"
        steps = []
        tool_calls_records = []
        conversation = []
        mock_llm = AsyncMock(
            return_value='{"action": "tool_call", "server_id": "srv", "tool_name": "danger_tool", "arguments": {}}'
        )
        mock_mcp = MagicMock()

        with patch("app.planner.loop.get_run_by_id") as mock_get_run:
            with patch("app.planner.loop.update_run") as mock_update:
                with patch("app.planner.loop.append_run_event"):
                    with patch("app.planner.loop.trace_step"):
                        mock_get_run.return_value = MagicMock(status="running")
                    await _run_planner_steps(
                        run_id=run_id,
                        goal_for_prompt="goal",
                        role_prompt="role",
                        tools_text="tools",
                        tools=[],
                        filter_enabled=False,
                        llm_generate=mock_llm,
                        llm_timeout=0,
                        steps=steps,
                        tool_calls_records=tool_calls_records,
                        conversation=conversation,
                        mcp_manager=mock_mcp,
                        approval_required_tools=["danger_tool"],
                        start_step=1,
                    )
                    mock_update.assert_called()
                    call_kw = mock_update.call_args[1]
                    assert call_kw.get("status") == "awaiting_approval"
                    assert "pending_tool_call" in call_kw
                    assert call_kw["pending_tool_call"]["tool_name"] == "danger_tool"
                    assert call_kw["pending_tool_call"]["server_id"] == "srv"
                    mock_mcp.call_tool.assert_not_called()


@pytest.mark.unit
class TestExecuteApprovedTool:
    """execute_approved_tool_and_update_run only runs when run is awaiting_approval."""

    @pytest.mark.asyncio
    async def test_returns_false_when_run_not_awaiting_approval(self):
        with patch("app.planner.loop.get_run_by_id") as mock_get:
            mock_get.return_value = MagicMock(status="running", pending_tool_call=None)
            result = await execute_approved_tool_and_update_run("run-1")
            assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_run_not_found(self):
        with patch("app.planner.loop.get_run_by_id") as mock_get:
            mock_get.return_value = None
            result = await execute_approved_tool_and_update_run("run-1")
            assert result is False
