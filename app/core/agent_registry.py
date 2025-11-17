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
        if not agent or not agent.agent_id:
            raise ValueError("Agent must have a valid agent_id")
        
        self._agents[agent.agent_id] = agent

    def get(self, agent_id: str) -> Optional[BaseAgent]:
        """
        Retrieve an agent by ID.

        Args:
            agent_id: Identifier of the agent

        Returns:
            Agent instance if found, None otherwise
        """
        return self._agents.get(agent_id)

    def get_all(self) -> List[BaseAgent]:
        """
        Retrieve all registered agents.

        Returns:
            List of all registered agent instances
        """
        return list(self._agents.values())

    def get_by_capability(self, capability: str) -> List[BaseAgent]:
        """
        Retrieve agents that have a specific capability.

        Args:
            capability: Capability to search for

        Returns:
            List of agents with the specified capability
        """
        matching_agents = []
        for agent in self._agents.values():
            if capability.lower() in [cap.lower() for cap in agent.capabilities]:
                matching_agents.append(agent)
        return matching_agents

    def list_agents(self) -> List[str]:
        """
        List all registered agent IDs.

        Returns:
            List of agent identifiers
        """
        return list(self._agents.keys())

