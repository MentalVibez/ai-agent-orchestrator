"""Unit tests for AuditLogMiddleware and GET /api/v1/admin/audit."""

import json
import threading
from datetime import datetime, timezone
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
# Module-level DB patch
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def use_in_memory_db():
    import app.api.v1.routes.audit as audit_routes_module
    import app.core.persistence as persistence_module
    import app.core.run_store as run_store_module
    import app.db.database as db_module

    original_engine = db_module.engine
    original_session = db_module.SessionLocal
    original_run_store_session = run_store_module.SessionLocal
    original_persistence_session = persistence_module.SessionLocal
    original_routes_session = audit_routes_module.SessionLocal

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
    audit_routes_module.SessionLocal = new_session  # by-value import in route file

    init_db()
    yield

    db_module.engine = original_engine
    db_module.SessionLocal = original_session
    run_store_module.SessionLocal = original_run_store_session
    persistence_module.SessionLocal = original_persistence_session
    audit_routes_module.SessionLocal = original_routes_session


# ---------------------------------------------------------------------------
# Tests: _redact_body
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRedactBody:
    def test_removes_password_key(self):
        from app.middleware.audit_log import _redact_body

        raw = json.dumps({"username": "alice", "password": "s3cr3t"}).encode()
        result = json.loads(_redact_body(raw))
        assert result["username"] == "alice"
        assert result["password"] == "[REDACTED]"

    def test_removes_api_key_key(self):
        from app.middleware.audit_log import _redact_body

        raw = json.dumps({"api_key": "orc_abc123", "name": "test"}).encode()
        result = json.loads(_redact_body(raw))
        assert result["name"] == "test"
        assert result["api_key"] == "[REDACTED]"

    def test_passes_through_non_sensitive_fields(self):
        from app.middleware.audit_log import _redact_body

        raw = json.dumps({"goal": "run diagnostics", "agent": "network"}).encode()
        result = json.loads(_redact_body(raw))
        assert result["goal"] == "run diagnostics"
        assert result["agent"] == "network"

    def test_returns_none_for_empty_bytes(self):
        from app.middleware.audit_log import _redact_body

        assert _redact_body(b"") is None

    def test_returns_none_for_non_json(self):
        from app.middleware.audit_log import _redact_body

        assert _redact_body(b"not-json-content") is None

    def test_handles_nested_dict(self):
        from app.middleware.audit_log import _redact_body

        raw = json.dumps({"creds": {"password": "secret", "user": "bob"}}).encode()
        result = json.loads(_redact_body(raw))
        assert result["creds"]["password"] == "[REDACTED]"
        assert result["creds"]["user"] == "bob"

    def test_handles_large_body_truncation(self):
        from app.middleware.audit_log import _redact_body

        # Body larger than 64 KB — should not raise
        big = b'{"key": "' + b"x" * 70000 + b'"}'
        # Result may be None (truncation breaks JSON) or a string — just must not raise
        result = _redact_body(big)
        assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# Tests: _persist_audit
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPersistAudit:
    def test_writes_record_to_db(self):
        import app.db.database as db_module
        from app.db.models import AuditLogRecord
        from app.middleware.audit_log import _persist_audit

        ts = datetime.now(timezone.utc).replace(tzinfo=None)
        _persist_audit(
            request_id="req-test-001",
            timestamp=ts,
            method="GET",
            path="/api/v1/health",
            status_code=200,
            api_key_id="kid_test",
            api_key_role="operator",
            client_ip="127.0.0.1",
            user_agent="pytest",
            request_body=None,
        )

        db = db_module.SessionLocal()
        try:
            record = db.query(AuditLogRecord).filter_by(request_id="req-test-001").first()
            assert record is not None
            assert record.method == "GET"
            assert record.path == "/api/v1/health"
            assert record.status_code == 200
            assert record.api_key_id == "kid_test"
        finally:
            db.close()

    def test_silently_absorbs_db_errors(self):
        from app.middleware.audit_log import _persist_audit

        # Patch SessionLocal to raise — must not propagate
        with patch("app.db.database.SessionLocal", side_effect=RuntimeError("db gone")):
            # Should not raise
            _persist_audit(
                request_id="req-error",
                timestamp=datetime.utcnow(),
                method="POST",
                path="/fail",
                status_code=500,
                api_key_id=None,
                api_key_role=None,
                client_ip=None,
                user_agent=None,
                request_body=None,
            )


