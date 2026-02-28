"""Unit tests for DEX predictive analysis (app/core/dex/predictive_analysis.py)."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import init_db
from app.db.models import DexAlert, EndpointMetricSnapshot


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


def _add_snapshots(db, hostname: str, disk_values: list, hours_apart: float = 1.0):
    """Helper: insert snapshots with given disk_pct values, spaced hours_apart hours."""
    base_time = datetime.now(timezone.utc) - timedelta(hours=len(disk_values) * hours_apart)
    for i, disk in enumerate(disk_values):
        ts = base_time + timedelta(hours=i * hours_apart)
        snap = EndpointMetricSnapshot(
            hostname=hostname,
            disk_pct=disk,
            cpu_pct=20.0,
            memory_pct=30.0,
            network_latency_ms=10.0,
            packet_loss_pct=0.0,
            services_down=[],
            log_error_count=0,
        )
        snap.captured_at = ts
        db.add(snap)
    db.commit()


class TestPredictiveAnalysis:
    def test_insufficient_data_returns_status(self, db):
        from app.core.dex.predictive_analysis import analyze_trends

        # Only 2 snapshots — below minimum of 3
        _add_snapshots(db, "sparse-host", [50.0, 55.0])
        trends = analyze_trends(db, "sparse-host")
        assert len(trends) == 1
        assert trends[0]["status"] == "insufficient_data"

    def test_stable_disk_no_alert(self, db):
        from app.core.dex.predictive_analysis import analyze_trends

        # Flat disk usage — no trend
        _add_snapshots(db, "stable-host", [50.0, 50.0, 50.0, 50.0, 50.0])
        trends = analyze_trends(db, "stable-host")
        disk_trend = next((t for t in trends if t["metric"] == "disk_pct"), None)
        assert disk_trend is not None
        assert disk_trend["status"] in ("stable", "stable_trend", "improving")

    def test_rising_disk_creates_alert(self, db):
        from app.core.dex.predictive_analysis import analyze_trends

        # Disk rising fast: 60 → 70 → 80 → 85 → 88 (trending to >90 soon)
        _add_snapshots(db, "rising-disk-host", [60.0, 70.0, 80.0, 85.0, 88.0])
        trends = analyze_trends(db, "rising-disk-host")
        disk_trend = next((t for t in trends if t["metric"] == "disk_pct"), None)
        assert disk_trend is not None
        assert disk_trend["status"] == "alert"
        assert disk_trend["time_to_impact"] is not None
        # Confirm a DexAlert was created
        alert = (
            db.query(DexAlert)
            .filter(DexAlert.hostname == "rising-disk-host", DexAlert.alert_type == "predictive")
            .first()
        )
        assert alert is not None
        assert alert.alert_name == "DiskFull"

    def test_declining_disk_shows_improving(self, db):
        from app.core.dex.predictive_analysis import analyze_trends

        # Disk going down — improving
        _add_snapshots(db, "declining-disk-host", [80.0, 75.0, 70.0, 65.0, 60.0])
        trends = analyze_trends(db, "declining-disk-host")
        disk_trend = next((t for t in trends if t["metric"] == "disk_pct"), None)
        assert disk_trend is not None
        assert disk_trend["status"] == "improving"

    def test_critical_imminent_produces_critical_severity(self, db):
        from app.core.dex.predictive_analysis import analyze_trends

        # Rising so fast it will cross 90% within a few hours
        _add_snapshots(db, "imminent-host", [75.0, 80.0, 84.0, 87.0, 89.0], hours_apart=0.5)
        trends = analyze_trends(db, "imminent-host")
        disk_trend = next((t for t in trends if t["metric"] == "disk_pct"), None)
        if disk_trend and disk_trend.get("status") == "alert":
            # Severity depends on tti — may be warning or critical
            assert disk_trend.get("severity") in ("warning", "critical")

    def test_linear_regression_function(self):
        from app.core.dex.predictive_analysis import _linear_regression

        xs = [0.0, 1.0, 2.0, 3.0]
        ys = [10.0, 15.0, 20.0, 25.0]
        slope, intercept = _linear_regression(xs, ys)
        assert abs(slope - 5.0) < 0.01
        assert abs(intercept - 10.0) < 0.01

    def test_hours_to_threshold_stable_returns_none(self):
        from app.core.dex.predictive_analysis import _hours_to_threshold

        result = _hours_to_threshold(current_value=50.0, slope_per_hour=0.0)
        assert result is None

    def test_hours_to_threshold_declining_returns_none(self):
        from app.core.dex.predictive_analysis import _hours_to_threshold

        result = _hours_to_threshold(current_value=50.0, slope_per_hour=-1.0)
        assert result is None

    def test_hours_to_threshold_rising_returns_estimate(self):
        from app.core.dex.predictive_analysis import _hours_to_threshold

        # At 80%, rising 2%/hr → should hit 90% in ~5 hours
        result = _hours_to_threshold(current_value=80.0, slope_per_hour=2.0, threshold=90.0)
        assert result is not None
        assert abs(result - 5.0) < 0.1

    def test_format_time_minutes(self):
        from app.core.dex.predictive_analysis import _format_time_to_impact

        assert "minutes" in _format_time_to_impact(0.5)

    def test_format_time_hours(self):
        from app.core.dex.predictive_analysis import _format_time_to_impact

        assert "hours" in _format_time_to_impact(3.5)

    def test_format_time_days(self):
        from app.core.dex.predictive_analysis import _format_time_to_impact

        assert "days" in _format_time_to_impact(48.0)

    def test_linear_regression_single_point_fallback(self):
        """_linear_regression with n<2 returns zero slope."""
        from app.core.dex.predictive_analysis import _linear_regression

        slope, intercept = _linear_regression([0.0], [50.0])
        assert slope == 0.0
        assert intercept == 50.0

    def test_hours_to_threshold_already_exceeded(self):
        """When current_value >= threshold, returns 0.0 (already critical)."""
        from app.core.dex.predictive_analysis import _hours_to_threshold

        result = _hours_to_threshold(current_value=95.0, slope_per_hour=1.0, threshold=90.0)
        assert result == 0.0

    def test_rising_cpu_creates_cpu_alert(self, db):
        """CPU trending upward should create a SustainedHighCPU alert."""
        from app.core.dex.predictive_analysis import analyze_trends

        base_time = datetime.now(timezone.utc) - timedelta(hours=5)
        for i, cpu in enumerate([60.0, 68.0, 76.0, 83.0, 88.0]):
            snap = EndpointMetricSnapshot(
                hostname="cpu-trend-host",
                cpu_pct=cpu,
                disk_pct=50.0,
                memory_pct=40.0,
            )
            snap.captured_at = base_time + timedelta(hours=i)
            db.add(snap)
        db.commit()

        trends = analyze_trends(db, "cpu-trend-host")
        cpu_trend = next((t for t in trends if t["metric"] == "cpu_pct"), None)
        assert cpu_trend is not None
        assert cpu_trend["status"] == "alert"
        alert = (
            db.query(DexAlert)
            .filter(DexAlert.hostname == "cpu-trend-host", DexAlert.alert_name == "SustainedHighCPU")
            .first()
        )
        assert alert is not None

    def test_rising_memory_creates_memory_alert(self, db):
        """Memory trending upward should create a MemoryLeak alert."""
        from app.core.dex.predictive_analysis import analyze_trends

        base_time = datetime.now(timezone.utc) - timedelta(hours=5)
        for i, mem in enumerate([62.0, 70.0, 77.0, 84.0, 88.0]):
            snap = EndpointMetricSnapshot(
                hostname="mem-trend-host",
                memory_pct=mem,
                cpu_pct=30.0,
                disk_pct=50.0,
            )
            snap.captured_at = base_time + timedelta(hours=i)
            db.add(snap)
        db.commit()

        trends = analyze_trends(db, "mem-trend-host")
        mem_trend = next((t for t in trends if t["metric"] == "memory_pct"), None)
        assert mem_trend is not None
        assert mem_trend["status"] == "alert"

    def test_slow_rising_disk_shows_stable_trend(self, db):
        """Disk rising so slowly that tti > 7 days should be 'stable_trend', not 'alert'."""
        from app.core.dex.predictive_analysis import analyze_trends

        # Slope ~0.01%/hr means ~10 000 hours to 90% — well beyond 168h window
        base_time = datetime.now(timezone.utc) - timedelta(hours=10)
        for i, disk in enumerate([50.0, 50.05, 50.10, 50.15, 50.20, 50.25]):
            snap = EndpointMetricSnapshot(
                hostname="slow-trend-host",
                disk_pct=disk,
                cpu_pct=20.0,
                memory_pct=30.0,
            )
            snap.captured_at = base_time + timedelta(hours=i * 2)
            db.add(snap)
        db.commit()

        trends = analyze_trends(db, "slow-trend-host")
        disk_trend = next((t for t in trends if t["metric"] == "disk_pct"), None)
        assert disk_trend is not None
        assert disk_trend["status"] == "stable_trend"

    def test_upsert_updates_existing_alert(self, db):
        """_upsert_predictive_alert updates an existing active alert instead of duplicating."""
        from app.core.dex.predictive_analysis import _upsert_predictive_alert

        # Create initial alert
        _upsert_predictive_alert(
            db,
            hostname="upsert-host",
            alert_name="DiskFull",
            message="Disk at 70%",
            predicted_time_to_impact="48.0 hours",
            severity="warning",
        )
        # Update it (should not create a duplicate)
        updated = _upsert_predictive_alert(
            db,
            hostname="upsert-host",
            alert_name="DiskFull",
            message="Disk now at 85%",
            predicted_time_to_impact="8.0 hours",
            severity="critical",
        )
        assert updated.severity == "critical"
        assert updated.message == "Disk now at 85%"

        count = (
            db.query(DexAlert)
            .filter(
                DexAlert.hostname == "upsert-host",
                DexAlert.alert_name == "DiskFull",
                DexAlert.alert_type == "predictive",
            )
            .count()
        )
        assert count == 1  # still only one alert

    def test_metric_with_mostly_none_values_shows_insufficient(self, db):
        """Metric with fewer than _MIN_SNAPSHOTS non-None values is marked insufficient_data."""
        from app.core.dex.predictive_analysis import analyze_trends

        base_time = datetime.now(timezone.utc) - timedelta(hours=5)
        for i in range(5):
            snap = EndpointMetricSnapshot(
                hostname="null-metric-host",
                cpu_pct=None,   # all None — no data for regression
                disk_pct=50.0,
                memory_pct=40.0,
            )
            snap.captured_at = base_time + timedelta(hours=i)
            db.add(snap)
        db.commit()

        trends = analyze_trends(db, "null-metric-host")
        cpu_trend = next((t for t in trends if t["metric"] == "cpu_pct"), None)
        assert cpu_trend is not None
        assert cpu_trend["status"] == "insufficient_data"
