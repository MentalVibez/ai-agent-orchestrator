"""Unit tests for run store (create_run, get_run_by_id, update_run, run_events)."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.run_store import append_run_event, create_run, get_run_by_id, get_run_events, update_run


@pytest.mark.unit
class TestRunStore:
    """Test cases for run store."""

    @patch("app.core.run_store.SessionLocal")
    @patch("app.core.run_store.uuid.uuid4")
    @patch("app.core.run_store.Run")
    async def test_create_run_returns_run_with_id(self, mock_run_cls, mock_uuid4, mock_session_local):
        mock_uuid4.return_value = MagicMock(__str__=lambda _: "test-uuid-123")
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_run = MagicMock()
        mock_run.run_id = "test-uuid-123"
        mock_run_cls.return_value = mock_run

        result = await create_run("Test goal", "default", None)

        assert result.run_id == "test-uuid-123"
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @patch("app.core.run_store.SessionLocal")
    async def test_get_run_by_id_returns_none_when_not_found(self, mock_session_local):
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = await get_run_by_id("nonexistent-id")
        assert result is None

    @patch("app.core.run_store.SessionLocal")
    async def test_get_run_by_id_returns_run_when_found(self, mock_session_local):
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_run = MagicMock()
        mock_run.run_id = "found-id"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_run

        result = await get_run_by_id("found-id")
        assert result is mock_run

    @patch("app.core.run_store.SessionLocal")
    async def test_update_run_returns_none_when_not_found(self, mock_session_local):
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = await update_run("nonexistent", status="cancelled")
        assert result is None
        mock_db.commit.assert_not_called()

    @patch("app.core.run_store.SessionLocal")
    async def test_update_run_updates_status(self, mock_session_local):
        mock_db = MagicMock()
        mock_run = MagicMock()
        mock_run.status = "running"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_run
        mock_session_local.return_value = mock_db

        result = await update_run("run-123", status="cancelled")
        assert result is mock_run
        assert mock_run.status == "cancelled"
        mock_db.commit.assert_called_once()

    @patch("app.core.run_store.SessionLocal")
    async def test_append_run_event_adds_event(self, mock_session_local):
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        await append_run_event("run-123", "status", {"status": "running"})
        mock_db.add.assert_called_once()
        added = mock_db.add.call_args[0][0]
        assert added.run_id == "run-123"
        assert added.event_type == "status"
        assert added.payload == {"status": "running"}
        mock_db.commit.assert_called_once()

    @patch("app.core.run_store.SessionLocal")
    async def test_get_run_events_returns_events_after_id(self, mock_session_local):
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_rows = [
            MagicMock(id=2, event_type="step", payload={"step_index": 1}),
            MagicMock(id=3, event_type="answer", payload={"answer": "done"}),
        ]
        chain = (
            mock_db.query.return_value.filter.return_value.order_by.return_value.filter.return_value.limit.return_value
        )
        chain.all.return_value = mock_rows

        result = await get_run_events("run-123", after_id=1)
        assert len(result) == 2
        assert result[0] == (2, "step", {"step_index": 1})
        assert result[1] == (3, "answer", {"answer": "done"})
