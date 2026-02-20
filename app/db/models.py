"""Database models for persistence."""

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.sql import func

from app.db.database import Base


class ExecutionHistory(Base):
    """Model for storing execution history."""

    __tablename__ = "execution_history"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String, index=True, nullable=True)
    agent_id = Column(String, index=True, nullable=False)
    agent_name = Column(String, nullable=False)
    task = Column(Text, nullable=False)
    context = Column(JSON, nullable=True)
    success = Column(Boolean, default=False)
    output = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    execution_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    execution_time_ms = Column(Float, nullable=True)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "request_id": self.request_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "task": self.task,
            "context": self.context,
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "metadata": self.execution_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "execution_time_ms": self.execution_time_ms,
        }


class AgentState(Base):
    """Model for storing agent state."""

    __tablename__ = "agent_state"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String, index=True, unique=True, nullable=False)
    state_data = Column(JSON, nullable=True)
    last_updated = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "state_data": self.state_data,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
        }


class WorkflowExecution(Base):
    """Model for storing workflow executions."""

    __tablename__ = "workflow_executions"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(String, index=True, nullable=False)
    input_data = Column(JSON, nullable=True)
    output_data = Column(JSON, nullable=True)
    status = Column(String, default="pending")  # pending, running, completed, failed
    error = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    execution_time_ms = Column(Float, nullable=True)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "status": self.status,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "execution_time_ms": self.execution_time_ms,
        }


class RunEvent(Base):
    """Event emitted during a run for SSE streaming (DB-backed for cross-process compatibility)."""

    __tablename__ = "run_events"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(String, index=True, nullable=False)
    event_type = Column(String, nullable=False)  # status, step, tool_call, answer
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Run(Base):
    """MCP-centric run: goal, profile, status, steps and tool calls stored as JSON."""

    __tablename__ = "runs"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(String, unique=True, index=True, nullable=False)  # uuid
    goal = Column(Text, nullable=False)
    agent_profile_id = Column(String, index=True, nullable=False, default="default")
    status = Column(String, index=True, nullable=False, default="pending")
    error = Column(Text, nullable=True)
    answer = Column(Text, nullable=True)
    steps = Column(JSON, nullable=True)  # list of PlanStep-like dicts
    tool_calls = Column(JSON, nullable=True)  # list of ToolCallRecord-like dicts
    context = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)
    # When status is awaiting_approval, holds { server_id, tool_name, arguments, reason? } for HITL.
    pending_tool_call = Column(JSON, nullable=True)
    # P2.3: LangGraph-style checkpointing — last completed step index (0 = not started)
    checkpoint_step_index = Column(Integer, default=0, nullable=True)

    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        out = {
            "run_id": self.run_id,
            "goal": self.goal,
            "agent_profile_id": self.agent_profile_id,
            "status": self.status,
            "error": self.error,
            "answer": self.answer,
            "steps": self.steps or [],
            "tool_calls": self.tool_calls or [],
            "context": self.context,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
        if self.status == "awaiting_approval":
            pending = getattr(self, "pending_tool_call", None)
            if pending:
                out["pending_approval"] = pending
        return out


class CostRecordDB(Base):
    """Persisted record of a single LLM call cost (P1.4)."""

    __tablename__ = "cost_records"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(String, index=True, nullable=True)
    provider = Column(String, nullable=False)
    model = Column(String, nullable=False)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    agent_id = Column(String, nullable=True)
    endpoint = Column(String, nullable=True)
    request_id = Column(String, nullable=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "run_id": self.run_id,
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "agent_id": self.agent_id,
            "endpoint": self.endpoint,
            "request_id": self.request_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }
