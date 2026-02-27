"""Unit tests for app/planner/loop.py — planner response parsing and step execution."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.planner.loop import (
    _conversation_from_steps_and_tool_calls,
    _format_tools_for_prompt,
    _parse_planner_response,
)

# ---------------------------------------------------------------------------
# Pure-function tests (no I/O)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseplannerResponse:
    """Tests for _parse_planner_response."""

    def test_parse_tool_call(self):
        response = '{"action": "tool_call", "server_id": "srv", "tool_name": "ping", "arguments": {"host": "example.com"}}'
        result = _parse_planner_response(response)
        assert result is not None
        assert result["action"] == "tool_call"
        assert result["server_id"] == "srv"
        assert result["tool_name"] == "ping"
        assert result["arguments"] == {"host": "example.com"}

    def test_parse_finish(self):
        response = '{"action": "finish", "answer": "All done."}'
        result = _parse_planner_response(response)
        assert result is not None
        assert result["action"] == "finish"
        assert result["answer"] == "All done."

    def test_parse_finish_fallback_keyword(self):
        """FINISH keyword in response triggers finish fallback."""
        response = "I have completed the task. FINISH"
        result = _parse_planner_response(response)
        assert result is not None
        assert result["action"] == "finish"

    def test_parse_invalid_json_returns_none(self):
        response = "Sorry, I cannot do that."
        result = _parse_planner_response(response)
        assert result is None

    def test_parse_tool_call_missing_server_id_returns_none(self):
        response = '{"action": "tool_call", "tool_name": "ping", "arguments": {}}'
        result = _parse_planner_response(response)
        assert result is None

    def test_parse_empty_response_returns_none(self):
        result = _parse_planner_response("")
        assert result is None

    def test_parse_tool_call_with_extra_text(self):
        """JSON embedded in surrounding text should still parse."""
        response = 'Here is my plan: {"action": "tool_call", "server_id": "s", "tool_name": "t", "arguments": {}}'
        result = _parse_planner_response(response)
        assert result is not None
        assert result["action"] == "tool_call"

    def test_parse_tool_call_empty_arguments_defaults(self):
        """Missing arguments key should default to {}."""
        response = '{"action": "tool_call", "server_id": "s", "tool_name": "t"}'
        result = _parse_planner_response(response)
        assert result is not None
        assert result["arguments"] == {}


@pytest.mark.unit
class TestFormatToolsForPrompt:
    """Tests for _format_tools_for_prompt."""

    def test_empty_tools(self):
        result = _format_tools_for_prompt([])
        assert "No tools available" in result

    def test_single_tool(self):
        tools = [{"server_id": "srv1", "name": "ping", "description": "Ping a host"}]
        result = _format_tools_for_prompt(tools)
        assert "srv1" in result
        assert "ping" in result
        assert "Ping a host" in result

    def test_multiple_tools(self):
        tools = [
            {"server_id": "srv1", "name": "ping", "description": "Ping"},
            {"server_id": "srv2", "name": "dns", "description": "DNS lookup"},
        ]
        result = _format_tools_for_prompt(tools)
        assert "ping" in result
        assert "dns" in result
        assert result.count("\n") >= 1

    def test_missing_description_doesnt_crash(self):
        tools = [{"server_id": "s", "name": "t"}]
        result = _format_tools_for_prompt(tools)
        assert "t" in result


@pytest.mark.unit
class TestConversationFromSteps:
    """Tests for _conversation_from_steps_and_tool_calls."""

    def test_empty_steps(self):
        result = _conversation_from_steps_and_tool_calls([], [])
        assert result == []

    def test_tool_call_steps_produce_lines(self):
        steps = [
            {
                "kind": "tool_call",
                "step_index": 1,
                "tool_call": {
                    "server_id": "srv",
                    "tool_name": "ping",
                    "result_summary": "Success",
                },
            }
        ]
        result = _conversation_from_steps_and_tool_calls(steps, [])
        assert len(result) == 1
        assert "ping" in result[0]
        assert "Success" in result[0]

    def test_non_tool_steps_skipped(self):
        steps = [{"kind": "finish", "step_index": 1, "finish_answer": "done"}]
        result = _conversation_from_steps_and_tool_calls(steps, [])
        assert result == []


# ---------------------------------------------------------------------------
# Async integration-style tests (with mocked I/O)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunPlannerLoop:
    """Tests for run_planner_loop — mocked DB and MCP."""

    @patch("app.planner.loop.get_mcp_client_manager")
    @patch("app.planner.loop.get_agent_profile")
    @patch("app.planner.loop.update_run")
    @patch("app.planner.loop.append_run_event")
    async def test_no_mcp_tools_fails_with_descriptive_error(
        self, mock_append, mock_update, mock_profile, mock_mcp
    ):
        """When no MCP tools configured, planner fails the run with a descriptive error."""
        from app.planner.loop import run_planner_loop

        mock_update.return_value = None
        mock_append.return_value = None
        mock_profile.return_value = {"role_prompt": "You are helpful."}

        mcp_manager = MagicMock()
        mcp_manager._initialized = True
        mcp_manager.get_tools_for_profile.return_value = []  # no tools
        mock_mcp.return_value = mcp_manager

        async def _dummy_llm(prompt, system_prompt=None):
            return "{}"

        await run_planner_loop("run-1", "Check network", "default", llm_generate=_dummy_llm)

        mock_update.assert_called()
        calls = mock_update.call_args_list
        statuses = [c.kwargs.get("status") for c in calls]
        assert "failed" in statuses
        # Verify error message describes what to do
        error_calls = [c for c in calls if c.kwargs.get("status") == "failed"]
        assert any("No MCP tools" in (c.kwargs.get("error") or "") for c in error_calls)

    @patch("app.planner.loop.get_mcp_client_manager")
    @patch("app.planner.loop.get_agent_profile")
    @patch("app.planner.loop.update_run")
    @patch("app.planner.loop.append_run_event")
    @patch("app.planner.loop.get_run_by_id")
    async def test_finish_action_completes_run(
        self, mock_get_run, mock_append, mock_update, mock_profile, mock_mcp
    ):
        """Planner loop marks run complete when LLM returns finish action."""
        from app.planner.loop import run_planner_loop

        mock_update.return_value = None
        mock_append.return_value = None
        mock_profile.return_value = {"role_prompt": "You are helpful."}

        # Run is not cancelled
        mock_run = MagicMock()
        mock_run.status = "running"
        mock_get_run.return_value = mock_run

        mcp_manager = MagicMock()
        mcp_manager._initialized = True
        mcp_manager.get_tools_for_profile.return_value = [
            {"server_id": "s", "name": "ping", "description": "Ping"}
        ]
        mock_mcp.return_value = mcp_manager

        finish_json = '{"action": "finish", "answer": "All looks good."}'

        with patch("app.core.services.get_service_container") as mock_svc:
            llm = AsyncMock()
            llm.generate.return_value = finish_json
            container = MagicMock()
            container.get_llm_manager.return_value.get_provider.return_value = llm
            mock_svc.return_value = container

            await run_planner_loop("run-2", "Check network", "default")

        # Verify run was completed
        update_calls = mock_update.call_args_list
        statuses = [c.kwargs.get("status") for c in update_calls]
        assert "completed" in statuses

    @patch("app.planner.loop.get_mcp_client_manager")
    @patch("app.planner.loop.get_agent_profile")
    @patch("app.planner.loop.update_run")
    @patch("app.planner.loop.append_run_event")
    @patch("app.planner.loop.get_run_by_id")
    async def test_tool_call_then_finish(
        self, mock_get_run, mock_append, mock_update, mock_profile, mock_mcp
    ):
        """Planner executes a tool call then finishes on next step."""
        from app.planner.loop import run_planner_loop

        mock_update.return_value = None
        mock_append.return_value = None
        mock_profile.return_value = {"role_prompt": "You are helpful.", "approval_required_tools": []}

        mock_run = MagicMock()
        mock_run.status = "running"
        mock_get_run.return_value = mock_run

        mcp_manager = MagicMock()
        mcp_manager._initialized = True
        mcp_manager.get_tools_for_profile.return_value = [
            {"server_id": "net", "name": "ping", "description": "Ping a host"}
        ]
        mcp_manager.call_tool = AsyncMock(return_value={
            "content": [{"type": "text", "text": "Ping OK"}],
            "isError": False,
        })
        mock_mcp.return_value = mcp_manager

        tool_json = '{"action": "tool_call", "server_id": "net", "tool_name": "ping", "arguments": {"host": "8.8.8.8"}}'
        finish_json = '{"action": "finish", "answer": "Network is healthy."}'

        responses = iter([tool_json, finish_json])

        async def fake_generate(prompt, system_prompt=None):
            return next(responses)

        with patch("app.core.services.get_service_container") as mock_svc:
            llm = MagicMock()
            llm.generate = fake_generate
            container = MagicMock()
            container.get_llm_manager.return_value.get_provider.return_value = llm
            mock_svc.return_value = container

            await run_planner_loop("run-3", "Check network", "default")

        mcp_manager.call_tool.assert_called_once_with("net", "ping", {"host": "8.8.8.8"})
        update_calls = mock_update.call_args_list
        statuses = [c.kwargs.get("status") for c in update_calls]
        assert "completed" in statuses

    @patch("app.planner.loop.get_mcp_client_manager")
    @patch("app.planner.loop.get_agent_profile")
    @patch("app.planner.loop.update_run")
    @patch("app.planner.loop.append_run_event")
    @patch("app.planner.loop.get_run_by_id")
    async def test_cancelled_run_exits_early(
        self, mock_get_run, mock_append, mock_update, mock_profile, mock_mcp
    ):
        """Planner exits without completing when run is cancelled."""
        from app.planner.loop import run_planner_loop

        mock_update.return_value = None
        mock_append.return_value = None
        mock_profile.return_value = {"role_prompt": "You are helpful."}

        # Run is cancelled
        mock_run = MagicMock()
        mock_run.status = "cancelled"
        mock_get_run.return_value = mock_run

        mcp_manager = MagicMock()
        mcp_manager._initialized = True
        mcp_manager.get_tools_for_profile.return_value = [
            {"server_id": "s", "name": "t", "description": "tool"}
        ]
        mock_mcp.return_value = mcp_manager

        with patch("app.core.services.get_service_container") as mock_svc:
            container = MagicMock()
            container.get_llm_manager.return_value.get_provider.return_value = AsyncMock()
            mock_svc.return_value = container

            await run_planner_loop("run-4", "Do something", "default")

        # update_run should only have been called for status=running at the start
        # and NOT for completed/failed (cancelled → early exit)
        update_calls = mock_update.call_args_list
        statuses = [c.kwargs.get("status") for c in update_calls]
        assert "completed" not in statuses

    @patch("app.planner.loop.get_mcp_client_manager")
    @patch("app.planner.loop.get_agent_profile")
    @patch("app.planner.loop.update_run")
    @patch("app.planner.loop.append_run_event")
    @patch("app.planner.loop.get_run_by_id")
    async def test_hitl_awaiting_approval(
        self, mock_get_run, mock_append, mock_update, mock_profile, mock_mcp
    ):
        """Planner pauses and marks awaiting_approval for protected tools."""
        from app.planner.loop import run_planner_loop

        mock_update.return_value = None
        mock_append.return_value = None
        mock_profile.return_value = {
            "role_prompt": "Be helpful.",
            "approval_required_tools": ["dangerous_tool"],
        }

        mock_run = MagicMock()
        mock_run.status = "running"
        mock_get_run.return_value = mock_run

        mcp_manager = MagicMock()
        mcp_manager._initialized = True
        mcp_manager.get_tools_for_profile.return_value = [
            {"server_id": "s", "name": "dangerous_tool", "description": "Danger"}
        ]
        mock_mcp.return_value = mcp_manager

        tool_json = '{"action": "tool_call", "server_id": "s", "tool_name": "dangerous_tool", "arguments": {}}'

        with patch("app.core.services.get_service_container") as mock_svc:
            llm = MagicMock()
            llm.generate = AsyncMock(return_value=tool_json)
            container = MagicMock()
            container.get_llm_manager.return_value.get_provider.return_value = llm
            mock_svc.return_value = container

            await run_planner_loop("run-5", "Do something dangerous", "default")

        update_calls = mock_update.call_args_list
        statuses = [c.kwargs.get("status") for c in update_calls]
        assert "awaiting_approval" in statuses

    @patch("app.planner.loop.get_mcp_client_manager")
    @patch("app.planner.loop.get_agent_profile")
    @patch("app.planner.loop.update_run")
    @patch("app.planner.loop.append_run_event")
    @patch("app.planner.loop.get_run_by_id")
    async def test_max_steps_auto_completes_run(
        self, mock_get_run, mock_append, mock_update, mock_profile, mock_mcp
    ):
        """Planner marks run completed with fallback answer after MAX_PLANNER_STEPS."""
        from app.planner.loop import run_planner_loop

        mock_update.return_value = None
        mock_append.return_value = None
        mock_profile.return_value = {"role_prompt": "You are helpful.", "approval_required_tools": []}

        mock_run = MagicMock()
        mock_run.status = "running"
        mock_get_run.return_value = mock_run

        mcp_manager = MagicMock()
        mcp_manager._initialized = True
        mcp_manager.get_tools_for_profile.return_value = [
            {"server_id": "s", "name": "t", "description": "tool"}
        ]
        mock_mcp.return_value = mcp_manager

        # Always return an unparseable response so the loop never finishes naturally
        async def _unparseable(prompt, system_prompt=None):
            return "I cannot decide yet."

        await run_planner_loop("run-6", "Long task", "default", llm_generate=_unparseable)

        update_calls = mock_update.call_args_list
        statuses = [c.kwargs.get("status") for c in update_calls]
        assert "completed" in statuses
        # Check the max-steps answer was used
        answers = [c.kwargs.get("answer") for c in update_calls if c.kwargs.get("answer")]
        assert any("maximum steps" in (a or "") for a in answers)

    @patch("app.planner.loop.get_mcp_client_manager")
    @patch("app.planner.loop.get_agent_profile")
    @patch("app.planner.loop.update_run")
    @patch("app.planner.loop.append_run_event")
    @patch("app.planner.loop.get_run_by_id")
    async def test_tool_timeout_continues_loop(
        self, mock_get_run, mock_append, mock_update, mock_profile, mock_mcp
    ):
        """Tool execution timeout is recorded as an error step and the loop continues."""
        from app.core.config import settings
        from app.planner.loop import run_planner_loop

        mock_update.return_value = None
        mock_append.return_value = None
        mock_profile.return_value = {"role_prompt": "You are helpful.", "approval_required_tools": []}

        mock_run = MagicMock()
        mock_run.status = "running"
        mock_get_run.return_value = mock_run

        mcp_manager = MagicMock()
        mcp_manager._initialized = True
        mcp_manager.get_tools_for_profile.return_value = [
            {"server_id": "net", "name": "ping", "description": "Ping"}
        ]
        # call_tool raises TimeoutError
        mcp_manager.call_tool = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_mcp.return_value = mcp_manager

        tool_json = '{"action": "tool_call", "server_id": "net", "tool_name": "ping", "arguments": {}}'
        finish_json = '{"action": "finish", "answer": "Done despite timeout."}'
        responses = iter([tool_json, finish_json])

        async def fake_generate(prompt, system_prompt=None):
            return next(responses)

        original_timeout = settings.planner_tool_timeout_seconds
        try:
            settings.planner_tool_timeout_seconds = 1  # allow wait_for to wrap
            await run_planner_loop("run-7", "Check network", "default", llm_generate=fake_generate)
        finally:
            settings.planner_tool_timeout_seconds = original_timeout

        update_calls = mock_update.call_args_list
        statuses = [c.kwargs.get("status") for c in update_calls]
        # Loop should continue after timeout and eventually complete
        assert "completed" in statuses


@pytest.mark.unit
class TestExecuteApprovedTool:
    """Tests for execute_approved_tool_and_update_run."""

    @patch("app.planner.loop.get_run_by_id")
    async def test_returns_false_when_run_not_found(self, mock_get_run):
        from app.planner.loop import execute_approved_tool_and_update_run

        mock_get_run.return_value = None
        result = await execute_approved_tool_and_update_run("nonexistent")
        assert result is False

    @patch("app.planner.loop.get_run_by_id")
    async def test_returns_false_when_not_awaiting_approval(self, mock_get_run):
        from app.planner.loop import execute_approved_tool_and_update_run

        mock_run = MagicMock()
        mock_run.status = "running"
        mock_run.pending_tool_call = None
        mock_get_run.return_value = mock_run
        result = await execute_approved_tool_and_update_run("run-1")
        assert result is False

    @patch("app.planner.loop.update_run")
    @patch("app.planner.loop.append_run_event")
    @patch("app.planner.loop.get_mcp_client_manager")
    @patch("app.planner.loop.get_run_by_id")
    async def test_executes_approved_tool_and_returns_true(
        self, mock_get_run, mock_mcp, mock_append, mock_update
    ):
        from app.planner.loop import execute_approved_tool_and_update_run

        mock_update.return_value = None
        mock_append.return_value = None

        mock_run = MagicMock()
        mock_run.status = "awaiting_approval"
        mock_run.pending_tool_call = {
            "server_id": "net",
            "tool_name": "ping",
            "arguments": {"host": "1.2.3.4"},
            "step_index": 2,
        }
        mock_run.steps = []
        mock_run.tool_calls = []
        mock_get_run.return_value = mock_run

        mcp_manager = MagicMock()
        mcp_manager.call_tool = AsyncMock(return_value={
            "content": [{"type": "text", "text": "Ping OK"}],
            "isError": False,
        })
        mock_mcp.return_value = mcp_manager

        result = await execute_approved_tool_and_update_run("run-6")

        assert result is True
        mcp_manager.call_tool.assert_called_once_with("net", "ping", {"host": "1.2.3.4"})
        mock_update.assert_called()


@pytest.mark.unit
class TestWorkflowConditionEvaluator:
    """Tests for the safe AST condition evaluator via workflow_executor."""

    def _executor(self):
        from app.core.workflow_executor import WorkflowExecutor
        return WorkflowExecutor(orchestrator=MagicMock())

    def test_no_condition_returns_true(self):
        ex = self._executor()
        assert ex._evaluate_condition(None, {}) is True
        assert ex._evaluate_condition("", {}) is True

    def test_simple_equality(self):
        ex = self._executor()
        assert ex._evaluate_condition("context.get('status') == 'ok'", {"status": "ok"}) is True
        assert ex._evaluate_condition("context.get('status') == 'ok'", {"status": "fail"}) is False

    def test_boolean_and(self):
        ex = self._executor()
        ctx = {"a": True, "b": True}
        assert ex._evaluate_condition("context.get('a') and context.get('b')", ctx) is True

    def test_boolean_or(self):
        ex = self._executor()
        ctx = {"x": False, "y": True}
        assert ex._evaluate_condition("context.get('x') or context.get('y')", ctx) is True

    def test_not_operator(self):
        ex = self._executor()
        assert ex._evaluate_condition("not context.get('error')", {"error": False}) is True

    def test_in_operator(self):
        ex = self._executor()
        assert ex._evaluate_condition("'foo' in context.get('tags', [])", {"tags": ["foo", "bar"]}) is True

    def test_numeric_comparison(self):
        ex = self._executor()
        assert ex._evaluate_condition("context.get('count') > 5", {"count": 10}) is True
        assert ex._evaluate_condition("context.get('count') > 5", {"count": 3}) is False

    def test_bad_expression_returns_false(self):
        """Expressions that fail to evaluate should return False (skip step) not crash."""
        ex = self._executor()
        assert ex._evaluate_condition("this is not valid python !!!", {}) is False

    def test_blocked_import(self):
        """import statements must not be allowed."""
        ex = self._executor()
        assert ex._evaluate_condition("__import__('os').getcwd()", {}) is False

    def test_blocked_arbitrary_name(self):
        """Accessing names other than 'context' must fail safely."""
        ex = self._executor()
        assert ex._evaluate_condition("open('/etc/passwd').read()", {}) is False
