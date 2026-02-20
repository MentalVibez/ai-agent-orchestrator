"""Unit tests for app/core/agent_memory.py.

Note: agent_memory.py imports SessionLocal and AgentState *inside* function bodies
(not at module level), so they must be patched at their source:
  app.db.database.SessionLocal  (not app.core.agent_memory.SessionLocal)
"""

from unittest.mock import MagicMock, patch

import pytest

from app.core.agent_memory import (
    _composite_key,
    _load_session_state_sync,
    _save_session_state_sync,
    load_session_state,
    save_session_state,
)


@pytest.mark.unit
class TestCompositeKey:
    """Tests for _composite_key() pure function."""

    def test_without_run_id_returns_agent_id(self):
        assert _composite_key("agent-x") == "agent-x"

    def test_with_run_id_returns_colon_separated(self):
        assert _composite_key("agent-x", "run-42") == "agent-x:run-42"

    def test_with_none_run_id_returns_agent_id(self):
        assert _composite_key("agent-x", None) == "agent-x"


def _make_db_mock(record=None):
    """Build a mock session with a configurable query result."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = record
    return db


@pytest.mark.unit
class TestLoadSessionStateSync:
    """Tests for _load_session_state_sync()."""

    def test_returns_state_data_when_record_exists(self):
        """Returns the record's state_data dict when found."""
        record = MagicMock()
        record.state_data = {"key": "value", "count": 1}
        db = _make_db_mock(record)

        with patch("app.db.database.SessionLocal", return_value=db):
            result = _load_session_state_sync("agent-x", "run-1")

        assert result == {"key": "value", "count": 1}

    def test_returns_empty_dict_when_no_record(self):
        """Returns {} when no record is found for the key."""
        db = _make_db_mock(None)

        with patch("app.db.database.SessionLocal", return_value=db):
            result = _load_session_state_sync("agent-x")

        assert result == {}

    def test_returns_empty_dict_when_state_data_is_none(self):
        """Returns {} when record exists but state_data is None."""
        record = MagicMock()
        record.state_data = None
        db = _make_db_mock(record)

        with patch("app.db.database.SessionLocal", return_value=db):
            result = _load_session_state_sync("agent-x")

        assert result == {}

    def test_closes_session_after_successful_query(self):
        """db.close() is called even on a successful query."""
        db = _make_db_mock(None)

        with patch("app.db.database.SessionLocal", return_value=db):
            _load_session_state_sync("agent-x")

        db.close.assert_called_once()

    def test_closes_session_after_exception(self):
        """db.close() is called even when the query raises."""
        db = MagicMock()
        db.query.side_effect = RuntimeError("DB error")

        with patch("app.db.database.SessionLocal", return_value=db):
            with pytest.raises(RuntimeError):
                _load_session_state_sync("agent-x")

        db.close.assert_called_once()


@pytest.mark.unit
class TestSaveSessionStateSync:
    """Tests for _save_session_state_sync()."""

    def test_updates_existing_record(self):
        """When a record exists, updates state_data and commits."""
        existing = MagicMock()
        db = _make_db_mock(existing)

        with patch("app.db.database.SessionLocal", return_value=db):
            _save_session_state_sync("agent-x", {"new": "state"}, "run-1")

        assert existing.state_data == {"new": "state"}
        db.commit.assert_called_once()
        db.add.assert_not_called()

    def test_creates_new_record_when_none_exists(self):
        """When no record is found, adds a new AgentState and commits."""
        db = _make_db_mock(None)

        with patch("app.db.database.SessionLocal", return_value=db):
            _save_session_state_sync("agent-x", {"data": 1})

        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_rollback_on_commit_exception(self):
        """If commit raises, rollback is called and exception propagates."""
        existing = MagicMock()
        db = _make_db_mock(existing)
        db.commit.side_effect = RuntimeError("Commit failed")

        with patch("app.db.database.SessionLocal", return_value=db):
            with pytest.raises(RuntimeError, match="Commit failed"):
                _save_session_state_sync("agent-x", {"state": "x"})

        db.rollback.assert_called_once()

    def test_closes_session_after_save(self):
        """db.close() is called after a successful save."""
        db = _make_db_mock(None)

        with patch("app.db.database.SessionLocal", return_value=db):
            _save_session_state_sync("agent-x", {})

        db.close.assert_called_once()


@pytest.mark.unit
class TestLoadSessionStateAsync:
    """Tests for load_session_state() async wrapper."""

    @pytest.mark.asyncio
    async def test_returns_dict_from_sync_helper(self):
        """Calls _load_session_state_sync and returns its result."""
        with patch(
            "app.core.agent_memory._load_session_state_sync",
            return_value={"x": 1},
        ):
            result = await load_session_state("agent-x", "run-1")
        assert result == {"x": 1}

    @pytest.mark.asyncio
    async def test_returns_empty_dict_on_exception(self):
        """Returns {} and does not propagate when sync helper raises."""
        with patch(
            "app.core.agent_memory._load_session_state_sync",
            side_effect=RuntimeError("DB down"),
        ):
            result = await load_session_state("agent-x")
        assert result == {}


@pytest.mark.unit
class TestSaveSessionStateAsync:
    """Tests for save_session_state() async wrapper."""

    @pytest.mark.asyncio
    async def test_calls_sync_helper(self):
        """Delegates to _save_session_state_sync with correct args."""
        with patch(
            "app.core.agent_memory._save_session_state_sync"
        ) as mock_sync:
            await save_session_state("agent-x", {"k": "v"}, "run-1")
        mock_sync.assert_called_once_with("agent-x", {"k": "v"}, "run-1")

    @pytest.mark.asyncio
    async def test_silences_exception_from_sync_helper(self):
        """Does not propagate exceptions from _save_session_state_sync."""
        with patch(
            "app.core.agent_memory._save_session_state_sync",
            side_effect=RuntimeError("DB down"),
        ):
            await save_session_state("agent-x", {})  # Should not raise
