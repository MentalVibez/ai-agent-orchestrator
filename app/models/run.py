"""Pydantic models for MCP-centric runs (goal, plan, tool calls, result)."""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunRequest(BaseModel):
    """Request to start a new run."""

    goal: str = Field(..., description="User goal to achieve")
    agent_profile_id: Optional[str] = Field(
        default="default", description="Agent profile (from agent_profiles.yaml)"
    )
    context: Optional[Dict[str, Any]] = Field(None, description="Optional context for the run")
    stream_tokens: bool = Field(
        default=False,
        description="When true, LLM token chunks are emitted as SSE 'token' events during the run",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "goal": "Fetch https://example.com and summarize the main heading",
                    "agent_profile_id": "default",
                },
                {
                    "goal": "Open example.com in the browser and tell me the page title",
                    "agent_profile_id": "browser",
                    "context": {},
                },
            ]
        }
    }


class ToolCallRecord(BaseModel):
    """Record of one MCP tool call in a run."""

    server_id: str = Field(..., description="MCP server id")
    tool_name: str = Field(..., description="Tool name")
    arguments: Dict[str, Any] = Field(default_factory=dict)
    result_summary: Optional[str] = Field(None, description="Short result or error")
    is_error: bool = Field(default=False)


class PlanStep(BaseModel):
    """One step in the planner output (tool call or finish)."""

    step_index: int = Field(..., description="1-based step number")
    kind: str = Field(..., description="tool_call | finish")
    tool_call: Optional[ToolCallRecord] = None
    finish_answer: Optional[str] = None
    raw_response: Optional[str] = None


class RunResponse(BaseModel):
    """Response after starting a run (run_id and status)."""

    run_id: str = Field(..., description="Unique run identifier")
    status: RunStatus = Field(..., description="Current status")
    goal: str = Field(..., description="Goal")
    agent_profile_id: str = Field(..., description="Profile used")
    created_at: Optional[str] = None
    message: Optional[str] = None


class ApproveRunRequest(BaseModel):
    """Request to approve or reject a pending tool call (HITL)."""

    approved: bool = Field(..., description="True to execute the pending tool call, false to reject")
    modified_arguments: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional override for the tool arguments (only when approved=true)",
    )


class RunDetailResponse(BaseModel):
    """Full run details (for GET /runs/:id)."""

    run_id: str
    status: RunStatus
    goal: str
    agent_profile_id: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    answer: Optional[str] = Field(None, description="Final answer when status=completed")
    steps: List[Any] = Field(default_factory=list, description="Plan steps / tool calls")
    tool_calls: List[Any] = Field(default_factory=list)
    pending_approval: Optional[Dict[str, Any]] = Field(
        None,
        description="When status=awaiting_approval, the pending tool call (server_id, tool_name, arguments, step_index)",
    )
    message: Optional[str] = None
