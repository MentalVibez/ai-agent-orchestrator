"""DB-backed agent session memory (P1.1).

Stores per-agent, per-run state in the AgentState table using a composite key
of the form "{agent_id}:{run_id}" so agents can maintain context across tool calls
within a single run while isolating state between runs.
"""

import asyncio
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _composite_key(agent_id: str, run_id: Optional[str] = None) -> str:
    """Build the DB key: agent_id when run_id is None, else agent_id:run_id."""
    if run_id:
        return f"{agent_id}:{run_id}"
    return agent_id


def _load_session_state_sync(agent_id: str, run_id: Optional[str] = None) -> Dict[str, Any]:
    """Synchronous helper — runs in thread pool via asyncio.to_thread."""
    from app.db.database import SessionLocal
    from app.db.models import AgentState

    key = _composite_key(agent_id, run_id)
    db = SessionLocal()
    try:
        record = db.query(AgentState).filter(AgentState.agent_id == key).first()
        return dict(record.state_data) if record and record.state_data else {}
    finally:
        db.close()


def _save_session_state_sync(
    agent_id: str, state: Dict[str, Any], run_id: Optional[str] = None
) -> None:
    """Synchronous helper — runs in thread pool via asyncio.to_thread."""
    from datetime import datetime

    from app.db.database import SessionLocal
    from app.db.models import AgentState

    key = _composite_key(agent_id, run_id)
    db = SessionLocal()
    try:
        existing = db.query(AgentState).filter(AgentState.agent_id == key).first()
        if existing:
            existing.state_data = state
            existing.last_updated = datetime.utcnow()
        else:
            db.add(AgentState(agent_id=key, state_data=state))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def load_session_state(
    agent_id: str, run_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Load persisted session state for an agent (optionally scoped to a run).

    Args:
        agent_id: Agent identifier
        run_id: Optional run ID to scope the state

    Returns:
        State dict, empty if no state stored yet
    """
    try:
        return await asyncio.to_thread(_load_session_state_sync, agent_id, run_id)
    except Exception as e:
        logger.warning("Failed to load session state for %s: %s", agent_id, e)
        return {}


async def save_session_state(
    agent_id: str, state: Dict[str, Any], run_id: Optional[str] = None
) -> None:
    """
    Persist session state for an agent (optionally scoped to a run).

    Args:
        agent_id: Agent identifier
        state: State dict to persist
        run_id: Optional run ID to scope the state
    """
    try:
        await asyncio.to_thread(_save_session_state_sync, agent_id, state, run_id)
    except Exception as e:
        logger.warning("Failed to save session state for %s: %s", agent_id, e)
