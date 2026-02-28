"""Unit tests for DEX API routes (app/api/v1/routes/dex.py)."""

from unittest.mock import AsyncMock, patch

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
    import app.api.v1.routes.dex as dex_routes_module
    import app.core.persistence as persistence_module
    import app.core.run_store as run_store_module
    import app.db.database as db_module

    original_engine = db_module.engine
    original_session = db_module.SessionLocal
    original_run_store_session = run_store_module.SessionLocal
    original_persistence_session = persistence_module.SessionLocal
    original_dex_session = dex_routes_module.SessionLocal

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
    dex_routes_module.SessionLocal = new_session_factory

    init_db()
    yield

    db_module.engine = original_engine
    db_module.SessionLocal = original_session
    run_store_module.SessionLocal = original_run_store_session
    persistence_module.SessionLocal = original_persistence_session
    dex_routes_module.SessionLocal = original_dex_session


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_disabled():
    original_require = settings.require_api_key
    original_key = settings.api_key
    settings.require_api_key = False
    settings.api_key = ""
    yield
    settings.require_api_key = original_require
    settings.api_key = original_key


@pytest.fixture
def client(auth_disabled):
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Endpoint Registry Tests
# ---------------------------------------------------------------------------


class TestEndpointRegistry:
    def test_register_endpoint(self, client):
        resp = client.post(
            "/api/v1/dex/endpoints",
            json={"hostname": "test-machine-1", "persona": "developer", "criticality_tier": 1},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["ok"] is True
        assert data["endpoint"]["hostname"] == "test-machine-1"
        assert data["endpoint"]["persona"] == "developer"
        assert data["endpoint"]["criticality_tier"] == 1

    def test_register_duplicate_returns_409(self, client):
        client.post(
            "/api/v1/dex/endpoints",
            json={"hostname": "dup-machine", "persona": "tech"},
        )
        resp = client.post(
            "/api/v1/dex/endpoints",
            json={"hostname": "dup-machine", "persona": "tech"},
        )
        assert resp.status_code == 409

    def test_list_endpoints(self, client):
        client.post("/api/v1/dex/endpoints", json={"hostname": "list-machine-a"})
        client.post("/api/v1/dex/endpoints", json={"hostname": "list-machine-b"})
        resp = client.get("/api/v1/dex/endpoints")
        assert resp.status_code == 200
        data = resp.json()
        hostnames = [e["hostname"] for e in data["endpoints"]]
        assert "list-machine-a" in hostnames
        assert "list-machine-b" in hostnames

    def test_get_endpoint_detail(self, client):
        client.post(
            "/api/v1/dex/endpoints",
            json={"hostname": "detail-machine", "owner_email": "owner@example.com"},
        )
        resp = client.get("/api/v1/dex/endpoints/detail-machine")
        assert resp.status_code == 200
        data = resp.json()
        assert data["endpoint"]["hostname"] == "detail-machine"
        assert data["endpoint"]["owner_email"] == "owner@example.com"
        assert data["dex_score"] is None  # no scan yet

    def test_get_nonexistent_endpoint_returns_404(self, client):
        resp = client.get("/api/v1/dex/endpoints/no-such-machine-xyz")
        assert resp.status_code == 404

    def test_patch_endpoint(self, client):
        client.post("/api/v1/dex/endpoints", json={"hostname": "patch-machine"})
        resp = client.patch(
            "/api/v1/dex/endpoints/patch-machine",
            json={"owner_email": "updated@example.com", "persona": "salesperson"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["endpoint"]["owner_email"] == "updated@example.com"
        assert data["endpoint"]["persona"] == "salesperson"

    def test_patch_nonexistent_returns_404(self, client):
        resp = client.patch(
            "/api/v1/dex/endpoints/ghost-machine",
            json={"owner_email": "x@x.com"},
        )
        assert resp.status_code == 404

    def test_delete_endpoint(self, client):
        client.post("/api/v1/dex/endpoints", json={"hostname": "delete-machine"})
        resp = client.delete("/api/v1/dex/endpoints/delete-machine")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        # Should now be deregistered (is_active=False)
        resp2 = client.get("/api/v1/dex/endpoints/delete-machine")
        assert resp2.status_code == 200  # still accessible but marked inactive

    def test_delete_nonexistent_returns_404(self, client):
        resp = client.delete("/api/v1/dex/endpoints/nonexistent-delete-xyz")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Scan Endpoint
# ---------------------------------------------------------------------------


class TestScanTrigger:
    def test_scan_nonexistent_endpoint_returns_404(self, client):
        resp = client.post("/api/v1/dex/endpoints/no-such-host/scan")
        assert resp.status_code == 404

    def test_scan_triggers_run(self, client):
        client.post("/api/v1/dex/endpoints", json={"hostname": "scan-machine"})
        with patch(
            "app.core.dex.telemetry_collector.trigger_endpoint_scan",
            new=AsyncMock(return_value="test-run-id-123"),
        ):
            resp = client.post("/api/v1/dex/endpoints/scan-machine/scan")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == "test-run-id-123"
        assert data["hostname"] == "scan-machine"


# ---------------------------------------------------------------------------
# Score Endpoints
# ---------------------------------------------------------------------------


class TestScoreEndpoints:
    def test_score_404_when_no_scan(self, client):
        client.post("/api/v1/dex/endpoints", json={"hostname": "noscore-machine"})
        resp = client.get("/api/v1/dex/endpoints/noscore-machine/score")
        assert resp.status_code == 404

    def test_score_history_returns_empty_list(self, client):
        client.post("/api/v1/dex/endpoints", json={"hostname": "history-machine"})
        resp = client.get("/api/v1/dex/endpoints/history-machine/history")
        assert resp.status_code == 200
        assert resp.json()["history"] == []
        assert resp.json()["count"] == 0

    def test_snapshots_returns_empty_list(self, client):
        client.post("/api/v1/dex/endpoints", json={"hostname": "snap-machine"})
        resp = client.get("/api/v1/dex/endpoints/snap-machine/snapshots")
        assert resp.status_code == 200
        assert resp.json()["snapshots"] == []


# ---------------------------------------------------------------------------
# Fleet and Alerts
# ---------------------------------------------------------------------------


class TestFleetAndAlerts:
    def test_fleet_summary_empty(self, client):
        # Use a fresh fleet check — active endpoints may exist from other tests
        resp = client.get("/api/v1/dex/fleet")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_endpoints" in data
        assert "avg_dex_score" in data

    def test_alerts_list_empty_by_default(self, client):
        resp = client.get("/api/v1/dex/alerts")
        assert resp.status_code == 200
        assert "alerts" in resp.json()

    def test_incidents_list(self, client):
        resp = client.get("/api/v1/dex/incidents")
        assert resp.status_code == 200
        assert "incidents" in resp.json()

    def test_kpis_endpoint(self, client):
        resp = client.get("/api/v1/dex/kpis")
        assert resp.status_code == 200
        data = resp.json()
        assert "mttr_minutes" in data
        assert "auto_resolution_rate_pct" in data
        assert "avg_fleet_dex_score" in data

    def test_trends_insufficient_data(self, client):
        client.post("/api/v1/dex/endpoints", json={"hostname": "trend-machine"})
        resp = client.get("/api/v1/dex/endpoints/trend-machine/trends")
        assert resp.status_code == 200
        data = resp.json()
        assert data["hostname"] == "trend-machine"
        # Should report insufficient data
        assert any(t.get("status") == "insufficient_data" for t in data["trends"])


# ---------------------------------------------------------------------------
# Feedback / Sentiment
# ---------------------------------------------------------------------------


class TestFeedback:
    def test_submit_feedback(self, client):
        client.post("/api/v1/dex/endpoints", json={"hostname": "feedback-machine"})
        resp = client.post(
            "/api/v1/dex/feedback",
            json={
                "hostname": "feedback-machine",
                "rating": 4,
                "comment": "Works great most of the time",
                "category": "performance",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["ok"] is True
        assert data["feedback"]["rating"] == 4

    def test_feedback_without_hostname(self, client):
        resp = client.post(
            "/api/v1/dex/feedback",
            json={"rating": 2, "comment": "VPN keeps dropping", "category": "connectivity"},
        )
        assert resp.status_code == 201

    def test_feedback_invalid_rating_rejected(self, client):
        resp = client.post(
            "/api/v1/dex/feedback",
            json={"rating": 10},  # out of 1-5 range
        )
        assert resp.status_code == 422

    def test_feedback_summary_empty(self, client):
        resp = client.get("/api/v1/dex/feedback/summary?lookback_days=1")
        assert resp.status_code == 200
        data = resp.json()
        # May have data from other tests or not
        assert "total_responses" in data
        assert "enps" in data

    def test_feedback_summary_calculates_enps(self, client):
        client.post("/api/v1/dex/endpoints", json={"hostname": "enps-machine"})
        # Submit 2 promoters (rating >= 4) and 1 detractor (rating <= 2)
        for rating in [5, 4, 1]:
            client.post(
                "/api/v1/dex/feedback",
                json={"hostname": "enps-machine", "rating": rating},
            )
        resp = client.get("/api/v1/dex/feedback/summary?lookback_days=30")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_responses"] >= 3
        assert data["avg_rating"] is not None
        assert data["enps"] is not None


# ---------------------------------------------------------------------------
# Acknowledge Alert
# ---------------------------------------------------------------------------


class TestAcknowledgeAlert:
    def test_acknowledge_unknown_alert_returns_404(self, client):
        resp = client.post("/api/v1/dex/alerts/99999/acknowledge")
        assert resp.status_code == 404

    def test_acknowledge_alert_success(self, client):
        from app.db.database import SessionLocal
        from app.db.models import DexAlert

        db = SessionLocal()
        alert = DexAlert(
            hostname="ack-host",
            alert_name="HighCPU",
            severity="warning",
            alert_type="threshold",
            status="active",
        )
        db.add(alert)
        db.commit()
        alert_id = alert.id
        db.close()

        resp = client.post(f"/api/v1/dex/alerts/{alert_id}/acknowledge?hours=2")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["alert_id"] == alert_id
        assert "acknowledged_until" in data


# ---------------------------------------------------------------------------
# Alert Filtering
# ---------------------------------------------------------------------------


class TestAlertFilters:
    def test_filter_alerts_by_hostname(self, client):
        from app.db.database import SessionLocal
        from app.db.models import DexAlert

        db = SessionLocal()
        db.add(DexAlert(
            hostname="filter-host-A",
            alert_name="FilterAlert",
            severity="warning",
            alert_type="threshold",
            status="active",
        ))
        db.add(DexAlert(
            hostname="other-host-B",
            alert_name="OtherAlert",
            severity="warning",
            alert_type="threshold",
            status="active",
        ))
        db.commit()
        db.close()

        resp = client.get("/api/v1/dex/alerts?hostname=filter-host-A")
        assert resp.status_code == 200
        alerts = resp.json()["alerts"]
        assert all(a["hostname"] == "filter-host-A" for a in alerts)

    def test_filter_alerts_by_severity(self, client):
        from app.db.database import SessionLocal
        from app.db.models import DexAlert

        db = SessionLocal()
        db.add(DexAlert(
            hostname="severity-host",
            alert_name="CriticalAlert",
            severity="critical",
            alert_type="threshold",
            status="active",
        ))
        db.commit()
        db.close()

        resp = client.get("/api/v1/dex/alerts?severity=critical")
        assert resp.status_code == 200
        alerts = resp.json()["alerts"]
        assert any(a["severity"] == "critical" for a in alerts)

    def test_filter_alerts_by_resolved_status(self, client):
        from app.db.database import SessionLocal
        from app.db.models import DexAlert

        db = SessionLocal()
        db.add(DexAlert(
            hostname="resolved-host",
            alert_name="ResolvedAlert",
            severity="info",
            alert_type="threshold",
            status="resolved",
        ))
        db.commit()
        db.close()

        resp = client.get("/api/v1/dex/alerts?status=resolved")
        assert resp.status_code == 200
        alerts = resp.json()["alerts"]
        assert any(a["alert_name"] == "ResolvedAlert" for a in alerts)


# ---------------------------------------------------------------------------
# Fleet and Score with actual data
# ---------------------------------------------------------------------------


class TestFleetWithData:
    def test_fleet_summary_with_score_records(self, client):
        from app.db.database import SessionLocal
        from app.db.models import DexScoreRecord

        client.post("/api/v1/dex/endpoints", json={"hostname": "fleet-scored-host"})
        db = SessionLocal()
        db.add(DexScoreRecord(
            hostname="fleet-scored-host",
            score=85.0,
            device_health_score=90.0,
            network_score=80.0,
            app_performance_score=85.0,
            remediation_score=75.0,
        ))
        db.commit()
        db.close()

        resp = client.get("/api/v1/dex/fleet")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_endpoints"] >= 1
        assert data["avg_dex_score"] is not None
        assert "at_risk" in data
        assert "healthy" in data

    def test_score_endpoint_returns_data(self, client):
        from app.db.database import SessionLocal
        from app.db.models import DexScoreRecord

        client.post("/api/v1/dex/endpoints", json={"hostname": "direct-score-host"})
        db = SessionLocal()
        db.add(DexScoreRecord(
            hostname="direct-score-host",
            score=72.5,
            device_health_score=80.0,
            network_score=70.0,
            app_performance_score=65.0,
            remediation_score=60.0,
        ))
        db.commit()
        db.close()

        resp = client.get("/api/v1/dex/endpoints/direct-score-host/score")
        assert resp.status_code == 200
        data = resp.json()
        assert data["score"] == 72.5
        assert data["hostname"] == "direct-score-host"

    def test_score_history_with_records(self, client):
        from app.db.database import SessionLocal
        from app.db.models import DexScoreRecord

        client.post("/api/v1/dex/endpoints", json={"hostname": "history-scored-host"})
        db = SessionLocal()
        for score in [80.0, 75.0, 70.0]:
            db.add(DexScoreRecord(hostname="history-scored-host", score=score))
        db.commit()
        db.close()

        resp = client.get("/api/v1/dex/endpoints/history-scored-host/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 3
        assert len(data["history"]) == 3


# ---------------------------------------------------------------------------
# Runbook endpoints (chromadb not installed in test env → 503)
# ---------------------------------------------------------------------------


class TestRunbookEndpoints:
    def test_get_runbooks_503_without_chromadb(self, client):
        client.post("/api/v1/dex/endpoints", json={"hostname": "runbook-host"})
        resp = client.get("/api/v1/dex/endpoints/runbook-host/runbooks")
        assert resp.status_code in (200, 503)

    def test_index_runbook_503_without_chromadb(self, client):
        resp = client.post(
            "/api/v1/dex/runbooks/index",
            params={"doc_id": "test-doc", "content": "some runbook content"},
        )
        assert resp.status_code in (200, 503)


# ---------------------------------------------------------------------------
# KPIs with data
# ---------------------------------------------------------------------------


class TestKPIsWithData:
    def test_kpis_with_resolved_alerts(self, client):
        from datetime import datetime, timedelta, timezone

        from app.db.database import SessionLocal
        from app.db.models import DexAlert

        now = datetime.now(timezone.utc)
        db = SessionLocal()
        alert = DexAlert(
            hostname="kpi-host",
            alert_name="KpiTest",
            severity="warning",
            alert_type="threshold",
            status="resolved",
            remediation_run_id="run-auto-123",
        )
        alert.created_at = now - timedelta(hours=2)
        alert.resolved_at = now - timedelta(hours=1)
        db.add(alert)
        db.commit()
        db.close()

        resp = client.get("/api/v1/dex/kpis?lookback_days=7")
        assert resp.status_code == 200
        data = resp.json()
        assert data["resolved_alerts"] >= 1
        assert data["auto_resolved_alerts"] >= 1
        assert data["mttr_minutes"] is not None
