"""Unit tests for Orchestrator."""

import pytest

from app.core.agent_registry import AgentRegistry
from app.core.orchestrator import Orchestrator


@pytest.mark.unit
class TestOrchestrator:
    """Test cases for Orchestrator."""

    @pytest.mark.asyncio
    async def test_route_task_empty_task(self, orchestrator: Orchestrator):
        """Test routing empty task returns error."""
        result = await orchestrator.route_task("")

        assert result.success is False
        assert result.agent_id == "orchestrator"
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_route_task_network_keyword(self, orchestrator: Orchestrator, network_agent):
        """Test routing task with network keyword."""
        orchestrator.agent_registry.register(network_agent)

        result = await orchestrator.route_task("Check network connectivity to google.com")

        assert result.success is True
        assert result.agent_id == "network_diagnostics"

    @pytest.mark.asyncio
    async def test_route_task_no_agent_found(self):
        """Test routing when no agent is available."""
        registry = AgentRegistry()
        orchestrator = Orchestrator(agent_registry=registry)

        result = await orchestrator.route_task("Some random task")

        assert result.success is False
        assert "No suitable agent found" in result.error

    @pytest.mark.asyncio
    async def test_route_task_with_context(self, orchestrator: Orchestrator, network_agent):
        """Test routing task with context."""
        orchestrator.agent_registry.register(network_agent)

        context = {"hostname": "example.com", "port": 443}
        result = await orchestrator.route_task("Check connectivity", context=context)

        assert result.success is True
        assert result.agent_id == "network_diagnostics"

    @pytest.mark.asyncio
    async def test_coordinate_agents_empty_list(self, orchestrator: Orchestrator):
        """Test coordinating empty agent list."""
        results = await orchestrator.coordinate_agents([], "test task")

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_coordinate_agents_single_agent(self, orchestrator: Orchestrator, network_agent):
        """Test coordinating single agent."""
        orchestrator.agent_registry.register(network_agent)

        results = await orchestrator.coordinate_agents(
            ["network_diagnostics"], "Check network connectivity"
        )

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].agent_id == "network_diagnostics"

    @pytest.mark.asyncio
    async def test_coordinate_agents_multiple_agents(
        self, orchestrator: Orchestrator, network_agent
    ):
        """Test coordinating multiple agents."""
        orchestrator.agent_registry.register(network_agent)

        # Register same agent twice to simulate multiple agents
        results = await orchestrator.coordinate_agents(
            ["network_diagnostics", "network_diagnostics"], "Check network connectivity"
        )

        assert len(results) == 2
        assert all(r.success for r in results)

    @pytest.mark.asyncio
    async def test_coordinate_agents_missing_agent(self, orchestrator: Orchestrator):
        """Test coordinating with missing agent."""
        results = await orchestrator.coordinate_agents(["nonexistent_agent"], "test task")

        assert len(results) == 1
        assert results[0].success is False
        assert "not found" in results[0].error.lower()

    @pytest.mark.asyncio
    async def test_coordinate_agents_passes_context(
        self, orchestrator: Orchestrator, network_agent
    ):
        """Test that coordinate_agents passes context between agents."""
        orchestrator.agent_registry.register(network_agent)

        context = {"test": "value"}
        results = await orchestrator.coordinate_agents(
            ["network_diagnostics"], "test task", context=context
        )

        assert len(results) == 1
        assert results[0].success is True
