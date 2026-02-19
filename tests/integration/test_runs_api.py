"""Integration tests for runs API (POST /run, GET /runs/:id)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.database import init_db
from app.main import app


@pytest.fixture
def client():
    import app.core.persistence as persistence_module
    import app.core.run_store as run_store_module
    import app.db.database as db_module

    # Use in-memory SQLite with StaticPool so all threads share the same DB.
    # StaticPool ensures the single in-memory connection is shared across threads.
    new_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    new_session_factory = sessionmaker(autocommit=False, autoflush=False, bind=new_engine)

    # Patch the module-level attribute AND any by-value imports in consumer modules
    db_module.engine = new_engine
    db_module.SessionLocal = new_session_factory
    run_store_module.SessionLocal = new_session_factory
    persistence_module.SessionLocal = new_session_factory

    init_db()
    return TestClient(app)


@pytest.fixture
def api_key_disabled():
    """Disable API key so requests don't need X-API-Key."""
    orig_require = settings.require_api_key
    orig_key = settings.api_key
    settings.require_api_key = False
    settings.api_key = ""
    yield
    settings.require_api_key = orig_require
    settings.api_key = orig_key


@pytest.mark.integration
class TestRunsAPI:
    """Test cases for runs API."""

    def test_post_run_returns_201_with_run_id(self, client, api_key_disabled):
        """POST /api/v1/run returns 201 and run_id when goal and profile are valid."""
        with patch(
            "app.api.v1.routes.runs.run_planner_loop", new_callable=AsyncMock
        ) as mock_planner:
            mock_planner.return_value = None
            with patch("app.api.v1.routes.runs.asyncio.create_task") as mock_create_task:
                mock_create_task.return_value = None
                response = client.post(
                    "/api/v1/run",
                    json={
                        "goal": "Check connectivity to example.com",
                        "agent_profile_id": "default",
                    },
                )
        assert response.status_code == 201
        data = response.json()
        assert "run_id" in data
        assert data["goal"] == "Check connectivity to example.com"
        assert data["agent_profile_id"] == "default"
        assert data["status"] in ("pending", "running", "completed")

    def test_get_run_returns_200_with_run_details(self, client, api_key_disabled):
        """After POST /run, GET /runs/:id returns 200 and run details."""
        with patch("app.api.v1.routes.runs.run_planner_loop", new_callable=AsyncMock):
            with patch("app.api.v1.routes.runs.asyncio.create_task"):
                post_resp = client.post(
                    "/api/v1/run",
                    json={"goal": "Simple goal", "agent_profile_id": "default"},
                )
        assert post_resp.status_code == 201
        run_id = post_resp.json()["run_id"]

        get_resp = client.get(f"/api/v1/runs/{run_id}")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["run_id"] == run_id
        assert data["goal"] == "Simple goal"
        assert "status" in data
        assert "steps" in data
        assert "tool_calls" in data

    def test_get_run_404_for_unknown_id(self, client, api_key_disabled):
        """GET /runs/:id returns 404 for unknown run_id."""
        response = client.get("/api/v1/runs/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404

    def test_stream_run_returns_sse_events(self, client, api_key_disabled):
        """GET /runs/:id/stream returns SSE stream with status, step, answer, end events."""
        run_id = "test-run-stream-123"
        mock_run = MagicMock()
        mock_run.run_id = run_id
        mock_run.status = "completed"
        events_first_call = [
            (1, "status", {"status": "running"}),
            (2, "step", {"step_index": 1, "kind": "finish"}),
            (3, "answer", {"answer": "Done."}),
        ]

        with patch("app.api.v1.routes.runs.get_run_by_id", return_value=mock_run):
            with patch("app.api.v1.routes.runs.get_run_events", side_effect=[events_first_call, []]):
                with client.stream("GET", f"/api/v1/runs/{run_id}/stream") as response:
                    assert response.status_code == 200
                    assert "text/event-stream" in response.headers.get("content-type", "")
                    chunks = list(response.iter_bytes())
        body = b"".join(chunks).decode("utf-8")
        assert "event: status" in body
        assert "event: step" in body
        assert "event: answer" in body
        assert "event: end" in body
        assert "running" in body
        assert "Done." in body

    def test_stream_run_404_for_unknown_id(self, client, api_key_disabled):
        """GET /runs/:id/stream returns 404 for unknown run_id."""
        with patch("app.api.v1.routes.runs.get_run_by_id", return_value=None):
            response = client.get("/api/v1/runs/00000000-0000-0000-0000-000000000000/stream")
        assert response.status_code == 404

    def test_post_run_in_process_when_queue_disabled(self, client, api_key_disabled):
        """When enqueue_run returns False (queue disabled), planner is run via create_task."""
        with patch("app.api.v1.routes.runs.run_planner_loop", new_callable=AsyncMock) as mock_planner:
            with patch("app.api.v1.routes.runs.enqueue_run", new_callable=AsyncMock) as mock_enqueue:
                mock_enqueue.return_value = False
                with patch("app.api.v1.routes.runs.asyncio.create_task") as mock_create_task:
                    response = client.post(
                        "/api/v1/run",
                        json={"goal": "Simple goal", "agent_profile_id": "default"},
                    )
        assert response.status_code == 201
        mock_enqueue.assert_called_once()
        mock_create_task.assert_called_once()
        # run_planner_loop is called once to create the coroutine for create_task,
        # but is never directly awaited — the task runner handles execution.
        mock_planner.assert_called_once()

    def test_post_run_enqueued_when_queue_returns_true(self, client, api_key_disabled):
        """When enqueue_run returns True, planner is not run in-process (worker will run it)."""
        with patch("app.api.v1.routes.runs.run_planner_loop", new_callable=AsyncMock) as mock_planner:
            with patch("app.api.v1.routes.runs.enqueue_run", new_callable=AsyncMock) as mock_enqueue:
                mock_enqueue.return_value = True
                with patch("app.api.v1.routes.runs.asyncio.create_task") as mock_create_task:
                    response = client.post(
                        "/api/v1/run",
                        json={"goal": "Simple goal", "agent_profile_id": "default"},
                    )
        assert response.status_code == 201
        mock_enqueue.assert_called_once()
        mock_create_task.assert_not_called()
        mock_planner.assert_not_called()
