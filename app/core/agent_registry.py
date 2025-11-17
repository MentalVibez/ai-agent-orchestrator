"""Agent registry for managing available agents and their capabilities."""

from typing import Dict, List, Optional
from app.agents.base import BaseAgent
from app.models.agent import AgentInfo, AgentCapability


class AgentRegistry:
    """Registry for managing and retrieving agents."""

    def __init__(self):
        """Initialize the agent registry."""
        self._agents: Dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        """
        Register an agent in the registry.

        Args:
            agent: Agent instance to register
        """
        # TODO: Implement agent registration
        # Store agent with its ID as the key
        raise NotImplementedError("register method must be implemented")

    def get(self, agent_id: str) -> Optional[BaseAgent]:
        """
        Retrieve an agent by ID.

        Args:
            agent_id: Identifier of the agent

        Returns:
            Agent instance if found, None otherwise
        """
        # TODO: Implement agent retrieval
        raise NotImplementedError("get method must be implemented")

    def get_all(self) -> List[BaseAgent]:
        """
        Retrieve all registered agents.

        Returns:
            List of all registered agent instances
        """
        # TODO: Implement retrieval of all agents
        raise NotImplementedError("get_all method must be implemented")

    def get_by_capability(self, capability: str) -> List[BaseAgent]:
        """
        Retrieve agents that have a specific capability.

        Args:
            capability: Capability to search for

        Returns:
            List of agents with the specified capability
        """
        # TODO: Implement capability-based agent retrieval
        raise NotImplementedError("get_by_capability method must be implemented")

    def list_agents(self) -> List[str]:
        """
        List all registered agent IDs.

        Returns:
            List of agent identifiers
        """
        # TODO: Implement agent ID listing
        raise NotImplementedError("list_agents method must be implemented")

