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


# ---------------------------------------------------------------------------
# Additional initialize() paths (lines 59-60, 62-67, 72-73, 104-106)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestInitializeAdditionalPaths:
    """Cover transport routing and error paths inside initialize()."""

    async def test_unsupported_transport_logs_warning_and_skips(self):
        """Lines 62-67: server with transport='websocket' → warning, no session."""
        mgr = _make_manager()
        servers = [("srv1", {"transport": "websocket", "command": "cmd"})]

        with patch(
            "app.mcp.client_manager._get_mcp_client",
            return_value=(MagicMock(), MagicMock(), MagicMock()),
        ), patch(
            "app.mcp.client_manager.get_enabled_mcp_servers", return_value=servers
        ):
            result = await mgr.initialize()

        assert result is False
        assert "srv1" not in mgr._sessions
        assert mgr._initialized is True

    async def test_missing_command_logs_warning_and_skips(self):
        """Lines 72-73: stdio server without 'command' key → warning, no session."""
        mgr = _make_manager()
        servers = [("srv1", {"transport": "stdio"})]  # no 'command' key

        with patch(
            "app.mcp.client_manager._get_mcp_client",
            return_value=(MagicMock(), MagicMock(), MagicMock()),
        ), patch(
            "app.mcp.client_manager.get_enabled_mcp_servers", return_value=servers
        ):
            result = await mgr.initialize()

        assert result is False
        assert "srv1" not in mgr._sessions

    async def test_sse_transport_delegates_to_connect_sse(self):
        """Lines 59-60: transport='sse' calls _connect_sse() then continues."""
        from app.mcp.client_manager import MCPClientManager

        mgr = _make_manager()
        servers = [("srv1", {"transport": "sse", "url": "http://example.com"})]

        with patch(
            "app.mcp.client_manager._get_mcp_client",
            return_value=(MagicMock(), MagicMock(), MagicMock()),
        ), patch(
            "app.mcp.client_manager.get_enabled_mcp_servers", return_value=servers
        ), patch.object(
            MCPClientManager, "_connect_sse", new_callable=AsyncMock
        ) as mock_connect:
            await mgr.initialize()

        mock_connect.assert_called_once()
        call_args = mock_connect.call_args
        assert call_args[0][0] == "srv1"

    async def test_outer_exception_closes_exit_stack_and_reraises(self):
        """Lines 104-106: _connect_sse raising propagates out; aclose() runs."""
        from app.mcp.client_manager import MCPClientManager

        mgr = _make_manager()
        servers = [("srv1", {"transport": "sse", "url": "http://example.com"})]

        with patch(
            "app.mcp.client_manager._get_mcp_client",
            return_value=(MagicMock(), MagicMock(), MagicMock()),
        ), patch(
            "app.mcp.client_manager.get_enabled_mcp_servers", return_value=servers
        ), patch.object(
            MCPClientManager,
            "_connect_sse",
            new_callable=AsyncMock,
            side_effect=RuntimeError("sse connect failed"),
        ):
            with pytest.raises(RuntimeError, match="sse connect failed"):
                await mgr.initialize()

        # _initialized must NOT have been set — exception interrupted the flow
        assert mgr._initialized is False


