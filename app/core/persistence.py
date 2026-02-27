"""Persistence layer for storing execution history and agent state."""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.db.database import SessionLocal
from app.db.models import AgentState, ExecutionHistory, WorkflowExecution
from app.models.agent import AgentResult

# ---------------------------------------------------------------------------
# Private sync helpers (run in thread pool via asyncio.to_thread)
# ---------------------------------------------------------------------------


def _save_execution_history_sync(
    result: AgentResult,
    request_id: Optional[str] = None,
    execution_time_ms: Optional[float] = None,
) -> ExecutionHistory:
    db = SessionLocal()
    try:
        history = ExecutionHistory(
            request_id=request_id,
            agent_id=result.agent_id,
            agent_name=result.agent_name,
            task=str(result.metadata.get("task", "")) if result.metadata else "",
            context=result.metadata.get("context") if result.metadata else None,
            success=result.success,
            output=result.output
            if isinstance(result.output, dict)
            else {"output": str(result.output)},
            error=result.error,
            execution_metadata=result.metadata if result.metadata else None,
            execution_time_ms=execution_time_ms,
        )
        db.add(history)
        db.commit()
        db.refresh(history)
        return history
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _get_execution_history_sync(
    agent_id: Optional[str] = None,
    request_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[ExecutionHistory]:
    db = SessionLocal()
    try:
        query = db.query(ExecutionHistory)
        if agent_id:
            query = query.filter(ExecutionHistory.agent_id == agent_id)
        if request_id:
            query = query.filter(ExecutionHistory.request_id == request_id)
        return query.order_by(ExecutionHistory.created_at.desc()).offset(offset).limit(limit).all()
    finally:
        db.close()


def _save_agent_state_sync(agent_id: str, state_data: Dict[str, Any]) -> AgentState:
    db = SessionLocal()
    try:
        existing = db.query(AgentState).filter(AgentState.agent_id == agent_id).first()
        if existing:
            existing.state_data = state_data
            existing.last_updated = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()
            db.refresh(existing)
            return existing
        else:
            state = AgentState(agent_id=agent_id, state_data=state_data)
            db.add(state)
            db.commit()
            db.refresh(state)
            return state
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _get_agent_state_sync(agent_id: str) -> Optional[Dict[str, Any]]:
    db = SessionLocal()
    try:
        state = db.query(AgentState).filter(AgentState.agent_id == agent_id).first()
        if state:
            return state.state_data
        return None
    finally:
        db.close()


def _save_workflow_execution_sync(
    workflow_id: str,
    input_data: Optional[Dict[str, Any]] = None,
    output_data: Optional[Dict[str, Any]] = None,
    status: str = "completed",
    error: Optional[str] = None,
    execution_time_ms: Optional[float] = None,
) -> WorkflowExecution:
    db = SessionLocal()
    try:
        execution = WorkflowExecution(
            workflow_id=workflow_id,
            input_data=input_data,
            output_data=output_data,
            status=status,
            error=error,
            execution_time_ms=execution_time_ms,
            completed_at=datetime.now(timezone.utc).replace(tzinfo=None) if status in ["completed", "failed"] else None,
        )
        db.add(execution)
        db.commit()
        db.refresh(execution)
        return execution
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------


async def save_execution_history(
    result: AgentResult,
    request_id: Optional[str] = None,
    execution_time_ms: Optional[float] = None,
) -> ExecutionHistory:
    """
    Save execution history to database.

    Args:
        result: AgentResult to save
        request_id: Optional request ID
        execution_time_ms: Optional execution time in milliseconds

    Returns:
        ExecutionHistory instance
    """
    return await asyncio.to_thread(
        _save_execution_history_sync, result, request_id, execution_time_ms
    )


async def get_execution_history(
    agent_id: Optional[str] = None,
    request_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[ExecutionHistory]:
    """
    Get execution history.

    Args:
        agent_id: Optional agent ID filter
        request_id: Optional request ID filter
        limit: Maximum number of records
        offset: Offset for pagination

    Returns:
        List of ExecutionHistory instances
    """
    return await asyncio.to_thread(
        _get_execution_history_sync, agent_id, request_id, limit, offset
    )


async def save_agent_state(agent_id: str, state_data: Dict[str, Any]) -> AgentState:
    """
    Save agent state to database.

    Args:
        agent_id: Agent identifier
        state_data: State data to save

    Returns:
        AgentState instance
    """
    return await asyncio.to_thread(_save_agent_state_sync, agent_id, state_data)


async def get_agent_state(agent_id: str) -> Optional[Dict[str, Any]]:
    """
    Get agent state from database.

    Args:
        agent_id: Agent identifier

    Returns:
        State data if found, None otherwise
    """
    return await asyncio.to_thread(_get_agent_state_sync, agent_id)


async def save_workflow_execution(
    workflow_id: str,
    input_data: Optional[Dict[str, Any]] = None,
    output_data: Optional[Dict[str, Any]] = None,
    status: str = "completed",
    error: Optional[str] = None,
    execution_time_ms: Optional[float] = None,
) -> WorkflowExecution:
    """
    Save workflow execution to database.

    Args:
        workflow_id: Workflow identifier
        input_data: Input data
        output_data: Output data
        status: Execution status
        error: Optional error message
        execution_time_ms: Optional execution time

    Returns:
        WorkflowExecution instance
    """
    return await asyncio.to_thread(
        _save_workflow_execution_sync,
        workflow_id,
        input_data,
        output_data,
        status,
        error,
        execution_time_ms,
    )
