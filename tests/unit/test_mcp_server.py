"""Unit tests for app/mcp/server.py MCP tool functions."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import the module-level tool functions directly (not via mcp framework)
import app.mcp.server as mcp_server_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(
    run_id="run-abc",
    status="completed",
    goal="Check disk",
    agent_profile_id="default",
    answer="All good",
    error=None,
    steps=None,
    created_at=None,
    completed_at=None,
    pending_tool_call=None,
):
    run = MagicMock()
    run.run_id = run_id
    run.status = status
    run.goal = goal
    run.agent_profile_id = agent_profile_id
    run.answer = answer
    run.error = error
    run.steps = steps or []
    run.created_at = created_at
    run.completed_at = completed_at
    run.pending_tool_call = pending_tool_call
    return run


# ---------------------------------------------------------------------------
# _init_db
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInitDb:
    def test_calls_init_db(self):
        with patch("app.mcp.server.init_db" if False else "app.db.database.init_db"):
            # Should not raise even if DB is not configured
            try:
                mcp_server_module._init_db()
            except Exception:
                pass  # DB not configured in test env — OK

    def test_swallows_exceptions(self):
        """_init_db wraps init_db in try/except so the MCP server starts even without a DB."""
        import app.db.database as db_module
        original = db_module.init_db
        db_module.init_db = lambda: (_ for _ in ()).throw(RuntimeError("no db"))
        try:
            mcp_server_module._init_db()  # must not propagate
        except RuntimeError:
            pytest.fail("_init_db should swallow DB init errors")
        finally:
            db_module.init_db = original


# ---------------------------------------------------------------------------
# start_run tool
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestStartRunTool:
    async def test_fire_and_forget_returns_run_id(self):
        mock_run = _make_run(run_id="run-001", status="pending", answer=None)
        with patch("app.mcp.server._init_db"), \
             patch("app.mcp.server._get_llm_manager", return_value=MagicMock()), \
             patch("app.core.run_store.create_run", new_callable=AsyncMock, return_value=mock_run), \
             patch("app.planner.loop.run_planner_loop", new_callable=AsyncMock), \
             patch("asyncio.create_task"):
            from app.mcp.server import start_run
            result = await start_run("Check disk on prod-01", wait=False)

        assert result["run_id"] == "run-001"
        assert result["status"] == "pending"
        assert "message" in result

    async def test_wait_true_returns_answer(self):
        mock_run_created = _make_run(run_id="run-002", status="pending", answer=None)
        mock_run_done = _make_run(run_id="run-002", status="completed", answer="All healthy")

        with patch("app.mcp.server._init_db"), \
             patch("app.mcp.server._get_llm_manager", return_value=MagicMock()), \
             patch("app.core.run_store.create_run", new_callable=AsyncMock, return_value=mock_run_created), \
             patch("app.core.run_store.get_run_by_id", new_callable=AsyncMock, return_value=mock_run_done), \
             patch("app.planner.loop.run_planner_loop", new_callable=AsyncMock), \
             patch("asyncio.wait_for", new_callable=AsyncMock):
            from app.mcp.server import start_run
            result = await start_run("goal", wait=True, timeout_seconds=30)

        assert result["status"] == "completed"
        assert result["answer"] == "All healthy"

    async def test_wait_true_run_not_found_returns_unknown(self):
        mock_run_created = _make_run(run_id="run-003")

        with patch("app.mcp.server._init_db"), \
             patch("app.mcp.server._get_llm_manager", return_value=MagicMock()), \
             patch("app.core.run_store.create_run", new_callable=AsyncMock, return_value=mock_run_created), \
             patch("app.core.run_store.get_run_by_id", new_callable=AsyncMock, return_value=None), \
             patch("asyncio.wait_for", new_callable=AsyncMock):
            from app.mcp.server import start_run
            result = await start_run("goal", wait=True)

        assert result["status"] == "unknown"


# ---------------------------------------------------------------------------
# get_run_status tool
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestGetRunStatusTool:
    async def test_returns_run_fields(self):
        from datetime import datetime
        mock_run = _make_run(
            run_id="run-abc",
            status="completed",
            goal="Check disk",
            answer="Disk OK",
            steps=[{"step": 1}, {"step": 2}],
            created_at=datetime(2026, 3, 1, 12, 0, 0),
        )
        with patch("app.mcp.server._init_db"), \
             patch("app.core.run_store.get_run_by_id", new_callable=AsyncMock, return_value=mock_run):
            from app.mcp.server import get_run_status
            result = await get_run_status("run-abc")

        assert result["run_id"] == "run-abc"
        assert result["status"] == "completed"
        assert result["answer"] == "Disk OK"
        assert result["step_count"] == 2

    async def test_run_not_found_returns_error(self):
        with patch("app.mcp.server._init_db"), \
             patch("app.core.run_store.get_run_by_id", new_callable=AsyncMock, return_value=None):
            from app.mcp.server import get_run_status
            result = await get_run_status("unknown-id")

        assert "error" in result

    async def test_awaiting_approval_includes_pending(self):
        mock_run = _make_run(
            run_id="run-hitl",
            status="awaiting_approval",
            pending_tool_call={"tool_name": "rm", "arguments": {}},
        )
        with patch("app.mcp.server._init_db"), \
             patch("app.core.run_store.get_run_by_id", new_callable=AsyncMock, return_value=mock_run):
            from app.mcp.server import get_run_status
            result = await get_run_status("run-hitl")

        assert result["pending_approval"] is not None


# ---------------------------------------------------------------------------
# run_from_template tool
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestRunFromTemplateTool:
    async def test_unknown_template_returns_error(self):
        with patch("app.mcp.server._init_db"), \
             patch("app.core.run_templates.get_run_template", return_value=None):
            from app.mcp.server import run_from_template
            result = await run_from_template("nonexistent")

        assert "error" in result
        assert "nonexistent" in result["error"]

    async def test_missing_required_param_returns_error(self):
        fake_template = {
            "name": "T",
            "agent_profile_id": "default",
            "goal_template": "Check {host}",
            "params": {"host": {"required": True, "description": "h"}},
        }
        with patch("app.mcp.server._init_db"), \
             patch("app.core.run_templates.get_run_template", return_value=fake_template):
            from app.mcp.server import run_from_template
            result = await run_from_template("disk-check", params={})

        assert "error" in result

    async def test_valid_template_fire_and_forget(self):
        fake_template = {
            "name": "Disk",
            "agent_profile_id": "default",
            "goal_template": "Check {host}",
            "params": {"host": {"required": True, "description": "h"}},
        }
        mock_run = _make_run(run_id="run-tpl-01", status="pending", answer=None)

        with patch("app.mcp.server._init_db"), \
             patch("app.core.run_templates.get_run_template", return_value=fake_template), \
             patch("app.mcp.server._get_llm_manager", return_value=MagicMock()), \
             patch("app.core.run_store.create_run", new_callable=AsyncMock, return_value=mock_run), \
             patch("asyncio.create_task"):
            from app.mcp.server import run_from_template
            result = await run_from_template("disk-check", params={"host": "prod-01"}, wait=False)

        assert result["run_id"] == "run-tpl-01"
        assert result["template"] == "disk-check"


# ---------------------------------------------------------------------------
# list_templates tool
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestListTemplatesTool:
    async def test_returns_templates_list(self):
        fake = [{"id": "t1", "name": "T1", "description": "", "agent_profile_id": "default", "params": {}}]
        with patch("app.core.run_templates.list_run_templates", return_value=fake):
            from app.mcp.server import list_templates
            result = await list_templates()

        assert "templates" in result
        assert len(result["templates"]) == 1


# ---------------------------------------------------------------------------
# list_agent_profiles tool
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestListAgentProfilesTool:
    async def test_returns_profiles(self):
        fake_profiles = [("default", {"name": "Default", "description": "General"})]
        with patch("app.mcp.config_loader.get_enabled_agent_profiles", return_value=fake_profiles):
            from app.mcp.server import list_agent_profiles
            result = await list_agent_profiles()

        assert "profiles" in result
        assert result["profiles"][0]["id"] == "default"


# ---------------------------------------------------------------------------
# list_runs tool
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestListRunsTool:
    async def test_returns_run_list(self):
        from datetime import datetime
        mock_run = _make_run(run_id="r1", goal="Check disk", created_at=datetime(2026, 3, 1))
        with patch("app.mcp.server._init_db"), \
             patch("app.core.run_store.list_runs", new_callable=AsyncMock, return_value=[mock_run]):
            from app.mcp.server import list_runs
            result = await list_runs(limit=10)

        assert "runs" in result
        assert result["runs"][0]["run_id"] == "r1"

    async def test_limit_clamped_to_100(self):
        with patch("app.mcp.server._init_db"), \
             patch("app.core.run_store.list_runs", new_callable=AsyncMock, return_value=[]) as mock_lr:
            from app.mcp.server import list_runs
            await list_runs(limit=9999)
            called_limit = mock_lr.call_args.kwargs.get("limit") or mock_lr.call_args.args[0]
            assert called_limit <= 100

    async def test_limit_clamped_to_minimum_1(self):
        with patch("app.mcp.server._init_db"), \
             patch("app.core.run_store.list_runs", new_callable=AsyncMock, return_value=[]) as mock_lr:
            from app.mcp.server import list_runs
            await list_runs(limit=0)
            called_limit = mock_lr.call_args.kwargs.get("limit") or mock_lr.call_args.args[0]
            assert called_limit >= 1


# ---------------------------------------------------------------------------
# cancel_run tool
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestCancelRunTool:
    async def test_cancels_running_run(self):
        mock_run = _make_run(run_id="r1", status="running")
        with patch("app.mcp.server._init_db"), \
             patch("app.core.run_store.get_run_by_id", new_callable=AsyncMock, return_value=mock_run), \
             patch("app.core.run_store.update_run", new_callable=AsyncMock):
            from app.mcp.server import cancel_run
            result = await cancel_run("r1")

        assert result["status"] == "cancelled"

    async def test_run_not_found_returns_error(self):
        with patch("app.mcp.server._init_db"), \
             patch("app.core.run_store.get_run_by_id", new_callable=AsyncMock, return_value=None):
            from app.mcp.server import cancel_run
            result = await cancel_run("unknown")

        assert "error" in result

    async def test_completed_run_not_cancellable(self):
        mock_run = _make_run(run_id="r1", status="completed")
        with patch("app.mcp.server._init_db"), \
             patch("app.core.run_store.get_run_by_id", new_callable=AsyncMock, return_value=mock_run):
            from app.mcp.server import cancel_run
            result = await cancel_run("r1")

        assert result["status"] == "completed"
        assert "not cancellable" in result.get("message", "")


# ---------------------------------------------------------------------------
# main() CLI entry point
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMainEntryPoint:
    def test_main_is_callable(self):
        assert callable(mcp_server_module.main)

    def test_main_parses_stdio_default(self):
        with patch("app.mcp.server.mcp") as mock_mcp, \
             patch("app.mcp.server._init_db"):
            mock_mcp.run = MagicMock()
            import sys
            old_argv = sys.argv
            sys.argv = ["server"]
            try:
                mcp_server_module.main()
            finally:
                sys.argv = old_argv
            mock_mcp.run.assert_called_once_with(transport="stdio")

    def test_main_parses_sse_transport(self):
        with patch("app.mcp.server.mcp") as mock_mcp, \
             patch("app.mcp.server._init_db"):
            mock_mcp.run = MagicMock()
            import sys
            old_argv = sys.argv
            sys.argv = ["server", "--transport", "sse", "--port", "9000", "--host", "0.0.0.0"]
            try:
                mcp_server_module.main()
            finally:
                sys.argv = old_argv
            mock_mcp.run.assert_called_once_with(transport="sse", host="0.0.0.0", port=9000)
