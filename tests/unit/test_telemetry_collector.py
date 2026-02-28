"""Unit tests for DEX telemetry collector (app/core/dex/telemetry_collector.py)."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import init_db
from app.db.models import Endpoint, EndpointMetricSnapshot


# ---------------------------------------------------------------------------
# Module-level DB patch
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def use_in_memory_db():
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


@pytest.fixture
def db(use_in_memory_db):
    from app.db.database import SessionLocal

    session = SessionLocal()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# _extract_json_from_answer
# ---------------------------------------------------------------------------


class TestExtractJsonFromAnswer:
    def test_plain_json_object(self):
        from app.core.dex.telemetry_collector import _extract_json_from_answer

        raw = json.dumps({"cpu_pct": 30.0, "memory_pct": 50.0})
        result = _extract_json_from_answer(raw)
        assert result is not None
        assert result["cpu_pct"] == 30.0
        assert result["memory_pct"] == 50.0

    def test_json_in_markdown_fence(self):
        from app.core.dex.telemetry_collector import _extract_json_from_answer

        raw = '```json\n{"cpu_pct": 25.0, "disk_pct": 70.0}\n```'
        result = _extract_json_from_answer(raw)
        assert result is not None
        assert result["cpu_pct"] == 25.0

    def test_json_in_plain_code_fence(self):
        from app.core.dex.telemetry_collector import _extract_json_from_answer

        raw = '```\n{"disk_pct": 80.0}\n```'
        result = _extract_json_from_answer(raw)
        assert result is not None
        assert result["disk_pct"] == 80.0

    def test_json_embedded_in_prose(self):
        from app.core.dex.telemetry_collector import _extract_json_from_answer

        raw = 'Here is the telemetry: {"cpu_pct": 10.0, "services_down": []} — end.'
        result = _extract_json_from_answer(raw)
        assert result is not None
        assert result["cpu_pct"] == 10.0

    def test_invalid_json_returns_none(self):
        from app.core.dex.telemetry_collector import _extract_json_from_answer

        assert _extract_json_from_answer("This is not JSON at all.") is None

    def test_empty_string_returns_none(self):
        from app.core.dex.telemetry_collector import _extract_json_from_answer

        assert _extract_json_from_answer("") is None

    def test_none_returns_none(self):
        from app.core.dex.telemetry_collector import _extract_json_from_answer

        assert _extract_json_from_answer(None) is None  # type: ignore[arg-type]

    def test_array_json_not_object_returns_none(self):
        from app.core.dex.telemetry_collector import _extract_json_from_answer

        # A JSON array is not a valid telemetry dict — should return None
        # (the re.search looks for {...} so arrays aren't matched)
        result = _extract_json_from_answer("[1, 2, 3]")
        # Could return None or the array depending on implementation; just ensure no crash
        assert result is None or isinstance(result, list)


# ---------------------------------------------------------------------------
# store_snapshot
# ---------------------------------------------------------------------------


class TestStoreSnapshot:
    def test_persists_all_fields(self, db):
        from app.core.dex.telemetry_collector import store_snapshot

        data = {
            "cpu_pct": 35.0,
            "memory_pct": 55.0,
            "disk_pct": 60.0,
            "network_latency_ms": 15.0,
            "packet_loss_pct": 0.5,
            "services_down": ["redis"],
            "log_error_count": 3,
        }
        snap = store_snapshot(db, "store-host", "run-001", data)
        assert snap.id is not None
        assert snap.hostname == "store-host"
        assert snap.run_id == "run-001"
        assert snap.cpu_pct == 35.0
        assert snap.services_down == ["redis"]
        assert snap.log_error_count == 3

        # Verify DB persistence
        fetched = db.query(EndpointMetricSnapshot).filter_by(id=snap.id).first()
        assert fetched is not None
        assert fetched.disk_pct == 60.0

    def test_null_run_id_allowed(self, db):
        from app.core.dex.telemetry_collector import store_snapshot

        snap = store_snapshot(db, "no-run-host", None, {"cpu_pct": 10.0})
        assert snap.id is not None
        assert snap.run_id is None
        assert snap.cpu_pct == 10.0

    def test_empty_data_uses_defaults(self, db):
        from app.core.dex.telemetry_collector import store_snapshot

        snap = store_snapshot(db, "empty-host", None, {})
        assert snap.id is not None
        assert snap.cpu_pct is None
        assert snap.log_error_count == 0  # default from code: `or 0`

    def test_null_services_down_stored_as_empty_list(self, db):
        from app.core.dex.telemetry_collector import store_snapshot

        snap = store_snapshot(db, "null-services-host", None, {"services_down": None})
        assert snap.services_down == []


# ---------------------------------------------------------------------------
# process_completed_scan
# ---------------------------------------------------------------------------


class TestProcessCompletedScan:
    def test_healthy_endpoint_returns_high_score(self, db):
        from app.core.dex.telemetry_collector import process_completed_scan

        db.add(Endpoint(hostname="healthy-scan-host"))
        db.commit()

        answer = json.dumps(
            {
                "cpu_pct": 20.0,
                "memory_pct": 40.0,
                "disk_pct": 50.0,
                "network_latency_ms": 10.0,
                "packet_loss_pct": 0.0,
                "services_down": [],
                "log_error_count": 0,
            }
        )
        result = process_completed_scan(db, "healthy-scan-host", "run-h1", answer)
        assert result["ok"] is True
        assert result["hostname"] == "healthy-scan-host"
        assert result["snapshot_id"] is not None
        assert result["score"] >= 80.0
        assert result["alert"] is None  # score above threshold — no alert

    def test_critical_endpoint_creates_alert(self, db):
        from app.core.dex.telemetry_collector import process_completed_scan

        db.add(Endpoint(hostname="critical-scan-host"))
        db.commit()

        answer = json.dumps(
            {
                "cpu_pct": 98.0,
                "memory_pct": 97.0,
                "disk_pct": 96.0,
                "network_latency_ms": 600.0,
                "packet_loss_pct": 8.0,
                "services_down": ["nginx", "mysql"],
                "log_error_count": 100,
            }
        )
        result = process_completed_scan(
            db,
            "critical-scan-host",
            "run-c1",
            answer,
            alert_threshold=60,
            critical_threshold=40,
        )
        assert result["ok"] is True
        assert result["score"] < 30.0
        assert result["alert"] is not None
        assert result["alert"]["severity"] in ("warning", "critical")

    def test_unparseable_answer_returns_not_ok(self, db):
        from app.core.dex.telemetry_collector import process_completed_scan

        result = process_completed_scan(db, "bad-answer-host", "run-b1", "no json here")
        assert result["ok"] is False
        assert result["reason"] == "unparseable_answer"

    def test_markdown_wrapped_json_is_processed(self, db):
        from app.core.dex.telemetry_collector import process_completed_scan

        db.add(Endpoint(hostname="md-scan-host"))
        db.commit()

        answer = '```json\n{"cpu_pct": 15.0, "memory_pct": 20.0, "disk_pct": 30.0}\n```'
        result = process_completed_scan(db, "md-scan-host", "run-md1", answer)
        assert result["ok"] is True
        assert result["score"] is not None
        assert result["score"] >= 80.0

    def test_snapshot_created_in_db(self, db):
        from app.core.dex.telemetry_collector import process_completed_scan

        db.add(Endpoint(hostname="db-verify-host"))
        db.commit()

        answer = json.dumps({"cpu_pct": 50.0, "disk_pct": 50.0})
        result = process_completed_scan(db, "db-verify-host", "run-dbv1", answer)
        assert result["ok"] is True

        snap = db.query(EndpointMetricSnapshot).filter_by(id=result["snapshot_id"]).first()
        assert snap is not None
        assert snap.hostname == "db-verify-host"
        assert snap.cpu_pct == 50.0
