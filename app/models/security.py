"""Security models for agent sandboxing and permissions."""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class ResourceLimitsConfig(BaseModel):
    """Resource limits configuration."""
    
    max_cpu_time: float = Field(default=30.0, description="Maximum CPU time in seconds")
    max_memory_mb: int = Field(default=512, description="Maximum memory in megabytes")
    max_execution_time: float = Field(default=60.0, description="Maximum execution time in seconds")
    allowed_operations: List[str] = Field(default_factory=list, description="Allowed operations")


class AuditLogEntry(BaseModel):
    """Audit log entry."""
    
    timestamp: str = Field(..., description="Timestamp of the action")
    operation: str = Field(..., description="Operation name")
    action: str = Field(..., description="Action type (start, success, error, etc.)")
    duration: Optional[float] = Field(None, description="Duration in seconds")
    error: Optional[str] = Field(None, description="Error message if applicable")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class SecurityConfig(BaseModel):
    """Security configuration for an agent."""
    
    agent_id: str = Field(..., description="Agent identifier")
    resource_limits: ResourceLimitsConfig = Field(..., description="Resource limits")
    allowed_operations: List[str] = Field(default_factory=list, description="Allowed operations")
    audit_log: List[AuditLogEntry] = Field(default_factory=list, description="Audit log entries")

