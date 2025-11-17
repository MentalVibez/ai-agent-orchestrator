"""Application services and dependency injection."""

from typing import Optional
from app.core.agent_registry import AgentRegistry
from app.core.orchestrator import Orchestrator
from app.core.workflow_executor import WorkflowExecutor
from app.llm.manager import LLMManager
from app.llm.bedrock import BedrockProvider
from app.agents.network_diagnostics import NetworkDiagnosticsAgent


class ServiceContainer:
    """Container for application services."""
    
    def __init__(self):
        """Initialize the service container."""
        self._agent_registry: Optional[AgentRegistry] = None
        self._orchestrator: Optional[Orchestrator] = None
        self._workflow_executor: Optional[WorkflowExecutor] = None
        self._llm_manager: Optional[LLMManager] = None
        self._initialized = False
    
    def initialize(self) -> None:
        """Initialize all services."""
        if self._initialized:
            return
        
        # Initialize database
        from app.db import init_db
        init_db()
        
        # Initialize LLM Manager
        self._llm_manager = LLMManager()
        llm_provider = self._llm_manager.initialize_provider()
        
        # Initialize Agent Registry
        self._agent_registry = AgentRegistry()
        
        # Register agents
        network_agent = NetworkDiagnosticsAgent(llm_provider=llm_provider)
        self._agent_registry.register(network_agent)
        
        system_agent = SystemMonitoringAgent(llm_provider=llm_provider)
        self._agent_registry.register(system_agent)
        
        code_review_agent = CodeReviewAgent(llm_provider=llm_provider)
        self._agent_registry.register(code_review_agent)
        
        # Initialize Orchestrator
        self._orchestrator = Orchestrator(agent_registry=self._agent_registry)
        
        # Initialize Workflow Executor
        self._workflow_executor = WorkflowExecutor(orchestrator=self._orchestrator)
        
        self._initialized = True
    
    def get_agent_registry(self) -> AgentRegistry:
        """Get the agent registry."""
        if not self._initialized:
            self.initialize()
        if not self._agent_registry:
            raise RuntimeError("Agent registry not initialized")
        return self._agent_registry
    
    def get_orchestrator(self) -> Orchestrator:
        """Get the orchestrator."""
        if not self._initialized:
            self.initialize()
        if not self._orchestrator:
            raise RuntimeError("Orchestrator not initialized")
        return self._orchestrator
    
    def get_workflow_executor(self) -> WorkflowExecutor:
        """Get the workflow executor."""
        if not self._initialized:
            self.initialize()
        if not self._workflow_executor:
            raise RuntimeError("Workflow executor not initialized")
        return self._workflow_executor
    
    def shutdown(self) -> None:
        """Shutdown and cleanup services."""
        # Cleanup if needed
        self._initialized = False


# Global service container instance
_service_container: Optional[ServiceContainer] = None


def get_service_container() -> ServiceContainer:
    """Get the global service container."""
    global _service_container
    if _service_container is None:
        _service_container = ServiceContainer()
    return _service_container

