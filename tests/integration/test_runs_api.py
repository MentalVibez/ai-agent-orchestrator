"""Integration tests for runs API (POST /run, GET /runs/:id)."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.database import init_db
from app.main import app


@pytest.fixture
def client():
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