# ---------------------------------------------------------------------------
# _connect_sse()  — lines 116-153 entirely uncovered before this file
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestConnectSse:
    """Direct tests for MCPClientManager._connect_sse()."""

    async def _make_mgr_with_stack(self):
        """Helper: build a manager with an entered AsyncExitStack."""
        from contextlib import AsyncExitStack

        mgr = _make_manager()
        mgr._exit_stack = AsyncExitStack()
        await mgr._exit_stack.__aenter__()
        return mgr

    async def test_no_url_logs_warning_and_returns_early(self):
        """Lines 116-119: missing 'url' → log warning, return, no session."""
        mgr = await self._make_mgr_with_stack()
        await mgr._connect_sse("srv", {}, MagicMock())  # no url in cfg
        assert "srv" not in mgr._sessions
        await mgr._exit_stack.aclose()

    async def test_sse_import_error_logs_warning_and_returns(self):
        """Lines 120-127: ImportError for mcp.client.sse → log warning, return."""
        mgr = await self._make_mgr_with_stack()

        with patch.dict(
            "sys.modules",
            {"mcp": MagicMock(), "mcp.client": MagicMock(), "mcp.client.sse": None},
        ):
            await mgr._connect_sse("srv", {"url": "http://example.com"}, MagicMock())

        assert "srv" not in mgr._sessions
        await mgr._exit_stack.aclose()

    async def test_success_path_connects_and_caches_tools(self):
        """Lines 128-151: happy path — connects, discovers tools, caches them."""
        mgr = await self._make_mgr_with_stack()

        # Build mock SSE transport context manager
        mock_read, mock_write = MagicMock(), MagicMock()

        class _SseCtx:
            async def __aenter__(self_):
                return (mock_read, mock_write)
            async def __aexit__(self_, *a):
                pass

        mock_sse_client = MagicMock(return_value=_SseCtx())

        # Build mock ClientSession context manager
        mock_session = MagicMock()
        mock_session.initialize = AsyncMock()
        mock_tool = MagicMock()
        mock_tool.name = "ping"
        mock_tool.description = "Ping a host"
        mock_tool.inputSchema = {"type": "object"}
        mock_list_resp = MagicMock()
        mock_list_resp.tools = [mock_tool]
        mock_session.list_tools = AsyncMock(return_value=mock_list_resp)

        class _SessionCtx:
            async def __aenter__(self_):
                return mock_session
            async def __aexit__(self_, *a):
                pass

        mock_client_session_cls = MagicMock(return_value=_SessionCtx())

        mock_sse_module = MagicMock()
        mock_sse_module.sse_client = mock_sse_client

        with patch.dict(
            "sys.modules",
            {
                "mcp": MagicMock(),
                "mcp.client": MagicMock(),
                "mcp.client.sse": mock_sse_module,
            },
        ):
            await mgr._connect_sse(
                "srv",
                {"url": "http://example.com", "headers": {"Authorization": "Bearer tok"}},
                mock_client_session_cls,
            )

        assert "srv" in mgr._sessions
        assert mgr._sessions["srv"] is mock_session
        assert len(mgr._tools_cache["srv"]) == 1
        assert mgr._tools_cache["srv"][0]["name"] == "ping"
        mock_session.initialize.assert_called_once()
        await mgr._exit_stack.aclose()

    async def test_exception_in_sse_connection_is_logged(self):
        """Lines 152-153: exception during connect is caught and logged."""
        mgr = await self._make_mgr_with_stack()

        mock_sse_module = MagicMock()
        mock_sse_module.sse_client = MagicMock(
            side_effect=ConnectionRefusedError("refused")
        )

        with patch.dict(
            "sys.modules",
            {
                "mcp": MagicMock(),
                "mcp.client": MagicMock(),
                "mcp.client.sse": mock_sse_module,
            },
        ), patch("app.mcp.client_manager.logger") as mock_log:
            await mgr._connect_sse("srv", {"url": "http://example.com"}, MagicMock())

        assert "srv" not in mgr._sessions
        mock_log.exception.assert_called_once()
        await mgr._exit_stack.aclose()


# ---------------------------------------------------------------------------
# get_mcp_client_manager() singleton  (line 219)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetMcpClientManagerSingleton:
    def test_returns_mcp_client_manager_instance(self):
        from app.mcp.client_manager import get_mcp_client_manager, MCPClientManager

        result = get_mcp_client_manager()
        assert isinstance(result, MCPClientManager)

    def test_returns_same_instance_on_repeated_calls(self):
        """Line 219: singleton — second call skips construction."""
        import app.mcp.client_manager as cm_module
        from app.mcp.client_manager import get_mcp_client_manager

        original = cm_module._mcp_client_manager
        cm_module._mcp_client_manager = None
        try:
            m1 = get_mcp_client_manager()
            m2 = get_mcp_client_manager()
            assert m1 is m2
        finally:
            cm_module._mcp_client_manager = original
