"""Pydantic models for API requests and responses."""

from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field
from app.models.agent import AgentResult, AgentInfo
from app.models.workflow import Workflow, WorkflowResult


class OrchestrateRequest(BaseModel):
    """Request model for orchestrator task execution."""

    task: str = Field(..., description="Task description to be executed")
    context: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional context information for the task"
    )
    agent_ids: Optional[List[str]] = Field(
        None,
        description="Optional list of specific agent IDs to use"
    )


class OrchestrateResponse(BaseModel):
    """Response model for orchestrator task execution."""

    success: bool = Field(..., description="Whether execution was successful")
    results: List[AgentResult] = Field(
        default_factory=list,
        description="Results from agent execution(s)"
    )
    message: Optional[str] = Field(None, description="Optional message")


class WorkflowExecuteRequest(BaseModel):
    """Request model for workflow execution."""

    workflow_id: str = Field(..., description="Workflow identifier to execute")
    input_data: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional input data for the workflow"
    )


class WorkflowExecuteResponse(BaseModel):
    """Response model for workflow execution."""

    success: bool = Field(..., description="Whether workflow execution was successful")
    result: Optional[WorkflowResult] = Field(
        None,
        description="Workflow execution result"
    )
    message: Optional[str] = Field(None, description="Optional message")


class AgentsListResponse(BaseModel):
    """Response model for listing agents."""

    agents: List[AgentInfo] = Field(..., description="List of available agents")
    count: int = Field(..., description="Total number of agents")


class AgentDetailResponse(BaseModel):
    """Response model for agent details."""

    agent: AgentInfo = Field(..., description="Agent information")


class HealthResponse(BaseModel):
    """Response model for health check."""

    status: str = Field(..., description="Health status")
    version: str = Field(..., description="Application version")
    timestamp: str = Field(..., description="Current timestamp")

