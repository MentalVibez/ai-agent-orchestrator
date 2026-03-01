"""Unit tests for app/core/services.py — ServiceContainer."""

import pytest
from unittest.mock import MagicMock, patch

from app.core.services import ServiceContainer, get_service_container


# ---------------------------------------------------------------------------
# initialize()
# ---------------------------------------------------------------------------


class TestServiceContainerInitialize:
    def test_initialize_is_idempotent_when_already_initialized(self):
        """Second call returns immediately — covers the line-32 early return."""
        container = ServiceContainer()
        container._initialized = True
        container.initialize()  # must not raise or call any external code
        assert container._initialized is True

    def test_shutdown_resets_initialized_flag(self):
        container = ServiceContainer()
        container._initialized = True
        container.shutdown()
        assert container._initialized is False

    def test_initialize_creates_all_components(self):
        """Full initialize() run wires up registry, orchestrator, workflow executor, llm manager."""
        container = ServiceContainer()

        with patch("app.db.init_db"), \
             patch("app.core.services.LLMManager") as MockLLM, \
             patch("app.core.services.AgentRegistry") as MockReg, \
             patch("app.core.services.NetworkDiagnosticsAgent"), \
             patch("app.core.services.SystemMonitoringAgent"), \
             patch("app.core.services.CodeReviewAgent"), \
             patch("app.core.services.OsqueryAgent"), \
             patch("app.core.services.AnsibleAgent"), \
             patch("app.core.services.LogAnalysisAgent"), \
             patch("app.core.services.InfrastructureAgent"), \
             patch("app.core.services.Orchestrator") as MockOrch, \
             patch("app.core.services.WorkflowExecutor") as MockWF:
            MockLLM.return_value.initialize_provider.return_value = MagicMock()
            container.initialize()

        assert container._initialized is True
        MockLLM.assert_called_once()
        MockReg.assert_called_once()
        MockOrch.assert_called_once()
        MockWF.assert_called_once()


# ---------------------------------------------------------------------------
# get_agent_registry()
# ---------------------------------------------------------------------------


class TestGetAgentRegistry:
    def test_happy_path_returns_registry(self):
        container = ServiceContainer()
        container._initialized = True
        container._agent_registry = MagicMock()
        result = container.get_agent_registry()
        assert result is container._agent_registry

    def test_auto_initializes_when_not_initialized(self):
        """Covers line 82: self.initialize() called from get_agent_registry."""
        container = ServiceContainer()
        mock_registry = MagicMock()

        def _setup(*args, **kwargs):
            container._initialized = True
            container._agent_registry = mock_registry

        with patch.object(container, "initialize", side_effect=_setup):
            result = container.get_agent_registry()

        assert result is mock_registry

    def test_raises_runtime_error_when_registry_is_none(self):
        """Covers line 84: raise RuntimeError when _agent_registry is None after init."""
        container = ServiceContainer()
        container._initialized = True
        container._agent_registry = None
        with pytest.raises(RuntimeError, match="Agent registry not initialized"):
            container.get_agent_registry()


# ---------------------------------------------------------------------------
# get_orchestrator()  — lines 89-93 entirely uncovered before this file
# ---------------------------------------------------------------------------


class TestGetOrchestrator:
    def test_happy_path_returns_orchestrator(self):
        """Covers lines 89, 91, 93."""
        container = ServiceContainer()
        container._initialized = True
        container._orchestrator = MagicMock()
        result = container.get_orchestrator()
        assert result is container._orchestrator

    def test_auto_initializes_when_not_initialized(self):
        """Covers lines 89-90: triggers initialize() then returns."""
        container = ServiceContainer()
        mock_orch = MagicMock()

        def _setup(*args, **kwargs):
            container._initialized = True
            container._orchestrator = mock_orch

        with patch.object(container, "initialize", side_effect=_setup):
            result = container.get_orchestrator()

        assert result is mock_orch

    def test_raises_runtime_error_when_orchestrator_is_none(self):
        """Covers lines 91-92: raises RuntimeError when _orchestrator is None."""
        container = ServiceContainer()
        container._initialized = True
        container._orchestrator = None
        with pytest.raises(RuntimeError, match="Orchestrator not initialized"):
            container.get_orchestrator()


# ---------------------------------------------------------------------------
# get_workflow_executor()  — lines 97-101 entirely uncovered before this file
# ---------------------------------------------------------------------------


class TestGetWorkflowExecutor:
    def test_happy_path_returns_workflow_executor(self):
        """Covers lines 97, 99, 101."""
        container = ServiceContainer()
        container._initialized = True
        container._workflow_executor = MagicMock()
        result = container.get_workflow_executor()
        assert result is container._workflow_executor

    def test_auto_initializes_when_not_initialized(self):
        """Covers lines 97-98: triggers initialize() then returns."""
        container = ServiceContainer()
        mock_wf = MagicMock()

        def _setup(*args, **kwargs):
            container._initialized = True
            container._workflow_executor = mock_wf

        with patch.object(container, "initialize", side_effect=_setup):
            result = container.get_workflow_executor()

        assert result is mock_wf

    def test_raises_runtime_error_when_executor_is_none(self):
        """Covers lines 99-100: raises RuntimeError when _workflow_executor is None."""
        container = ServiceContainer()
        container._initialized = True
        container._workflow_executor = None
        with pytest.raises(RuntimeError, match="Workflow executor not initialized"):
            container.get_workflow_executor()


# ---------------------------------------------------------------------------
# get_llm_manager()  — lines 105-109 entirely uncovered before this file
# ---------------------------------------------------------------------------


class TestGetLlmManager:
    def test_happy_path_returns_llm_manager(self):
        """Covers lines 105, 107, 109."""
        container = ServiceContainer()
        container._initialized = True
        container._llm_manager = MagicMock()
        result = container.get_llm_manager()
        assert result is container._llm_manager

    def test_auto_initializes_when_not_initialized(self):
        """Covers lines 105-106: triggers initialize() then returns."""
        container = ServiceContainer()
        mock_llm = MagicMock()

        def _setup(*args, **kwargs):
            container._initialized = True
            container._llm_manager = mock_llm

        with patch.object(container, "initialize", side_effect=_setup):
            result = container.get_llm_manager()

        assert result is mock_llm

    def test_raises_runtime_error_when_llm_manager_is_none(self):
        """Covers lines 107-108: raises RuntimeError when _llm_manager is None."""
        container = ServiceContainer()
        container._initialized = True
        container._llm_manager = None
        with pytest.raises(RuntimeError, match="LLM manager not initialized"):
            container.get_llm_manager()


# ---------------------------------------------------------------------------
# get_service_container() module-level singleton
# ---------------------------------------------------------------------------


class TestGetServiceContainerSingleton:
    def test_returns_a_service_container_instance(self):
        result = get_service_container()
        assert isinstance(result, ServiceContainer)

    def test_returns_same_instance_on_repeated_calls(self):
        c1 = get_service_container()
        c2 = get_service_container()
        assert c1 is c2
