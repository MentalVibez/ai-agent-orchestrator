"""Unit tests for System Monitoring Agent."""

import pytest
from unittest.mock import AsyncMock
from app.agents.system_monitoring import SystemMonitoringAgent
from tests.fixtures.mock_llm import MockLLMProvider


@pytest.mark.unit
class TestSystemMonitoringAgent:
    """Test cases for SystemMonitoringAgent."""
    
    @pytest.fixture
    def agent(self, mock_llm_provider: MockLLMProvider):
        """Create a system monitoring agent."""
        return SystemMonitoringAgent(llm_provider=mock_llm_provider)
    
    @pytest.mark.asyncio
    async def test_agent_initialization(self, agent: SystemMonitoringAgent):
        """Test agent is properly initialized."""
        assert agent.agent_id == "system_monitoring"
        assert agent.name == "System Monitoring Agent"
        assert "cpu_monitoring" in agent.capabilities
        assert "memory_monitoring" in agent.capabilities
    
    @pytest.mark.asyncio
    async def test_execute_success(self, agent: SystemMonitoringAgent):
        """Test successful task execution."""
        result = await agent.execute("Monitor CPU usage")
        
        assert result.success is True
        assert result.agent_id == "system_monitoring"
        assert "output" in result.output or "summary" in result.output
    
    @pytest.mark.asyncio
    async def test_execute_with_context(self, agent: SystemMonitoringAgent):
        """Test execution with context."""
        context = {"cpu_usage": 85.0, "memory_usage": 70.0}
        result = await agent.execute("Check system health", context=context)
        
        assert result.success is True
        assert "context_used" in result.output or "metrics_collected" in result.output
    
    @pytest.mark.asyncio
    async def test_execute_handles_errors(self, agent: SystemMonitoringAgent):
        """Test error handling during execution."""
        failing_provider = MockLLMProvider()
        failing_provider.generate = AsyncMock(side_effect=Exception("LLM Error"))
        failing_agent = SystemMonitoringAgent(llm_provider=failing_provider)
        
        result = await failing_agent.execute("Test task")
        
        assert result.success is False
        assert "error" in result.error.lower() or result.error is not None
    
    def test_collect_metrics_basic(self, agent: SystemMonitoringAgent):
        """Test collecting basic system metrics."""
        metrics = agent._collect_metrics({})
        
        assert "platform" in metrics
        assert "cpu_count" in metrics
        assert "hostname" in metrics
    
    def test_collect_metrics_with_context(self, agent: SystemMonitoringAgent):
        """Test collecting metrics with context data."""
        context = {
            "cpu_usage": 85.0,
            "memory_usage": 70.0,
            "disk_usage": 60.0
        }
        metrics = agent._collect_metrics(context)
        
        assert metrics["cpu_usage_percent"] == 85.0
        assert metrics["memory_usage_percent"] == 70.0
        assert metrics["disk_usage_percent"] == 60.0
    
    def test_identify_monitoring_type_cpu(self, agent: SystemMonitoringAgent):
        """Test identifying CPU monitoring type."""
        monitoring_type = agent._identify_monitoring_type("Check CPU usage")
        assert monitoring_type == "cpu_monitoring"
    
    def test_identify_monitoring_type_memory(self, agent: SystemMonitoringAgent):
        """Test identifying memory monitoring type."""
        monitoring_type = agent._identify_monitoring_type("Monitor RAM usage")
        assert monitoring_type == "memory_monitoring"
    
    def test_identify_monitoring_type_disk(self, agent: SystemMonitoringAgent):
        """Test identifying disk monitoring type."""
        monitoring_type = agent._identify_monitoring_type("Check disk storage")
        assert monitoring_type == "disk_monitoring"
    
    def test_identify_monitoring_type_process(self, agent: SystemMonitoringAgent):
        """Test identifying process monitoring type."""
        monitoring_type = agent._identify_monitoring_type("Monitor running processes")
        assert monitoring_type == "process_monitoring"
    
    def test_identify_monitoring_type_health(self, agent: SystemMonitoringAgent):
        """Test identifying system health monitoring type."""
        monitoring_type = agent._identify_monitoring_type("Check overall system health")
        assert monitoring_type == "system_health"
    
    def test_identify_monitoring_type_general(self, agent: SystemMonitoringAgent):
        """Test identifying general monitoring type."""
        monitoring_type = agent._identify_monitoring_type("Monitor system")
        assert monitoring_type == "general_monitoring"

