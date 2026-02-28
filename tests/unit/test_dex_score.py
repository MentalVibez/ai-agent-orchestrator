"""Unit tests for DEX score calculation engine (app/core/dex/dex_score.py)."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import init_db
from app.db.models import DexAlert, DexScoreRecord, EndpointMetricSnapshot


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


@pytest.fixture
def healthy_snapshot():
    return EndpointMetricSnapshot(
        hostname="test-host",
        cpu_pct=20.0,
        memory_pct=40.0,
        disk_pct=50.0,
        network_latency_ms=10.0,
        packet_loss_pct=0.0,
        services_down=[],
        log_error_count=0,
    )


@pytest.fixture
def critical_snapshot():
    return EndpointMetricSnapshot(
        hostname="test-host",
        cpu_pct=98.0,
        memory_pct=97.0,
        disk_pct=96.0,
        network_latency_ms=600.0,
        packet_loss_pct=8.0,
        services_down=["nginx", "mysql"],
        log_error_count=100,
    )


class TestScoreCalculation:
    def test_healthy_snapshot_scores_high(self, db, healthy_snapshot):
        from app.core.dex.dex_score import calculate_score

        record = calculate_score(db, "test-host-healthy", healthy_snapshot)
        assert record.score >= 80.0, f"Expected healthy score >= 80, got {record.score}"
        assert record.device_health_score == 100.0
        assert record.network_score == 100.0
        assert record.app_performance_score == 100.0

    def test_critical_snapshot_scores_low(self, db, critical_snapshot):
        from app.core.dex.dex_score import calculate_score

        record = calculate_score(db, "test-host-critical", critical_snapshot)
        assert record.score < 30.0, f"Expected critical score < 30, got {record.score}"

    def test_score_persisted_to_db(self, db, healthy_snapshot):
        from app.core.dex.dex_score import calculate_score

        hostname = "test-persist-host"
        record = calculate_score(db, hostname, healthy_snapshot)
        assert record.id is not None
        fetched = db.query(DexScoreRecord).filter(DexScoreRecord.hostname == hostname).first()
        assert fetched is not None
        assert abs(fetched.score - record.score) < 0.01

    def test_score_clamps_to_zero(self, db, critical_snapshot):
        from app.core.dex.dex_score import calculate_score

        record = calculate_score(db, "test-clamp-host", critical_snapshot)
        assert record.score >= 0.0

    def test_score_clamps_to_100(self, db):
        from app.core.dex.dex_score import calculate_score

        perfect = EndpointMetricSnapshot(
            hostname="perfect-host",
            cpu_pct=5.0,
            memory_pct=10.0,
            disk_pct=20.0,
            network_latency_ms=1.0,
            packet_loss_pct=0.0,
            services_down=[],
            log_error_count=0,
        )
        record = calculate_score(db, "perfect-host", perfect)
        assert record.score <= 100.0

    def test_high_cpu_reduces_device_health(self, db):
        from app.core.dex.dex_score import _score_device_health

        snap = EndpointMetricSnapshot(hostname="x", cpu_pct=85.0, memory_pct=10.0, disk_pct=10.0)
        score, reasons = _score_device_health(snap)
        assert score < 100.0
        assert any("CPU" in r for r in reasons)

    def test_critical_cpu_reduces_more(self, db):
        from app.core.dex.dex_score import _score_device_health

        high = EndpointMetricSnapshot(hostname="x", cpu_pct=82.0, memory_pct=10.0, disk_pct=10.0)
        critical = EndpointMetricSnapshot(hostname="x", cpu_pct=96.0, memory_pct=10.0, disk_pct=10.0)
        high_score, _ = _score_device_health(high)
        crit_score, _ = _score_device_health(critical)
        assert crit_score < high_score

    def test_packet_loss_reduces_network_score(self, db):
        from app.core.dex.dex_score import _score_network

        snap = EndpointMetricSnapshot(
            hostname="x", network_latency_ms=10.0, packet_loss_pct=3.0
        )
        score, reasons = _score_network(snap)
        assert score < 100.0
        assert any("loss" in r.lower() for r in reasons)

    def test_service_down_reduces_app_score(self, db):
        from app.core.dex.dex_score import _score_app_performance

        snap = EndpointMetricSnapshot(
            hostname="x", services_down=["nginx", "redis"], log_error_count=0
        )
        score, reasons = _score_app_performance(snap)
        assert score <= 70.0  # 2 services * 15pts each
        assert any("down" in r.lower() for r in reasons)

    def test_none_metrics_do_not_crash(self, db):
        from app.core.dex.dex_score import calculate_score

        snap = EndpointMetricSnapshot(
            hostname="null-host",
            cpu_pct=None,
            memory_pct=None,
            disk_pct=None,
            network_latency_ms=None,
            packet_loss_pct=None,
            services_down=None,
            log_error_count=0,
        )
        record = calculate_score(db, "null-host", snap)
        assert record.score == 100.0  # no deductions when data is missing


class TestThresholdAlerts:
    def test_no_alert_when_score_above_threshold(self, db):
        from app.core.dex.dex_score import evaluate_thresholds

        record = DexScoreRecord(hostname="good-host", score=80.0)
        alert = evaluate_thresholds(db, "good-host", record, alert_threshold=60, critical_threshold=40)
        assert alert is None

    def test_warning_alert_when_score_between_thresholds(self, db):
        from app.core.dex.dex_score import evaluate_thresholds

        record = DexScoreRecord(hostname="warn-host", score=50.0)
        alert = evaluate_thresholds(db, "warn-host", record, alert_threshold=60, critical_threshold=40)
        assert alert is not None
        assert alert.severity == "warning"
        assert alert.alert_type == "threshold"

    def test_critical_alert_when_score_below_critical_threshold(self, db):
        from app.core.dex.dex_score import evaluate_thresholds

        record = DexScoreRecord(hostname="crit-host", score=30.0)
        alert = evaluate_thresholds(db, "crit-host", record, alert_threshold=60, critical_threshold=40)
        assert alert is not None
        assert alert.severity == "critical"

    def test_no_duplicate_active_alerts(self, db):
        from app.core.dex.dex_score import evaluate_thresholds

        record = DexScoreRecord(hostname="dup-host", score=50.0)
        alert1 = evaluate_thresholds(db, "dup-host", record, alert_threshold=60, critical_threshold=40)
        alert2 = evaluate_thresholds(db, "dup-host", record, alert_threshold=60, critical_threshold=40)
        assert alert1 is not None
        assert alert2 is not None
        assert alert1.id == alert2.id  # same record returned, not duplicated


class TestGetLatestScore:
    def test_returns_none_for_unknown_host(self, db):
        from app.core.dex.dex_score import get_latest_score

        result = get_latest_score(db, "unknown-host-xyz")
        assert result is None

    def test_returns_most_recent_record(self, db):
        from app.core.dex.dex_score import get_latest_score

        hostname = "history-host"
        # Commit separately so each row gets its own auto-incremented ID
        # (timestamps may collide at SQLite 1-second resolution; ID is the tiebreaker)
        r1 = DexScoreRecord(hostname=hostname, score=70.0)
        db.add(r1)
        db.commit()
        db.refresh(r1)
        r2 = DexScoreRecord(hostname=hostname, score=85.0)
        db.add(r2)
        db.commit()
        db.refresh(r2)

        record = get_latest_score(db, hostname)
        assert record is not None
        # get_latest_score orders by (scored_at DESC, id DESC) so r2 (higher id) wins
        assert record.id == r2.id
        assert record.score == 85.0

    def test_score_history_returns_multiple(self, db):
        from app.core.dex.dex_score import get_score_history

        hostname = "multi-history-host"
        for score in [60.0, 70.0, 80.0]:
            db.add(DexScoreRecord(hostname=hostname, score=score))
        db.commit()

        records = get_score_history(db, hostname, limit=10)
        assert len(records) == 3
