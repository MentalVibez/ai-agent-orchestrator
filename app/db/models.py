"""Database models for persistence."""

from sqlalchemy import Column, Integer, String, Float, DateTime, Text, JSON, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
from app.db.database import Base
import json


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
    metadata = Column(JSON, nullable=True)
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
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "execution_time_ms": self.execution_time_ms
        }


class AgentState(Base):
    """Model for storing agent state."""
    
    __tablename__ = "agent_state"
    
    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String, index=True, unique=True, nullable=False)
    state_data = Column(JSON, nullable=True)
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "state_data": self.state_data,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None
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
            "execution_time_ms": self.execution_time_ms
        }

