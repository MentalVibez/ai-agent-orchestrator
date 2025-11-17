"""Base agent class with common functionality."""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from app.llm.base import LLMProvider
from app.models.agent import AgentResult, AgentCapability
from app.core.tool_registry import get_tool_registry


class BaseAgent(ABC):
    """Abstract base class for all agents."""

    def __init__(
        self,
        agent_id: str,
        name: str,
        description: str,
        llm_provider: LLMProvider,
        capabilities: Optional[List[str]] = None
    ):
        """
        Initialize the base agent.

        Args:
            agent_id: Unique identifier for the agent
            name: Human-readable name
            description: Agent description
            llm_provider: LLM provider instance
            capabilities: List of capability strings
        """
        self.agent_id = agent_id
        self.name = name
        self.description = description
        self.llm_provider = llm_provider
        self.capabilities = capabilities or []
        self._state: Dict[str, Any] = {}
        self._tool_registry = get_tool_registry()

    @abstractmethod
    async def execute(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None
    ) -> AgentResult:
        """
        Execute a task.

        Args:
            task: Task description
            context: Optional context information

        Returns:
            AgentResult containing execution results
        """
        raise NotImplementedError("execute method must be implemented")

    def get_capabilities(self) -> List[AgentCapability]:
        """
        Get the agent's capabilities.

        Returns:
            List of AgentCapability objects
        """
        return [
            AgentCapability(name=cap, description=f"Supports {cap}")
            for cap in self.capabilities
        ]

    def get_state(self) -> Dict[str, Any]:
        """
        Get the agent's current state.

        Returns:
            Dictionary containing agent state
        """
        return self._state.copy()

    def set_state(self, key: str, value: Any) -> None:
        """
        Set a state value.

        Args:
            key: State key
            value: State value
        """
        self._state[key] = value

    def clear_state(self) -> None:
        """Clear all agent state."""
        self._state.clear()

    async def _generate_response(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs: Any
    ) -> str:
        """
        Generate a response using the LLM provider.

        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            **kwargs: Additional LLM parameters

        Returns:
            Generated response text
        """
        # Set agent context for cost tracking
        if hasattr(self.llm_provider, '_current_agent_id'):
            self.llm_provider._current_agent_id = self.agent_id
        
        return await self.llm_provider.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            **kwargs
        )

    def _format_result(
        self,
        success: bool,
        output: Any,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> AgentResult:
        """
        Format an agent result.

        Args:
            success: Whether execution was successful
            output: Output data
            error: Optional error message
            metadata: Optional metadata

        Returns:
            Formatted AgentResult
        """
        return AgentResult(
            agent_id=self.agent_id,
            agent_name=self.name,
            success=success,
            output=output,
            error=error,
            metadata=metadata or {}
        )
    
    async def use_tool(
        self,
        tool_id: str,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute a tool.
        
        Args:
            tool_id: Tool identifier
            params: Tool parameters
            context: Optional execution context
            
        Returns:
            Tool execution result
            
        Raises:
            AgentError: If tool execution fails
        """
        tool = self._tool_registry.get(tool_id)
        if not tool:
            from app.core.exceptions import AgentError
            raise AgentError(
                f"Tool '{tool_id}' not found",
                agent_id=self.agent_id,
                details={"available_tools": self._tool_registry.list_tools()}
            )
        
        # Execute tool with sandboxing
        from app.core.sandbox import get_sandbox
        sandbox = get_sandbox()
        
        with sandbox.execute_with_limits(self.agent_id, f"tool_{tool_id}"):
            return await tool.execute(self.agent_id, params, context)
    
    def get_available_tools(self) -> List[Dict[str, str]]:
        """
        Get list of available tools for this agent.
        
        Returns:
            List of tool information dictionaries
        """
        tools = self._tool_registry.get_tools_for_agent(self.agent_id)
        return [
            {
                "tool_id": tool.tool_id,
                "name": tool.name,
                "description": tool.description
            }
            for tool in tools
        ]