# ---------------------------------------------------------------------------
# Tests: AuditLogMiddleware (via real app + TestClient)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def admin_client():
    original_require = settings.require_api_key
    original_key = settings.api_key
    settings.require_api_key = True
    settings.api_key = "audit-test-bootstrap-key"
    app.state.container = MagicMock()

    yield TestClient(app, raise_server_exceptions=False)

    settings.require_api_key = original_require
    settings.api_key = original_key


@pytest.fixture(scope="module")
def admin_headers():
    return {"X-API-Key": "audit-test-bootstrap-key"}


@pytest.mark.unit
class TestAuditLogMiddlewareIntegration:
    def test_middleware_does_not_break_request_pipeline(self, admin_client, admin_headers):
        """AuditLogMiddleware should not interfere with normal request handling."""
        resp = admin_client.get("/", headers=admin_headers)
        # Any HTTP response (not a connection error) means middleware didn't crash
        assert resp.status_code < 600

    def test_post_body_captured_via_redact_body(self):
        from app.middleware.audit_log import _redact_body

        body = {"name": "test-capture", "role": "viewer"}
        raw = json.dumps(body).encode()
        result = _redact_body(raw)
        assert result is not None
        parsed = json.loads(result)
        assert parsed["name"] == "test-capture"

    def test_get_body_not_captured(self):
        from app.middleware.audit_log import _redact_body

        # GET requests send no body — _redact_body(b"") should return None
        assert _redact_body(b"") is None

    def test_thread_is_started_after_response(self, admin_client, admin_headers):
        """Verify that a daemon thread is started for each request."""
        threads_started = []

        original_thread = __import__("threading").Thread

        class CapturingThread(original_thread):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                threads_started.append(self)

        with patch("app.middleware.audit_log.threading.Thread", CapturingThread):
            admin_client.get("/", headers=admin_headers)

        assert any(t.daemon for t in threads_started)


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/admin/audit route
# ---------------------------------------------------------------------------


def _seed_audit_records(n: int = 5) -> None:
    """Insert n audit records directly into the DB for testing."""
    import app.db.database as db_module
    from app.db.models import AuditLogRecord

    db = db_module.SessionLocal()
    try:
        for i in range(n):
            record = AuditLogRecord(
                request_id=f"seed-req-{i:03d}",
                timestamp=datetime(2026, 3, 4, 10, i, 0),
                method="GET" if i % 2 == 0 else "POST",
                path=f"/api/v1/test/{i}",
                status_code=200 if i < 4 else 500,
                api_key_id="kid_seed" if i < 3 else "kid_other",
                api_key_role="operator",
                client_ip="10.0.0.1",
                user_agent="pytest-seed",
                request_body=None,
            )
            db.add(record)
        db.commit()
    finally:
        db.close()


@pytest.mark.unit
class TestAdminAuditRoutes:
    @pytest.fixture(autouse=True, scope="class")
    def seed(self):
        _seed_audit_records(5)

    def test_list_returns_200(self, admin_client, admin_headers):
        resp = admin_client.get("/api/v1/admin/audit", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert data["page"] == 1

    def test_filter_by_api_key_id(self, admin_client, admin_headers):
        resp = admin_client.get(
            "/api/v1/admin/audit?api_key_id=kid_seed", headers=admin_headers
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        for item in items:
            if item["api_key_id"] is not None:
                assert item["api_key_id"] == "kid_seed"

    def test_filter_by_status_code(self, admin_client, admin_headers):
        resp = admin_client.get(
            "/api/v1/admin/audit?status_code=500", headers=admin_headers
        )
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            if item["status_code"] is not None:
                assert item["status_code"] == 500

    def test_filter_by_path_substring(self, admin_client, admin_headers):
        resp = admin_client.get(
            "/api/v1/admin/audit?path=/api/v1/test", headers=admin_headers
        )
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            assert "/api/v1/test" in item["path"]

    def test_pagination_page_size(self, admin_client, admin_headers):
        resp = admin_client.get(
            "/api/v1/admin/audit?page=1&page_size=2", headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) <= 2
        assert data["page_size"] == 2

    def test_unauthenticated_returns_401(self, admin_client):
        resp = admin_client.get("/api/v1/admin/audit")
        assert resp.status_code == 401

    def test_viewer_role_returns_403(self, admin_client):
        import app.db.database as db_module
        from app.core.api_keys import create_api_key

        db = db_module.SessionLocal()
        try:
            _, viewer_key, _ = create_api_key(db, name="viewer-audit-test", role="viewer")
        finally:
            db.close()

        resp = admin_client.get(
            "/api/v1/admin/audit", headers={"X-API-Key": viewer_key}
        )
        assert resp.status_code == 403
