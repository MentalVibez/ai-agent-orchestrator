"""Pydantic models for agents."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AgentCapability(BaseModel):
    """Represents an agent capability."""

    name: str = Field(..., description="Capability name")
    description: str = Field(..., description="Capability description")


class AgentInfo(BaseModel):
    """Agent information model."""

    agent_id: str = Field(..., description="Unique agent identifier")
    name: str = Field(..., description="Agent name")
    description: str = Field(..., description="Agent description")
    capabilities: List[AgentCapability] = Field(
        default_factory=list, description="List of agent capabilities"
    )


class AgentResult(BaseModel):
    """Result from agent execution."""

    agent_id: str = Field(..., description="Agent identifier")
    agent_name: str = Field(..., description="Agent name")
    success: bool = Field(..., description="Whether execution was successful")
    output: Any = Field(..., description="Output data from agent")
    error: Optional[str] = Field(None, description="Error message if execution failed")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Execution timestamp")
