"""Pytest configuration and shared fixtures."""

import pytest
from typing import Generator
from app.core.agent_registry import AgentRegistry
from app.core.orchestrator import Orchestrator
from app.agents.network_diagnostics import NetworkDiagnosticsAgent
from app.llm.base import LLMProvider
from tests.fixtures.mock_llm import MockLLMProvider


@pytest.fixture
def mock_llm_provider() -> MockLLMProvider:
    """Create a mock LLM provider for testing."""
    return MockLLMProvider()


@pytest.fixture
def mock_llm_with_responses() -> MockLLMProvider:
    """Create a mock LLM provider with predefined responses."""
    responses = {
        "Network Diagnostics Task: Check connectivity\n\nPlease provide:\n1. Analysis of the network issue\n2. Recommended diagnostic steps\n3. Potential causes\n4. Troubleshooting recommendations": 
        "Network connectivity analysis: The host appears to be reachable. Recommended steps: 1) Check firewall rules, 2) Verify DNS resolution, 3) Test with ping. Potential causes: Network congestion or firewall blocking. Troubleshooting: Use traceroute to identify the issue."
    }
    return MockLLMProvider(responses=responses)


@pytest.fixture
def agent_registry(mock_llm_provider: MockLLMProvider) -> AgentRegistry:
    """Create an agent registry with a test agent."""
    registry = AgentRegistry()
    agent = NetworkDiagnosticsAgent(llm_provider=mock_llm_provider)
    registry.register(agent)
    return registry


@pytest.fixture
def orchestrator(agent_registry: AgentRegistry) -> Orchestrator:
    """Create an orchestrator instance for testing."""
    return Orchestrator(agent_registry=agent_registry)


@pytest.fixture
def network_agent(mock_llm_with_responses: MockLLMProvider) -> NetworkDiagnosticsAgent:
    """Create a network diagnostics agent for testing."""
    return NetworkDiagnosticsAgent(llm_provider=mock_llm_with_responses)

