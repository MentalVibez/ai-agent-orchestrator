"""Integration tests for Metrics endpoints."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def api_key_enabled():
    """Fixture to enable API key requirement for tests."""
    original_require = settings.require_api_key
    original_key = settings.api_key
    settings.require_api_key = True
    settings.api_key = "test-api-key"
    yield
    settings.require_api_key = original_require
    settings.api_key = original_key


@pytest.mark.integration
class TestMetricsEndpoints:
    """Test cases for metrics endpoints."""

    def test_get_cost_metrics_success(self, client, api_key_enabled):
        """Test getting cost metrics."""
        with patch("app.api.v1.routes.metrics.get_cost_tracker") as mock_tracker:
            mock_tracker.return_value.get_total_cost.return_value = 10.0
            mock_tracker.return_value.get_cost_by_agent.return_value = {"agent1": 5.0}
            mock_tracker.return_value.get_cost_by_endpoint.return_value = {
                "/api/v1/orchestrate": 10.0
            }
            mock_tracker.return_value.get_token_usage.return_value = {
                "input_tokens": 1000,
                "output_tokens": 500,
                "total_tokens": 1500,
                "request_count": 5,
            }
            mock_tracker.return_value.get_recent_records.return_value = []

            response = client.get(
                "/api/v1/metrics/costs?days=7",
                headers={"X-API-Key": "test-api-key"},
            )

            assert response.status_code == 200
            data = response.json()
            assert "total_cost" in data or "metrics" in data or "success" in data

    def test_get_cost_metrics_requires_api_key(self, client, api_key_enabled):
        """Test that cost metrics requires API key."""
        response = client.get("/api/v1/metrics/costs")
        assert response.status_code in [401, 403]

    def test_get_daily_cost_success(self, client, api_key_enabled):
        """Test getting daily cost."""
        with patch("app.api.v1.routes.metrics.get_cost_tracker") as mock_tracker:
            mock_tracker.return_value.get_daily_cost.return_value = 5.0
            mock_tracker.return_value.get_cost_by_agent.return_value = {}
            mock_tracker.return_value.get_cost_by_endpoint.return_value = {}
            mock_tracker.return_value.get_token_usage.return_value = {}

            response = client.get(
                "/api/v1/metrics/costs/daily",
                headers={"X-API-Key": "test-api-key"},
            )
            assert response.status_code == 200

    def test_get_daily_cost_with_date(self, client, api_key_enabled):
        """Test getting daily cost with specific date."""
        with patch("app.api.v1.routes.metrics.get_cost_tracker") as mock_tracker:
            mock_tracker.return_value.get_daily_cost.return_value = 3.0
            mock_tracker.return_value.get_cost_by_agent.return_value = {}
            mock_tracker.return_value.get_cost_by_endpoint.return_value = {}
            mock_tracker.return_value.get_token_usage.return_value = {}

            response = client.get(
                "/api/v1/metrics/costs/daily?date=2024-01-01",
                headers={"X-API-Key": "test-api-key"},
            )
            assert response.status_code in [200, 400]
