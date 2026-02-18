"""Persistence for MCP-centric runs."""

import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.db.database import SessionLocal
from app.db.models import Run, RunEvent


def create_run(
    goal: str,
    agent_profile_id: str = "default",
    context: Optional[Dict[str, Any]] = None,
) -> Run:
    """Create a new run with status pending. Returns the Run model."""
    run_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        run = Run(
            run_id=run_id,
            goal=goal,
            agent_profile_id=agent_profile_id,
            status="pending",
            context=context,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def append_run_event(run_id: str, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
    """Append an event for a run (for SSE streaming). DB-backed so workers can emit events."""
    db = SessionLocal()
    try:
        db.add(
            RunEvent(
                run_id=run_id,
                event_type=event_type,
                payload=payload or {},
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_run_events(
    run_id: str, after_id: Optional[int] = None, limit: int = 100
) -> List[Tuple[int, str, Dict[str, Any]]]:
    """
    Get events for a run, optionally after a given event id.
    Returns list of (event_id, event_type, payload).
    """
    db = SessionLocal()
    try:
        q = db.query(RunEvent).filter(RunEvent.run_id == run_id).order_by(RunEvent.id.asc())
        if after_id is not None:
            q = q.filter(RunEvent.id > after_id)
        rows = q.limit(limit).all()
        return [(r.id, r.event_type, r.payload or {}) for r in rows]
    finally:
        db.close()


def get_run_by_id(run_id: str) -> Optional[Run]:
    """Get run by run_id (uuid string)."""
    db = SessionLocal()
    try:
        return db.query(Run).filter(Run.run_id == run_id).first()
    finally:
        db.close()


def list_runs(
    limit: int = 20,
    offset: int = 0,
    status: Optional[str] = None,
) -> List[Run]:
    """List runs, newest first. Optional filter by status."""
    db = SessionLocal()
    try:
        q = db.query(Run).order_by(Run.created_at.desc())
        if status:
            q = q.filter(Run.status == status)
        return q.offset(offset).limit(limit).all()
    finally:
        db.close()


def update_run(
    run_id: str,
    status: Optional[str] = None,
    error: Optional[str] = None,
    answer: Optional[str] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
    tool_calls: Optional[List[Dict[str, Any]]] = None,
    completed_at: Optional[Any] = None,
    pending_tool_call: Optional[Dict[str, Any]] = None,
    _clear_pending_tool_call: bool = False,
) -> Optional[Run]:
    """Update run fields. Returns updated Run or None if not found.
    Use pending_tool_call={...} to set, or _clear_pending_tool_call=True to clear."""
    db = SessionLocal()
    try:
        run = db.query(Run).filter(Run.run_id == run_id).first()
        if not run:
            return None
        if status is not None:
            run.status = status
        if error is not None:
            run.error = error
        if answer is not None:
            run.answer = answer
        if steps is not None:
            run.steps = steps
        if tool_calls is not None:
            run.tool_calls = tool_calls
        if completed_at is not None:
            run.completed_at = completed_at
        if pending_tool_call is not None:
            run.pending_tool_call = pending_tool_call
        if _clear_pending_tool_call:
            run.pending_tool_call = None
        db.commit()
        db.refresh(run)
        return run
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
