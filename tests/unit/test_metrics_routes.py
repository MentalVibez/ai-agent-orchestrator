"""Unit tests for app/api/v1/routes/metrics.py — cost metrics endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.database import init_db
from app.main import app


# ---------------------------------------------------------------------------
# Module-level DB patch (prevents "unable to open database file" on Windows)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def use_in_memory_db():
    """Redirect all DB calls to an in-memory SQLite DB for this test module."""
    import app.core.persistence as persistence_module
    import app.core.run_store as run_store_module
    import app.db.database as db_module

    original_engine = db_module.engine
    original_session = db_module.SessionLocal
    original_run_store_session = run_store_module.SessionLocal
    original_persistence_session = persistence_module.SessionLocal

    new_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    new_session_factory = sessionmaker(autocommit=False, autoflush=False, bind=new_engine)

    db_module.engine = new_engine
    db_module.SessionLocal = new_session_factory
    run_store_module.SessionLocal = new_session_factory
    persistence_module.SessionLocal = new_session_factory

    init_db()
    yield

    db_module.engine = original_engine
    db_module.SessionLocal = original_session
    run_store_module.SessionLocal = original_run_store_session
    persistence_module.SessionLocal = original_persistence_session


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_disabled():
    """Disable API key requirement for tests."""
    original_require = settings.require_api_key
    original_key = settings.api_key
    settings.require_api_key = False
    settings.api_key = None
    yield
    settings.require_api_key = original_require
    settings.api_key = original_key


@pytest.fixture
def mock_tracker():
    """Return a mock CostTracker with sensible defaults."""
    tracker = MagicMock()
    tracker.get_total_cost.return_value = 1.23
    tracker.get_cost_by_agent.return_value = {"agent-1": 0.50, "agent-2": 0.73}
    tracker.get_cost_by_endpoint.return_value = {"/api/v1/runs": 1.00, "/api/v1/agents": 0.23}
    tracker.get_token_usage.return_value = {"input": 1000, "output": 500}
    tracker.get_recent_records.return_value = []
    tracker.get_daily_cost.return_value = 0.42
    return tracker


@pytest.fixture
def client(auth_disabled, mock_tracker):
    """TestClient with auth disabled and get_cost_tracker patched."""
    with patch("app.api.v1.routes.metrics.get_cost_tracker", return_value=mock_tracker):
        with TestClient(app) as tc:
            yield tc, mock_tracker


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetCostMetrics:
    """Tests for GET /api/v1/metrics/costs."""

    def test_returns_200_with_success_true(self, client):
        tc, tracker = client
        response = tc.get("/api/v1/metrics/costs")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "metrics" in data
        assert data["metrics"]["total_cost"] == pytest.approx(1.23)

    def test_default_days_triggers_cost_lookup(self, client):
        tc, tracker = client
        tc.get("/api/v1/metrics/costs")
        tracker.get_total_cost.assert_called_once()

    def test_with_agent_filter(self, client):
        tc, tracker = client
        response = tc.get("/api/v1/metrics/costs?agent_id=agent-1")
        assert response.status_code == 200
        data = response.json()
        assert "agent-1" in data["metrics"]["cost_by_agent"]
        assert "agent-2" not in data["metrics"]["cost_by_agent"]

    def test_with_endpoint_filter(self, client):
        tc, tracker = client
        response = tc.get("/api/v1/metrics/costs?endpoint=/api/v1/runs")
        assert response.status_code == 200
        data = response.json()
        assert "/api/v1/runs" in data["metrics"]["cost_by_endpoint"]
        assert "/api/v1/agents" not in data["metrics"]["cost_by_endpoint"]

    def test_returns_500_on_exception(self, auth_disabled):
        tracker = MagicMock()
        tracker.get_total_cost.side_effect = RuntimeError("db down")
        with patch("app.api.v1.routes.metrics.get_cost_tracker", return_value=tracker):
            with TestClient(app) as tc:
                response = tc.get("/api/v1/metrics/costs")
        assert response.status_code == 500


@pytest.mark.unit
class TestGetDailyCost:
    """Tests for GET /api/v1/metrics/costs/daily."""

    def test_returns_200_with_success_true(self, client):
        tc, tracker = client
        response = tc.get("/api/v1/metrics/costs/daily")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["metrics"]["total_cost"] == pytest.approx(0.42)

    def test_with_explicit_date(self, client):
        import datetime

        tc, tracker = client
        response = tc.get("/api/v1/metrics/costs/daily?date=2026-01-15")
        assert response.status_code == 200
        call_kwargs = tracker.get_daily_cost.call_args
        assert call_kwargs.kwargs["date"] == datetime.date(2026, 1, 15)

    def test_invalid_date_returns_400(self, client):
        tc, _ = client
        response = tc.get("/api/v1/metrics/costs/daily?date=not-a-date")
        assert response.status_code == 400
        assert "Invalid date format" in response.json()["detail"]

    def test_with_agent_filter(self, client):
        tc, tracker = client
        response = tc.get("/api/v1/metrics/costs/daily?agent_id=agent-1")
        assert response.status_code == 200
        data = response.json()
        assert "agent-1" in data["metrics"]["cost_by_agent"]
        assert "agent-2" not in data["metrics"]["cost_by_agent"]

    def test_returns_500_on_exception(self, auth_disabled):
        tracker = MagicMock()
        tracker.get_daily_cost.side_effect = RuntimeError("db down")
        with patch("app.api.v1.routes.metrics.get_cost_tracker", return_value=tracker):
            with TestClient(app) as tc:
                response = tc.get("/api/v1/metrics/costs/daily")
        assert response.status_code == 500
