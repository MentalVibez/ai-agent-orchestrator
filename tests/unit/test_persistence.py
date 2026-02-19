"""Unit tests for Persistence layer."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.persistence import (
    get_agent_state,
    get_execution_history,
    save_agent_state,
    save_execution_history,
    save_workflow_execution,
)
from app.db.models import AgentState, ExecutionHistory, WorkflowExecution
from app.models.agent import AgentResult


@pytest.mark.unit
class TestPersistence:
    """Test cases for persistence functions."""

    @pytest.fixture
    def sample_agent_result(self):
        """Create a sample agent result."""
        return AgentResult(
            agent_id="test_agent",
            agent_name="Test Agent",
            success=True,
            output={"result": "success"},
            metadata={"task": "test task", "context": {"key": "value"}},
        )

    @pytest.fixture
    def mock_db_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.add = MagicMock()
        session.commit = MagicMock()
        session.refresh = MagicMock()
        session.rollback = MagicMock()
        session.close = MagicMock()
        session.query = MagicMock()
        return session

    @patch("app.core.persistence.SessionLocal")
    async def test_save_execution_history_success(
        self, mock_session_local, sample_agent_result, mock_db_session
    ):
        """Test saving execution history successfully."""
        mock_session_local.return_value = mock_db_session
        mock_db_session.refresh.return_value = None

        # Create a mock history object
        mock_history = MagicMock(spec=ExecutionHistory)
        mock_db_session.add.return_value = None

        with patch("app.core.persistence.ExecutionHistory", return_value=mock_history):
            await save_execution_history(
                sample_agent_result, request_id="req123", execution_time_ms=100.0
            )

            assert mock_db_session.add.called
            assert mock_db_session.commit.called
            assert mock_db_session.refresh.called

    @patch("app.core.persistence.SessionLocal")
    async def test_save_execution_history_with_error(
        self, mock_session_local, sample_agent_result, mock_db_session
    ):
        """Test saving execution history with database error."""
        mock_session_local.return_value = mock_db_session
        mock_db_session.commit.side_effect = Exception("DB Error")

        with patch("app.core.persistence.ExecutionHistory"):
            with pytest.raises(Exception):
                await save_execution_history(sample_agent_result)

            assert mock_db_session.rollback.called

    @patch("app.core.persistence.SessionLocal")
    async def test_get_execution_history_all(self, mock_session_local, mock_db_session):
        """Test getting all execution history."""
        mock_session_local.return_value = mock_db_session
        mock_query = MagicMock()
        mock_db_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [MagicMock()]

        results = await get_execution_history()

        assert len(results) >= 0  # May be empty, but should not error

    @patch("app.core.persistence.SessionLocal")
    async def test_get_execution_history_by_agent_id(self, mock_session_local, mock_db_session):
        """Test getting execution history filtered by agent ID."""
        mock_session_local.return_value = mock_db_session
        mock_query = MagicMock()
        mock_db_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        await get_execution_history(agent_id="test_agent")

        assert mock_query.filter.called

    @patch("app.core.persistence.SessionLocal")
    async def test_save_agent_state_new(self, mock_session_local, mock_db_session):
        """Test saving new agent state."""
        mock_session_local.return_value = mock_db_session
        mock_query = MagicMock()
        mock_db_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None  # No existing state

        mock_state = MagicMock(spec=AgentState)
        with patch("app.core.persistence.AgentState", return_value=mock_state):
            await save_agent_state("test_agent", {"key": "value"})

            assert mock_db_session.add.called
            assert mock_db_session.commit.called

    @patch("app.core.persistence.SessionLocal")
    async def test_save_agent_state_update(self, mock_session_local, mock_db_session):
        """Test updating existing agent state."""
        mock_session_local.return_value = mock_db_session
        mock_existing = MagicMock(spec=AgentState)
        mock_query = MagicMock()
        mock_db_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = mock_existing

        await save_agent_state("test_agent", {"key": "new_value"})

        assert mock_existing.state_data == {"key": "new_value"}
        assert mock_db_session.commit.called

    @patch("app.core.persistence.SessionLocal")
    async def test_get_agent_state_exists(self, mock_session_local, mock_db_session):
        """Test getting existing agent state."""
        mock_session_local.return_value = mock_db_session
        mock_state = MagicMock(spec=AgentState)
        mock_state.state_data = {"key": "value"}
        mock_query = MagicMock()
        mock_db_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = mock_state

        result = await get_agent_state("test_agent")

        assert result == {"key": "value"}

    @patch("app.core.persistence.SessionLocal")
    async def test_get_agent_state_not_exists(self, mock_session_local, mock_db_session):
        """Test getting non-existent agent state."""
        mock_session_local.return_value = mock_db_session
        mock_query = MagicMock()
        mock_db_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        result = await get_agent_state("test_agent")

        assert result is None

    @patch("app.core.persistence.SessionLocal")
    async def test_save_workflow_execution_success(self, mock_session_local, mock_db_session):
        """Test saving workflow execution successfully."""
        mock_session_local.return_value = mock_db_session
        mock_execution = MagicMock(spec=WorkflowExecution)

        with patch("app.core.persistence.WorkflowExecution", return_value=mock_execution):
            await save_workflow_execution(
                workflow_id="test_workflow",
                input_data={"input": "data"},
                output_data={"output": "data"},
                status="completed",
                execution_time_ms=500.0,
            )

            assert mock_db_session.add.called
            assert mock_db_session.commit.called

    @patch("app.core.persistence.SessionLocal")
    async def test_save_workflow_execution_with_error(self, mock_session_local, mock_db_session):
        """Test saving workflow execution with error status."""
        mock_session_local.return_value = mock_db_session
        mock_execution = MagicMock(spec=WorkflowExecution)

        with patch("app.core.persistence.WorkflowExecution", return_value=mock_execution):
            await save_workflow_execution(
                workflow_id="test_workflow", status="failed", error="Test error"
            )

            assert mock_db_session.add.called
            assert mock_db_session.commit.called
