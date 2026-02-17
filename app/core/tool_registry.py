"""Registry for managing agent tools."""

from typing import Dict, List, Optional

from app.core.tools import AgentTool


class ToolRegistry:
    """Registry for managing and retrieving tools."""

    def __init__(self):
        """Initialize the tool registry."""
        self._tools: Dict[str, AgentTool] = {}

    def register(self, tool: AgentTool) -> None:
        """
        Register a tool in the registry.

        Args:
            tool: Tool instance to register
        """
        if not tool or not tool.tool_id:
            raise ValueError("Tool must have a valid tool_id")

        self._tools[tool.tool_id] = tool

    def get(self, tool_id: str) -> Optional[AgentTool]:
        """
        Retrieve a tool by ID.

        Args:
            tool_id: Identifier of the tool

        Returns:
            Tool instance if found, None otherwise
        """
        return self._tools.get(tool_id)

    def get_all(self) -> List[AgentTool]:
        """
        Retrieve all registered tools.

        Returns:
            List of all registered tool instances
        """
        return list(self._tools.values())

    def list_tools(self) -> List[str]:
        """
        List all registered tool IDs.

        Returns:
            List of tool identifiers
        """
        return list(self._tools.keys())

    def get_tools_for_agent(self, agent_id: str) -> List[AgentTool]:
        """
        Get tools available for a specific agent.

        Args:
            agent_id: Agent identifier

        Returns:
            List of available tools (can be filtered by agent permissions)
        """
        # For now, return all tools. Can be enhanced with per-agent permissions
        return self.get_all()


# Global tool registry instance
_tool_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """Get the global tool registry instance."""
    global _tool_registry
    if _tool_registry is None:
        _tool_registry = ToolRegistry()
        # Register default tools
        from app.core.tools import CodeSearchTool, DirectoryListTool, FileMetadataTool, FileReadTool

        _tool_registry.register(FileReadTool())
        _tool_registry.register(CodeSearchTool())
        _tool_registry.register(DirectoryListTool())
        _tool_registry.register(FileMetadataTool())
    return _tool_registry
