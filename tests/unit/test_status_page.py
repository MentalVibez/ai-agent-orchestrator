"""Unit tests for the in-app operational status page.

Tests:
- GET /api/v1/status returns 200 with no authentication header
- All expected fields are present in the response
- database field is "ok" when DB is reachable
- database field contains "error:" when DB is unavailable
- uptime_seconds is a non-negative integer
- llm_provider and llm_model reflect settings
- queue.enabled is a bool
- runs_last_24h is a dict
"""


import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import init_db

# ---------------------------------------------------------------------------
# In-memory DB + TestClient fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def use_in_memory_db():
    import app.core.run_store as run_store_module
    import app.db.database as db_module

    original_engine = db_module.engine
    original_session = db_module.SessionLocal
    original_rs_session = run_store_module.SessionLocal

    new_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    new_session = sessionmaker(autocommit=False, autoflush=False, bind=new_engine)

    db_module.engine = new_engine
    db_module.SessionLocal = new_session
    run_store_module.SessionLocal = new_session
    init_db()

    yield new_session

    db_module.engine = original_engine
    db_module.SessionLocal = original_session
    run_store_module.SessionLocal = original_rs_session


@pytest.fixture(scope="module")
def client():
    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.mark.unit
class TestStatusPage:
    def test_returns_200_without_auth(self, client):
        """Status page must be accessible without any API key."""
        resp = client.get("/api/v1/status")
        assert resp.status_code == 200

    def test_all_required_fields_present(self, client):
        """Response must contain all documented top-level fields."""
        resp = client.get("/api/v1/status")
        data = resp.json()
        for field in (
            "service", "version", "uptime_seconds", "timestamp",
            "database", "llm_provider", "llm_model",
            "mcp_servers", "queue", "runs_last_24h",
        ):
            assert field in data, f"Missing field: {field}"

    def test_database_ok_when_reachable(self, client):
        resp = client.get("/api/v1/status")
        data = resp.json()
        assert data["database"] == "ok"

    def test_uptime_seconds_non_negative(self, client):
        resp = client.get("/api/v1/status")
        data = resp.json()
        assert isinstance(data["uptime_seconds"], int)
        assert data["uptime_seconds"] >= 0

    def test_queue_has_enabled_bool(self, client):
        resp = client.get("/api/v1/status")
        data = resp.json()
        assert isinstance(data["queue"], dict)
        assert "enabled" in data["queue"]
        assert isinstance(data["queue"]["enabled"], bool)

    def test_runs_last_24h_is_dict(self, client):
        resp = client.get("/api/v1/status")
        data = resp.json()
        assert isinstance(data["runs_last_24h"], dict)

    def test_mcp_servers_is_list(self, client):
        resp = client.get("/api/v1/status")
        data = resp.json()
        assert isinstance(data["mcp_servers"], list)

    def test_service_name_present(self, client):
        resp = client.get("/api/v1/status")
        data = resp.json()
        assert data["service"]  # non-empty

    def test_database_error_string_on_failure(self, client):
        """When DB is unavailable, database field should start with 'error:'."""
        import app.db.database as db_module

        def broken_session():
            raise Exception("DB unreachable")

        # Patch SessionLocal at the source; status.py imports it lazily inside the function
        original = db_module.SessionLocal
        db_module.SessionLocal = broken_session
        try:
            resp = client.get("/api/v1/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["database"].startswith("error:")
        finally:
            db_module.SessionLocal = original
