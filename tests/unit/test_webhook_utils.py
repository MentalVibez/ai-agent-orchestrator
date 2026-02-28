"""Unit tests for webhook utility functions and DEX self-healing hook."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.routes.webhooks import (
    _alert_fingerprint,
    _alert_summary,
    _dedup_cache,
    _fire_dex_self_healing,
    _is_duplicate,
    _record_alert,
    _verify_webhook_signature,
)
from app.db.database import init_db
from app.db.models import DexAlert, Endpoint


# ---------------------------------------------------------------------------
# Module-level DB patch (needed for _fire_dex_self_healing tests)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def use_in_memory_db():
    import app.core.persistence as persistence_module
    import app.core.run_store as run_store_module
    import app.db.database as db_module
    import app.api.v1.routes.webhooks as webhooks_module

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


@pytest.mark.unit
class TestAlertSummary:
    """Test _alert_summary utility function."""

    def test_basic_alert(self):
        alert = {
            "labels": {"alertname": "HighCPU"},
            "annotations": {"summary": "CPU usage is high"},
        }
        summary = _alert_summary(alert)
        assert "CPU usage is high" in summary

    def test_with_instance(self):
        alert = {
            "labels": {"alertname": "HighCPU", "instance": "server1:9100"},
            "annotations": {"summary": "CPU high"},
        }
        summary = _alert_summary(alert)
        assert "server1:9100" in summary

    def test_falls_back_to_description(self):
        alert = {
            "labels": {"alertname": "HighCPU"},
            "annotations": {"description": "CPU is at 95%"},
        }
        summary = _alert_summary(alert)
        assert "CPU is at 95%" in summary

    def test_falls_back_to_alertname(self):
        alert = {
            "labels": {"alertname": "HighCPU"},
            "annotations": {},
        }
        summary = _alert_summary(alert)
        assert "HighCPU" in summary

    def test_empty_alert(self):
        alert = {}
        summary = _alert_summary(alert)
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_none_labels(self):
        alert = {"labels": None, "annotations": None}
        summary = _alert_summary(alert)
        assert isinstance(summary, str)


@pytest.mark.unit
class TestAlertFingerprint:
    """Test _alert_fingerprint utility function."""

    def test_consistent_fingerprint(self):
        alert = {"labels": {"alertname": "HighCPU", "instance": "host1"}}
        fp1 = _alert_fingerprint(alert)
        fp2 = _alert_fingerprint(alert)
        assert fp1 == fp2

    def test_different_labels_different_fingerprint(self):
        alert1 = {"labels": {"alertname": "HighCPU", "instance": "host1"}}
        alert2 = {"labels": {"alertname": "HighCPU", "instance": "host2"}}
        assert _alert_fingerprint(alert1) != _alert_fingerprint(alert2)

    def test_label_order_independent(self):
        alert1 = {"labels": {"a": "1", "b": "2"}}
        alert2 = {"labels": {"b": "2", "a": "1"}}
        assert _alert_fingerprint(alert1) == _alert_fingerprint(alert2)

    def test_empty_labels(self):
        alert = {"labels": {}}
        fp = _alert_fingerprint(alert)
        assert isinstance(fp, str)
        assert len(fp) == 64  # SHA256 hex

    def test_no_labels_key(self):
        alert = {}
        fp = _alert_fingerprint(alert)
        assert isinstance(fp, str)


@pytest.mark.unit
class TestIsDuplicate:
    """Test _is_duplicate utility function."""

    def setup_method(self):
        """Clear dedup cache before each test."""
        _dedup_cache.clear()

    def test_not_duplicate_on_first_seen(self):
        assert _is_duplicate("new_fp_123", ttl_seconds=60) is False

    def test_is_duplicate_within_ttl(self):
        _dedup_cache["fp_abc"] = time.monotonic()
        assert _is_duplicate("fp_abc", ttl_seconds=60) is True

    def test_not_duplicate_after_ttl_expires(self):
        _dedup_cache["fp_old"] = time.monotonic() - 120  # 2 minutes ago
        assert _is_duplicate("fp_old", ttl_seconds=60) is False

    def test_zero_ttl_always_not_duplicate(self):
        _dedup_cache["fp_zero"] = time.monotonic()
        # TTL of 0 means everything is immediately expired
        assert _is_duplicate("fp_zero", ttl_seconds=0) is False


@pytest.mark.unit
class TestRecordAlert:
    """Test _record_alert utility function."""

    def setup_method(self):
        _dedup_cache.clear()

    def test_records_fingerprint(self):
        _record_alert("fp_new")
        assert "fp_new" in _dedup_cache

    def test_recorded_time_is_recent(self):
        before = time.monotonic()
        _record_alert("fp_time")
        after = time.monotonic()
        assert before <= _dedup_cache["fp_time"] <= after

    def test_prunes_when_cache_large(self):
        """Test that cache is pruned when it exceeds 1000 entries."""
        # Fill cache with old (stale) entries
        old_time = time.monotonic() - 9999
        for i in range(1001):
            _dedup_cache[f"fp_{i}"] = old_time

        _record_alert("fp_new_trigger")
        # Cache should have been pruned
        assert len(_dedup_cache) < 1002

    def test_can_record_multiple(self):
        _record_alert("fp_a")
        _record_alert("fp_b")
        assert "fp_a" in _dedup_cache
        assert "fp_b" in _dedup_cache


@pytest.mark.unit
class TestVerifyWebhookSignature:
    """Test _verify_webhook_signature utility function."""

    def test_no_secret_with_require_auth_true_returns_false(self):
        """When no secret is set and webhook_require_auth=True (default), reject all webhooks."""
        from unittest.mock import MagicMock, patch

        mock_request = MagicMock()
        with patch("app.api.v1.routes.webhooks.settings") as mock_settings:
            mock_settings.webhook_secret = ""
            mock_settings.webhook_require_auth = True
            result = _verify_webhook_signature(b"body", mock_request)
        assert result is False

    def test_no_secret_with_require_auth_false_returns_true(self):
        """When no secret is set and WEBHOOK_REQUIRE_AUTH=False, allow all webhooks."""
        from unittest.mock import MagicMock, patch

        mock_request = MagicMock()
        with patch("app.api.v1.routes.webhooks.settings") as mock_settings:
            mock_settings.webhook_secret = ""
            mock_settings.webhook_require_auth = False
            result = _verify_webhook_signature(b"body", mock_request)
        assert result is True

    def test_valid_hmac_token_accepted(self):
        """Valid HMAC-SHA256 token should be accepted."""
        import hashlib
        import hmac
        from unittest.mock import MagicMock, patch

        secret = "my_secret"
        body = b"test payload"
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        mock_request = MagicMock()
        mock_request.headers = {"X-Webhook-Token": expected}

        with patch("app.api.v1.routes.webhooks.settings") as mock_settings:
            mock_settings.webhook_secret = secret
            result = _verify_webhook_signature(body, mock_request)
        assert result is True

    def test_invalid_token_rejected(self):
        """Wrong HMAC token should be rejected."""
        from unittest.mock import MagicMock, patch

        mock_request = MagicMock()
        mock_request.headers = {"X-Webhook-Token": "wrong_token"}

        with patch("app.api.v1.routes.webhooks.settings") as mock_settings:
            mock_settings.webhook_secret = "my_secret"
            result = _verify_webhook_signature(b"body", mock_request)
        assert result is False

    def test_missing_token_rejected(self):
        """Missing X-Webhook-Token header should be rejected when secret is set."""
        from unittest.mock import MagicMock, patch

        mock_request = MagicMock()
        mock_request.headers = {}

        with patch("app.api.v1.routes.webhooks.settings") as mock_settings:
            mock_settings.webhook_secret = "my_secret"
            result = _verify_webhook_signature(b"body", mock_request)
        assert result is False


# ---------------------------------------------------------------------------
# _fire_dex_self_healing
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFireDexSelfHealing:
    """Tests for the _fire_dex_self_healing background task."""

    @pytest.mark.asyncio
    async def test_no_hostname_in_labels_returns_early(self):
        """Alert with no hostname or instance label does nothing."""
        alert_data = {"labels": {}, "annotations": {}}
        # No DB interaction expected — returns silently
        await _fire_dex_self_healing(alert_data, "test summary")

    @pytest.mark.asyncio
    async def test_unknown_hostname_returns_early(self):
        """Alert for a hostname not in the DEX registry does nothing."""
        alert_data = {
            "labels": {"hostname": "unregistered-host", "alertname": "HighCPU"},
        }
        with patch(
            "app.core.dex.endpoint_registry.get_endpoint", return_value=None
        ):
            await _fire_dex_self_healing(alert_data, "CPU high")

    @pytest.mark.asyncio
    async def test_inactive_endpoint_returns_early(self):
        """Alert for an inactive DEX endpoint does nothing."""
        alert_data = {
            "labels": {"hostname": "inactive-webhook-host", "alertname": "HighCPU"},
        }
        inactive_ep = MagicMock()
        inactive_ep.is_active = False

        with patch(
            "app.core.dex.endpoint_registry.get_endpoint", return_value=inactive_ep
        ):
            await _fire_dex_self_healing(alert_data, "CPU high")

    @pytest.mark.asyncio
    async def test_registered_endpoint_creates_alert_and_heals(self):
        """Alert for a registered active endpoint creates a DexAlert and calls handle_alert."""
        from app.db.database import SessionLocal

        # Register the endpoint in DB
        db = SessionLocal()
        ep = Endpoint(hostname="heal-webhook-host", is_active=True)
        db.add(ep)
        db.commit()
        db.close()

        alert_data = {
            "labels": {
                "hostname": "heal-webhook-host",
                "alertname": "DiskFull",
                "severity": "warning",
            },
            "annotations": {"summary": "Disk nearly full"},
        }

        with patch(
            "app.core.dex.self_healing.handle_alert", new=AsyncMock()
        ) as mock_handle:
            await _fire_dex_self_healing(alert_data, "Disk nearly full")

        mock_handle.assert_awaited_once()
        # Verify the DexAlert was written to DB
        db = SessionLocal()
        alert = (
            db.query(DexAlert)
            .filter(
                DexAlert.hostname == "heal-webhook-host",
                DexAlert.alert_name == "DiskFull",
                DexAlert.alert_type == "prometheus",
            )
            .first()
        )
        db.close()
        assert alert is not None
        assert alert.severity == "warning"

    @pytest.mark.asyncio
    async def test_duplicate_active_alert_skipped(self):
        """A second Prometheus alert for the same active alert_name is deduplicated."""
        from app.db.database import SessionLocal

        # Register endpoint + an already-active alert
        db = SessionLocal()
        ep = Endpoint(hostname="dedup-webhook-host", is_active=True)
        db.add(ep)
        existing = DexAlert(
            hostname="dedup-webhook-host",
            alert_name="ServiceDown",
            alert_type="prometheus",
            status="active",
        )
        db.add(existing)
        db.commit()
        db.close()

        alert_data = {
            "labels": {
                "hostname": "dedup-webhook-host",
                "alertname": "ServiceDown",
            },
        }

        with patch(
            "app.core.dex.self_healing.handle_alert", new=AsyncMock()
        ) as mock_handle:
            await _fire_dex_self_healing(alert_data, "Service down")

        # handle_alert should NOT have been called (dedup)
        mock_handle.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_hostname_extracted_from_instance_label(self):
        """Falls back to instance label (stripping port) when hostname label is absent."""
        alert_data = {
            "labels": {"instance": "my-server:9100", "alertname": "HighCPU"},
        }
        with patch(
            "app.core.dex.endpoint_registry.get_endpoint", return_value=None
        ) as mock_get:
            await _fire_dex_self_healing(alert_data, "CPU high")

        mock_get.assert_called_once()
        called_hostname = mock_get.call_args.args[1]
        assert called_hostname == "my-server"
