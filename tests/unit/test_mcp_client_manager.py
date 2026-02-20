"""Unit tests for app/mcp/client_manager.py — MCPClientManager."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manager():
    """Return a fresh MCPClientManager without calling initialize()."""
    from app.mcp.client_manager import MCPClientManager
    return MCPClientManager()


# ---------------------------------------------------------------------------
# Sync method tests (no asyncio)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetAllTools:
    """Tests for MCPClientManager.get_all_tools()."""

    def test_returns_empty_list_when_no_tools_cached(self):
        mgr = _make_manager()
        assert mgr.get_all_tools() == []

    def test_returns_flattened_list_with_server_id(self):
        mgr = _make_manager()
        mgr._tools_cache = {
            "srv-a": [{"name": "tool1", "description": "d1", "inputSchema": {"type": "object"}}],
            "srv-b": [{"name": "tool2", "description": "d2", "inputSchema": {}}],
        }
        result = mgr.get_all_tools()
        assert len(result) == 2
        assert result[0]["server_id"] == "srv-a"
        assert result[0]["name"] == "tool1"
        assert result[1]["server_id"] == "srv-b"
        assert result[1]["name"] == "tool2"

    def test_includes_multiple_tools_per_server(self):
        mgr = _make_manager()
        mgr._tools_cache = {
            "srv": [
                {"name": "t1", "description": "", "inputSchema": {}},
                {"name": "t2", "description": "", "inputSchema": {}},
            ]
        }
        result = mgr.get_all_tools()
        assert len(result) == 2
        assert all(t["server_id"] == "srv" for t in result)


@pytest.mark.unit
class TestGetToolsForProfile:
    """Tests for MCPClientManager.get_tools_for_profile()."""

    def test_returns_empty_when_profile_not_found(self):
        mgr = _make_manager()
        with patch("app.mcp.client_manager.get_agent_profile", return_value=None):
            result = mgr.get_tools_for_profile("nonexistent")
        assert result == []

    def test_returns_empty_when_no_allowed_servers(self):
        mgr = _make_manager()
        mgr._tools_cache = {"srv": [{"name": "t1", "description": "", "inputSchema": {}}]}
        profile = {"allowed_mcp_servers": []}
        with patch("app.mcp.client_manager.get_agent_profile", return_value=profile):
            result = mgr.get_tools_for_profile("empty-profile")
        assert result == []

    def test_returns_all_tools_when_wildcard(self):
        mgr = _make_manager()
        mgr._tools_cache = {
            "srv-a": [{"name": "t1", "description": "", "inputSchema": {}}],
            "srv-b": [{"name": "t2", "description": "", "inputSchema": {}}],
        }
        profile = {"allowed_mcp_servers": ["*"]}
        with patch("app.mcp.client_manager.get_agent_profile", return_value=profile):
            result = mgr.get_tools_for_profile("wildcard-profile")
        assert len(result) == 2

    def test_filters_to_allowed_servers_only(self):
        mgr = _make_manager()
        mgr._tools_cache = {
            "srv-a": [{"name": "t1", "description": "", "inputSchema": {}}],
            "srv-b": [{"name": "t2", "description": "", "inputSchema": {}}],
        }
        profile = {"allowed_mcp_servers": ["srv-a"]}
        with patch("app.mcp.client_manager.get_agent_profile", return_value=profile):
            result = mgr.get_tools_for_profile("restricted-profile")
        assert len(result) == 1
        assert result[0]["server_id"] == "srv-a"


@pytest.mark.unit
class TestIsConnected:
    """Tests for MCPClientManager.is_connected()."""

    def test_returns_false_when_no_sessions(self):
        mgr = _make_manager()
        assert mgr.is_connected() is False

    def test_returns_true_when_sessions_exist(self):
        mgr = _make_manager()
        mgr._sessions["srv"] = MagicMock()
        assert mgr.is_connected() is True

    def test_specific_server_true(self):
        mgr = _make_manager()
        mgr._sessions["known-server"] = MagicMock()
        assert mgr.is_connected("known-server") is True

    def test_specific_server_false(self):
        mgr = _make_manager()
        assert mgr.is_connected("unknown-server") is False


# ---------------------------------------------------------------------------
# Async tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestInitialize:
    """Tests for MCPClientManager.initialize() error paths."""

    async def test_returns_false_when_mcp_sdk_not_installed(self):
        """Returns False (and sets _initialized) when MCP SDK ImportError."""
        mgr = _make_manager()
        with patch(
            "app.mcp.client_manager._get_mcp_client",
            side_effect=ImportError("no mcp"),
        ):
            result = await mgr.initialize()
        assert result is False
        assert mgr._initialized is True

    async def test_returns_false_when_no_servers_configured(self):
        """Returns False when get_enabled_mcp_servers returns empty list."""
        mgr = _make_manager()
        mock_client = MagicMock()
        with patch("app.mcp.client_manager._get_mcp_client", return_value=(mock_client, MagicMock(), MagicMock())):
            with patch("app.mcp.client_manager.get_enabled_mcp_servers", return_value=[]):
                result = await mgr.initialize()
        assert result is False
        assert mgr._initialized is True

    async def test_idempotent_when_already_initialized(self):
        """Second call to initialize() returns immediately without re-running."""
        mgr = _make_manager()
        mgr._initialized = True
        # No mocks needed — should not call any external code
        result = await mgr.initialize()
        assert result is False  # no sessions → False


@pytest.mark.unit
@pytest.mark.asyncio
class TestCallTool:
    """Tests for MCPClientManager.call_tool()."""

    async def test_returns_error_when_server_not_connected(self):
        """Returns isError=True when server_id is not in _sessions."""
        mgr = _make_manager()
        result = await mgr.call_tool("unknown-server", "some_tool", {})
        assert result["isError"] is True
        assert "Unknown MCP server" in result["content"][0]["text"]

    async def test_returns_content_on_success(self):
        """Returns tool output when session.call_tool succeeds."""
        mgr = _make_manager()
        mock_result = MagicMock()
        mock_result.content = [{"type": "text", "text": "output"}]
        mock_result.isError = False
        mock_session = MagicMock()
        mock_session.call_tool = AsyncMock(return_value=mock_result)
        mgr._sessions["srv"] = mock_session

        result = await mgr.call_tool("srv", "my_tool", {"arg": "val"})

        mock_session.call_tool.assert_called_once_with("my_tool", {"arg": "val"})
        assert result["isError"] is False
        assert result["content"] == [{"type": "text", "text": "output"}]

    async def test_returns_error_on_exception(self):
        """Returns isError=True and error message when call_tool raises."""
        mgr = _make_manager()
        mock_session = MagicMock()
        mock_session.call_tool = AsyncMock(side_effect=RuntimeError("connection lost"))
        mgr._sessions["srv"] = mock_session

        result = await mgr.call_tool("srv", "my_tool", {})

        assert result["isError"] is True
        assert "connection lost" in result["content"][0]["text"]


@pytest.mark.unit
@pytest.mark.asyncio
class TestShutdown:
    """Tests for MCPClientManager.shutdown()."""

    async def test_shutdown_clears_all_state(self):
        """shutdown() closes exit stack, clears sessions and tools cache."""
        mgr = _make_manager()
        mock_stack = MagicMock()
        mock_stack.aclose = AsyncMock()
        mgr._exit_stack = mock_stack
        mgr._sessions["srv"] = MagicMock()
        mgr._tools_cache["srv"] = [{"name": "t1"}]
        mgr._initialized = True

        await mgr.shutdown()

        mock_stack.aclose.assert_called_once()
        assert mgr._exit_stack is None
        assert len(mgr._sessions) == 0
        assert len(mgr._tools_cache) == 0
        assert mgr._initialized is False

    async def test_shutdown_no_op_when_no_exit_stack(self):
        """shutdown() is safe to call when no connections were made."""
        mgr = _make_manager()
        await mgr.shutdown()  # should not raise
