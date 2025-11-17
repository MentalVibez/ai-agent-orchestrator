"""Unit tests for Agent Registry."""

import pytest
from app.core.agent_registry import AgentRegistry
from app.agents.network_diagnostics import NetworkDiagnosticsAgent
from tests.fixtures.mock_llm import MockLLMProvider


@pytest.mark.unit
class TestAgentRegistry:
    """Test cases for AgentRegistry."""
    
    def test_register_agent(self, mock_llm_provider: MockLLMProvider):
        """Test registering an agent."""
        registry = AgentRegistry()
        agent = NetworkDiagnosticsAgent(llm_provider=mock_llm_provider)
        
        registry.register(agent)
        
        assert registry.get("network_diagnostics") == agent
        assert len(registry.get_all()) == 1
    
    def test_register_agent_duplicate(self, mock_llm_provider: MockLLMProvider):
        """Test registering duplicate agent overwrites."""
        registry = AgentRegistry()
        agent1 = NetworkDiagnosticsAgent(llm_provider=mock_llm_provider)
        agent2 = NetworkDiagnosticsAgent(llm_provider=mock_llm_provider)
        
        registry.register(agent1)
        registry.register(agent2)
        
        assert registry.get("network_diagnostics") == agent2
        assert len(registry.get_all()) == 1
    
    def test_register_invalid_agent(self):
        """Test registering invalid agent raises error."""
        registry = AgentRegistry()
        
        with pytest.raises(ValueError, match="Agent must have a valid agent_id"):
            registry.register(None)
    
    def test_get_agent_exists(self, agent_registry: AgentRegistry):
        """Test getting an existing agent."""
        agent = agent_registry.get("network_diagnostics")
        
        assert agent is not None
        assert agent.agent_id == "network_diagnostics"
    
    def test_get_agent_not_exists(self, agent_registry: AgentRegistry):
        """Test getting a non-existent agent returns None."""
        agent = agent_registry.get("nonexistent_agent")
        
        assert agent is None
    
    def test_get_all_agents(self, agent_registry: AgentRegistry):
        """Test getting all agents."""
        agents = agent_registry.get_all()
        
        assert len(agents) == 1
        assert agents[0].agent_id == "network_diagnostics"
    
    def test_get_all_empty(self):
        """Test getting all agents from empty registry."""
        registry = AgentRegistry()
        agents = registry.get_all()
        
        assert len(agents) == 0
    
    def test_get_by_capability(self, agent_registry: AgentRegistry):
        """Test getting agents by capability."""
        agents = agent_registry.get_by_capability("network_connectivity")
        
        assert len(agents) == 1
        assert agents[0].agent_id == "network_diagnostics"
    
    def test_get_by_capability_not_found(self, agent_registry: AgentRegistry):
        """Test getting agents by non-existent capability."""
        agents = agent_registry.get_by_capability("nonexistent_capability")
        
        assert len(agents) == 0
    
    def test_get_by_capability_case_insensitive(self, agent_registry: AgentRegistry):
        """Test capability search is case insensitive."""
        agents = agent_registry.get_by_capability("NETWORK_CONNECTIVITY")
        
        assert len(agents) == 1
    
    def test_list_agents(self, agent_registry: AgentRegistry):
        """Test listing agent IDs."""
        agent_ids = agent_registry.list_agents()
        
        assert len(agent_ids) == 1
        assert "network_diagnostics" in agent_ids
    
    def test_list_agents_empty(self):
        """Test listing agents from empty registry."""
        registry = AgentRegistry()
        agent_ids = registry.list_agents()
        
        assert len(agent_ids) == 0

