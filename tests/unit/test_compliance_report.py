"""Unit tests for the compliance evidence report endpoint.

Tests:
- GET /api/v1/admin/compliance/report returns 200 for admin key
- Response has all required top-level sections
- Admin-only: non-admin returns 403
- Unauthenticated: returns 401/403
- ?format=csv returns text/csv with Content-Disposition attachment
- CSV has correct column headers
- Period filter (since/until) is accepted
- api_keys section is a list
- llm_cost section has total_usd and by_provider
- runs section has total and by_status
"""


import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import init_db

# ---------------------------------------------------------------------------
# In-memory DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def use_in_memory_db():
    import app.api.v1.routes.compliance as compliance_module
    import app.core.run_store as run_store_module
    import app.db.database as db_module

    original_engine = db_module.engine
    original_session = db_module.SessionLocal
    original_rs_session = run_store_module.SessionLocal
    original_compliance_session = compliance_module.SessionLocal

    new_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    new_session = sessionmaker(autocommit=False, autoflush=False, bind=new_engine)

    db_module.engine = new_engine
    db_module.SessionLocal = new_session
    run_store_module.SessionLocal = new_session
    compliance_module.SessionLocal = new_session
    init_db()

    yield new_session

    db_module.engine = original_engine
    db_module.SessionLocal = original_session
    run_store_module.SessionLocal = original_rs_session
    compliance_module.SessionLocal = original_compliance_session


# ---------------------------------------------------------------------------
# Client and admin auth helpers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def admin_key(use_in_memory_db):
    from app.core.api_keys import create_api_key
    db = use_in_memory_db()
    try:
        _, raw_key, _ = create_api_key(db, name="compliance-admin", role="admin")
        return raw_key
    finally:
        db.close()


@pytest.fixture(scope="module")
def operator_key(use_in_memory_db):
    from app.core.api_keys import create_api_key
    db = use_in_memory_db()
    try:
        _, raw_key, _ = create_api_key(db, name="compliance-operator", role="operator")
        return raw_key
    finally:
        db.close()


@pytest.fixture(scope="module")
def client():
    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.mark.unit
class TestComplianceReportJson:
    def test_admin_gets_200(self, client, admin_key):
        resp = client.get(
            "/api/v1/admin/compliance/report",
            headers={"X-API-Key": admin_key},
        )
        assert resp.status_code == 200

    def test_response_has_required_sections(self, client, admin_key):
        resp = client.get(
            "/api/v1/admin/compliance/report",
            headers={"X-API-Key": admin_key},
        )
        data = resp.json()
        for section in ("generated_at", "period", "requests", "api_keys", "runs", "llm_cost"):
            assert section in data, f"Missing section: {section}"

    def test_requests_section_structure(self, client, admin_key):
        resp = client.get(
            "/api/v1/admin/compliance/report",
            headers={"X-API-Key": admin_key},
        )
        req = resp.json()["requests"]
        assert "total" in req
        assert "by_method" in req
        assert "by_status_class" in req
        assert "auth_failures" in req
        assert "top_paths" in req

    def test_llm_cost_section_structure(self, client, admin_key):
        resp = client.get(
            "/api/v1/admin/compliance/report",
            headers={"X-API-Key": admin_key},
        )
        llm = resp.json()["llm_cost"]
        assert "total_usd" in llm
        assert "by_provider" in llm

    def test_runs_section_structure(self, client, admin_key):
        resp = client.get(
            "/api/v1/admin/compliance/report",
            headers={"X-API-Key": admin_key},
        )
        runs = resp.json()["runs"]
        assert "total" in runs
        assert "by_status" in runs

    def test_api_keys_is_list(self, client, admin_key):
        resp = client.get(
            "/api/v1/admin/compliance/report",
            headers={"X-API-Key": admin_key},
        )
        assert isinstance(resp.json()["api_keys"], list)

    def test_period_has_since_and_until(self, client, admin_key):
        resp = client.get(
            "/api/v1/admin/compliance/report",
            headers={"X-API-Key": admin_key},
        )
        period = resp.json()["period"]
        assert "since" in period
        assert "until" in period

    def test_date_filter_accepted(self, client, admin_key):
        resp = client.get(
            "/api/v1/admin/compliance/report",
            params={"since": "2026-01-01T00:00:00Z", "until": "2026-03-01T00:00:00Z"},
            headers={"X-API-Key": admin_key},
        )
        assert resp.status_code == 200


@pytest.mark.unit
class TestComplianceReportAccessControl:
    def test_operator_gets_403(self, client, operator_key):
        resp = client.get(
            "/api/v1/admin/compliance/report",
            headers={"X-API-Key": operator_key},
        )
        assert resp.status_code == 403

    def test_unauthenticated_gets_401_or_403(self, client):
        resp = client.get("/api/v1/admin/compliance/report")
        assert resp.status_code in (401, 403, 503)


@pytest.fixture(scope="module")
def csv_admin_key(use_in_memory_db):
    """Separate admin key for CSV tests to avoid rate limit from other test classes."""
    from app.core.api_keys import create_api_key
    db = use_in_memory_db()
    try:
        _, raw_key, _ = create_api_key(db, name="compliance-csv-admin", role="admin")
        return raw_key
    finally:
        db.close()


@pytest.mark.unit
class TestComplianceReportCsv:
    def test_csv_content_type(self, client, csv_admin_key):
        resp = client.get(
            "/api/v1/admin/compliance/report",
            params={"format": "csv"},
            headers={"X-API-Key": csv_admin_key},
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")

    def test_csv_content_disposition_attachment(self, client, csv_admin_key):
        resp = client.get(
            "/api/v1/admin/compliance/report",
            params={"format": "csv"},
            headers={"X-API-Key": csv_admin_key},
        )
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert "compliance_report.csv" in cd

    def test_csv_has_headers(self, client, csv_admin_key):
        resp = client.get(
            "/api/v1/admin/compliance/report",
            params={"format": "csv"},
            headers={"X-API-Key": csv_admin_key},
        )
        lines = resp.text.strip().splitlines()
        assert len(lines) >= 1  # at least header row
        header = lines[0]
        assert "api_key_id" in header
        assert "monthly_llm_spend_usd" in header
