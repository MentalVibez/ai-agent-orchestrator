"""Integration tests for run template routes (GET /run/templates, POST /run/template/{name})."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from unittest.mock import MagicMock

from app.core.config import settings
from app.db.database import init_db
from app.main import app

# ---------------------------------------------------------------------------
# Fixtures (mirrors test_runs_api.py)
# ---------------------------------------------------------------------------

_FAKE_TEMPLATES = {
    "disk-check": {
        "name": "Disk Check",
        "description": "Check disk on a host",
        "agent_profile_id": "default",
        "goal_template": "Check disk on {host}. Alert above {threshold}%.",
        "params": {
            "host": {"description": "Hostname", "required": True},
            "threshold": {"description": "Threshold", "required": False, "default": "80"},
        },
    },
    "no-params": {
        "name": "No Params",
        "description": "Always works",
        "agent_profile_id": "default",
        "goal_template": "Run a health check.",
        "params": {},
    },
}


@pytest.fixture(scope="module")
def client():
    import app.core.persistence as persistence_module
    import app.core.run_store as run_store_module
    import app.db.database as db_module

    new_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    new_session = sessionmaker(autocommit=False, autoflush=False, bind=new_engine)
    db_module.engine = new_engine
    db_module.SessionLocal = new_session
    run_store_module.SessionLocal = new_session
    persistence_module.SessionLocal = new_session
    init_db()

    # Inject a mock service container so the template route can call get_llm_manager()
    mock_container = MagicMock()
    mock_container.get_llm_manager.return_value = MagicMock()
    app.state.container = mock_container

    return TestClient(app)


@pytest.fixture(scope="module")
def api_key_disabled():
    orig_require = settings.require_api_key
    orig_key = settings.api_key
    settings.require_api_key = False
    settings.api_key = ""
    yield
    settings.require_api_key = orig_require
    settings.api_key = orig_key


@pytest.fixture(autouse=True, scope="module")
def patch_templates():
    """Use fake templates so tests are independent of config/run_templates.yaml."""
    with patch("app.core.run_templates._load_yaml", return_value={"run_templates": _FAKE_TEMPLATES}):
        yield


# ---------------------------------------------------------------------------
# GET /api/v1/run/templates
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestListTemplatesRoute:
    def test_returns_200(self, client, api_key_disabled):
        response = client.get("/api/v1/run/templates")
        assert response.status_code == 200

    def test_returns_templates_list(self, client, api_key_disabled):
        response = client.get("/api/v1/run/templates")
        data = response.json()
        assert "templates" in data
        ids = [t["id"] for t in data["templates"]]
        assert "disk-check" in ids
        assert "no-params" in ids

    def test_template_has_params_schema(self, client, api_key_disabled):
        response = client.get("/api/v1/run/templates")
        templates = {t["id"]: t for t in response.json()["templates"]}
        disk = templates["disk-check"]
        assert "host" in disk["params"]
        assert disk["params"]["host"]["required"] is True
        assert disk["params"]["threshold"]["required"] is False

    def test_requires_auth_when_enabled(self, client):
        orig = settings.require_api_key
        settings.require_api_key = True
        settings.api_key = "secret"
        try:
            response = client.get("/api/v1/run/templates")
            assert response.status_code in (401, 403, 503)
        finally:
            settings.require_api_key = orig
            settings.api_key = ""


# ---------------------------------------------------------------------------
# POST /api/v1/run/template/{template_name}
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStartRunFromTemplateRoute:
    def test_returns_201_with_run_id(self, client, api_key_disabled):
        with patch("app.api.v1.routes.runs._tracked_planner", new_callable=AsyncMock), \
             patch("app.api.v1.routes.runs.asyncio.create_task"), \
             patch("app.api.v1.routes.runs.enqueue_run", new_callable=AsyncMock, return_value=False):
            response = client.post(
                "/api/v1/run/template/disk-check",
                json={"params": {"host": "prod-01"}},
            )
        assert response.status_code == 201
        data = response.json()
        assert "run_id" in data
        assert "disk-check" in data.get("message", "")

    def test_goal_rendered_with_params(self, client, api_key_disabled):
        """The rendered goal should contain the supplied param value."""
        with patch("app.api.v1.routes.runs._tracked_planner", new_callable=AsyncMock), \
             patch("app.api.v1.routes.runs.asyncio.create_task"), \
             patch("app.api.v1.routes.runs.enqueue_run", new_callable=AsyncMock, return_value=False):
            response = client.post(
                "/api/v1/run/template/disk-check",
                json={"params": {"host": "my-server"}},
            )
        assert response.status_code == 201
        run_id = response.json()["run_id"]
        # Poll GET /runs/{run_id} to verify goal was rendered
        run_resp = client.get(f"/api/v1/runs/{run_id}")
        assert run_resp.status_code == 200
        assert "my-server" in run_resp.json().get("goal", "")

    def test_default_param_applied_when_omitted(self, client, api_key_disabled):
        with patch("app.api.v1.routes.runs._tracked_planner", new_callable=AsyncMock), \
             patch("app.api.v1.routes.runs.asyncio.create_task"), \
             patch("app.api.v1.routes.runs.enqueue_run", new_callable=AsyncMock, return_value=False):
            response = client.post(
                "/api/v1/run/template/disk-check",
                json={"params": {"host": "h"}},  # threshold omitted → default "80"
            )
        run_id = response.json()["run_id"]
        run_resp = client.get(f"/api/v1/runs/{run_id}")
        assert "80%" in run_resp.json().get("goal", "")

    def test_missing_required_param_returns_422(self, client, api_key_disabled):
        response = client.post(
            "/api/v1/run/template/disk-check",
            json={"params": {}},  # host is required but missing
        )
        assert response.status_code == 422

    def test_unknown_template_returns_404(self, client, api_key_disabled):
        response = client.post(
            "/api/v1/run/template/nonexistent",
            json={"params": {}},
        )
        assert response.status_code == 404
        assert "nonexistent" in response.json()["detail"]

    def test_no_params_template_works_with_empty_body(self, client, api_key_disabled):
        with patch("app.api.v1.routes.runs._tracked_planner", new_callable=AsyncMock), \
             patch("app.api.v1.routes.runs.asyncio.create_task"), \
             patch("app.api.v1.routes.runs.enqueue_run", new_callable=AsyncMock, return_value=False):
            response = client.post(
                "/api/v1/run/template/no-params",
                json={},
            )
        assert response.status_code == 201

    def test_goal_length_exceeding_15000_rejected(self, client, api_key_disabled):
        """Templates whose rendered goal exceeds 15k chars (validate_goal limit) are rejected."""
        huge_templates = {
            "huge": {
                "name": "Huge",
                "description": "d",
                "agent_profile_id": "default",
                "goal_template": "{data}",
                "params": {"data": {"required": True, "description": "d"}},
            }
        }
        with patch("app.core.run_templates._load_yaml", return_value={"run_templates": huge_templates}):
            response = client.post(
                "/api/v1/run/template/huge",
                json={"params": {"data": "x" * 15_001}},
            )
        # validate_goal raises ValidationError → 400 from the exception handler
        assert response.status_code in (400, 422)
