"""Unit tests for Network Diagnostics Agent."""

import pytest
from unittest.mock import AsyncMock
from app.agents.network_diagnostics import NetworkDiagnosticsAgent
from tests.fixtures.mock_llm import MockLLMProvider


@pytest.mark.unit
class TestNetworkDiagnosticsAgent:
    """Test cases for NetworkDiagnosticsAgent."""
    
    @pytest.fixture
    def agent(self, mock_llm_provider: MockLLMProvider):
        """Create a network diagnostics agent."""
        return NetworkDiagnosticsAgent(llm_provider=mock_llm_provider)
    
    @pytest.mark.asyncio
    async def test_agent_initialization(self, agent: NetworkDiagnosticsAgent):
        """Test agent is properly initialized."""
        assert agent.agent_id == "network_diagnostics"
        assert agent.name == "Network Diagnostics Agent"
        assert "network_connectivity" in agent.capabilities
    
    @pytest.mark.asyncio
    async def test_execute_success(self, agent: NetworkDiagnosticsAgent):
        """Test successful task execution."""
        result = await agent.execute("Check network connectivity to example.com")
        
        assert result.success is True
        assert result.agent_id == "network_diagnostics"
        assert "output" in result.output or "summary" in result.output
    
    @pytest.mark.asyncio
    async def test_execute_with_context(self, agent: NetworkDiagnosticsAgent):
        """Test execution with context."""
        context = {"hostname": "example.com", "port": 443}
        result = await agent.execute("Check connectivity", context=context)
        
        assert result.success is True
        assert "context_used" in result.output
    
    @pytest.mark.asyncio
    async def test_execute_handles_errors(self, agent: NetworkDiagnosticsAgent):
        """Test error handling during execution."""
        # Create agent with failing LLM provider
        failing_provider = MockLLMProvider()
        failing_provider.generate = AsyncMock(side_effect=Exception("LLM Error"))
        failing_agent = NetworkDiagnosticsAgent(llm_provider=failing_provider)
        
        result = await failing_agent.execute("Test task")
        
        assert result.success is False
        assert "error" in result.error.lower() or result.error is not None
    
    def test_identify_diagnostic_type_connectivity(self, agent: NetworkDiagnosticsAgent):
        """Test diagnostic type identification for connectivity."""
        diagnostic_type = agent._identify_diagnostic_type("Check ping connectivity")
        
        assert diagnostic_type == "connectivity_check"
    
    def test_identify_diagnostic_type_dns(self, agent: NetworkDiagnosticsAgent):
        """Test diagnostic type identification for DNS."""
        diagnostic_type = agent._identify_diagnostic_type("Resolve DNS for domain")
        
        assert diagnostic_type == "dns_resolution"
    
    def test_identify_diagnostic_type_latency(self, agent: NetworkDiagnosticsAgent):
        """Test diagnostic type identification for latency."""
        diagnostic_type = agent._identify_diagnostic_type("Check network latency")
        
        assert diagnostic_type == "latency_analysis"
    
    def test_identify_diagnostic_type_routing(self, agent: NetworkDiagnosticsAgent):
        """Test diagnostic type identification for routing."""
        diagnostic_type = agent._identify_diagnostic_type("Trace route to host")
        
        assert diagnostic_type == "routing_analysis"
    
    def test_identify_diagnostic_type_port(self, agent: NetworkDiagnosticsAgent):
        """Test diagnostic type identification for port."""
        diagnostic_type = agent._identify_diagnostic_type("Scan ports on server")
        
        assert diagnostic_type == "port_analysis"
    
    def test_identify_diagnostic_type_general(self, agent: NetworkDiagnosticsAgent):
        """Test diagnostic type identification for general."""
        diagnostic_type = agent._identify_diagnostic_type("General network issue")
        
        assert diagnostic_type == "general_diagnostics"

