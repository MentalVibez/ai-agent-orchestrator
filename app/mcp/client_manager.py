"""MCP client manager: connect to multiple MCP servers, discover tools, execute tool calls."""

import logging
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional

from app.mcp.config_loader import get_agent_profile, get_enabled_mcp_servers

logger = logging.getLogger(__name__)


# Lazy import to avoid requiring mcp when MCP is disabled
def _get_mcp_client():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    return ClientSession, StdioServerParameters, stdio_client


class MCPClientManager:
    """
    Connects to configured MCP servers (stdio), discovers tools, and routes tool calls.
    Use get_mcp_client_manager() to get the singleton.
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, Any] = {}  # server_id -> ClientSession
        self._tools_cache: Dict[str, List[Dict[str, Any]]] = {}  # server_id -> list of tool infos
        self._exit_stack: Optional[AsyncExitStack] = None
        self._initialized = False

    async def initialize(self) -> bool:
        """
        Connect to all enabled MCP servers (stdio only in v0). Returns True if at least one connected.
        """
        if self._initialized:
            return len(self._sessions) > 0

        try:
            ClientSession, StdioServerParameters, stdio_client = _get_mcp_client()
        except ImportError as e:
            logger.warning("MCP SDK not installed; MCP features disabled: %s", e)
            self._initialized = True
            return False

        servers = get_enabled_mcp_servers()
        if not servers:
            logger.info("No enabled MCP servers in config; MCP layer idle.")
            self._initialized = True
            return False

        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()
        try:
            for server_id, cfg in servers:
                if cfg.get("transport") != "stdio":
                    logger.warning(
                        "MCP server %s: only stdio transport is supported in v0", server_id
                    )
                    continue
                command = cfg.get("command")
                args = cfg.get("args") or []
                env = cfg.get("env") or {}
                if not command:
                    logger.warning("MCP server %s: missing 'command'", server_id)
                    continue
                try:
                    server_params = StdioServerParameters(
                        command=command,
                        args=args,
                        env=env if env else None,
                    )
                    stdio_transport = await self._exit_stack.enter_async_context(
                        stdio_client(server_params)
                    )
                    read_stream, write_stream = stdio_transport
                    session = await self._exit_stack.enter_async_context(
                        ClientSession(read_stream, write_stream)
                    )
                    await session.initialize()
                    self._sessions[server_id] = session
                    # Discover tools
                    response = await session.list_tools()
                    tools = []
                    for t in response.tools:
                        tools.append(
                            {
                                "name": t.name,
                                "description": t.description or "",
                                "inputSchema": getattr(t, "inputSchema", None) or {},
                            }
                        )
                    self._tools_cache[server_id] = tools
                    logger.info("MCP server %s connected with %d tools", server_id, len(tools))
                except Exception as e:
                    logger.exception("Failed to connect to MCP server %s: %s", server_id, e)
        except Exception:
            await self._exit_stack.aclose()
            raise
        self._initialized = True
        return len(self._sessions) > 0

    async def shutdown(self) -> None:
        """Close all MCP connections."""
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._exit_stack = None
        self._sessions.clear()
        self._tools_cache.clear()
        self._initialized = False
        logger.info("MCP client manager shutdown")

    def get_all_tools(self) -> List[Dict[str, Any]]:
        """
        Return flattened list of tools from all connected servers.
        Each item: { "server_id", "name", "description", "inputSchema" }
        """
        out = []
        for server_id, tools in self._tools_cache.items():
            for t in tools:
                out.append(
                    {
                        "server_id": server_id,
                        "name": t["name"],
                        "description": t["description"],
                        "inputSchema": t.get("inputSchema"),
                    }
                )
        return out

    def get_tools_for_profile(self, profile_id: str) -> List[Dict[str, Any]]:
        """
        Return tools allowed for this agent profile (by allowed_mcp_servers).
        If allowed_mcp_servers is empty or missing, return [] (no MCP tools for this profile).
        If allowed_mcp_servers is ['*'] or contains '*', return all tools.
        """
        profile = get_agent_profile(profile_id)
        if not profile:
            return []
        allowed = profile.get("allowed_mcp_servers")
        if not allowed:
            return []
        all_tools = self.get_all_tools()
        if "*" in allowed:
            return all_tools
        return [t for t in all_tools if t["server_id"] in allowed]

    async def call_tool(
        self, server_id: str, tool_name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a tool on the given MCP server. Returns { "content": ..., "isError": bool }.
        """
        session = self._sessions.get(server_id)
        if not session:
            return {
                "content": [{"type": "text", "text": f"Unknown MCP server: {server_id}"}],
                "isError": True,
            }
        try:
            result = await session.call_tool(tool_name, arguments)
            # MCP SDK returns CallToolResult with content list and possibly isError
            content = getattr(result, "content", result) if hasattr(result, "content") else result
            is_error = getattr(result, "isError", False)
            if isinstance(content, list):
                return {"content": content, "isError": is_error}
            return {"content": [{"type": "text", "text": str(content)}], "isError": is_error}
        except Exception as e:
            logger.exception("MCP call_tool %s/%s failed: %s", server_id, tool_name, e)
            return {
                "content": [{"type": "text", "text": f"Tool call failed: {e!s}"}],
                "isError": True,
            }

    def is_connected(self, server_id: Optional[str] = None) -> bool:
        """Return True if any (or the given) server is connected."""
        if server_id:
            return server_id in self._sessions
        return len(self._sessions) > 0


_mcp_client_manager: Optional[MCPClientManager] = None


def get_mcp_client_manager() -> MCPClientManager:
    """Singleton MCP client manager."""
    global _mcp_client_manager
    if _mcp_client_manager is None:
        _mcp_client_manager = MCPClientManager()
    return _mcp_client_manager
