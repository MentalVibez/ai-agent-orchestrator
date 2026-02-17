"""Pydantic models for workflows."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class WorkflowStepStatus(str, Enum):
    """Workflow step execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowStep(BaseModel):
    """Represents a single step in a workflow."""

    step_id: str = Field(..., description="Unique step identifier")
    name: str = Field(..., description="Step name")
    agent_id: str = Field(..., description="Agent to execute this step")
    task: str = Field(..., description="Task description for the agent")
    depends_on: List[str] = Field(
        default_factory=list, description="List of step IDs this step depends on"
    )
    context: Optional[Dict[str, Any]] = Field(
        None, description="Optional context data for the step"
    )


class Workflow(BaseModel):
    """Workflow definition."""

    workflow_id: str = Field(..., description="Unique workflow identifier")
    name: str = Field(..., description="Workflow name")
    description: str = Field(..., description="Workflow description")
    steps: List[WorkflowStep] = Field(..., description="List of workflow steps")
    enabled: bool = Field(default=True, description="Whether workflow is enabled")


class WorkflowStepResult(BaseModel):
    """Result from a single workflow step."""

    step_id: str = Field(..., description="Step identifier")
    status: WorkflowStepStatus = Field(..., description="Step execution status")
    agent_result: Optional[Any] = Field(None, description="Agent execution result")
    error: Optional[str] = Field(None, description="Error message if step failed")
    duration: Optional[float] = Field(None, description="Step execution duration in seconds")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow, description="Step execution timestamp"
    )


class WorkflowResult(BaseModel):
    """Result from workflow execution."""

    workflow_id: str = Field(..., description="Workflow identifier")
    success: bool = Field(..., description="Whether workflow completed successfully")
    step_results: List[WorkflowStepResult] = Field(
        default_factory=list, description="Results from each workflow step"
    )
    output: Optional[Dict[str, Any]] = Field(None, description="Aggregated workflow output")
    error: Optional[str] = Field(None, description="Error message if workflow failed")
    duration: Optional[float] = Field(
        None, description="Total workflow execution duration in seconds"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow, description="Workflow execution timestamp"
    )
