"""FastAPI dependency functions for injecting services from app.state."""

from fastapi import Depends, Request

from app.core.agent_registry import AgentRegistry
from app.core.orchestrator import Orchestrator
from app.core.workflow_executor import WorkflowExecutor
from app.llm.manager import LLMManager


def get_container(request: Request):
    """Get the service container from app state."""
    return request.app.state.container


def get_agent_registry(container=Depends(get_container)) -> AgentRegistry:
    """Inject the agent registry."""
    return container.get_agent_registry()


def get_orchestrator(container=Depends(get_container)) -> Orchestrator:
    """Inject the orchestrator."""
    return container.get_orchestrator()


def get_workflow_executor(container=Depends(get_container)) -> WorkflowExecutor:
    """Inject the workflow executor."""
    return container.get_workflow_executor()


def get_llm_manager(container=Depends(get_container)) -> LLMManager:
    """Inject the LLM manager."""
    return container.get_llm_manager()
