"""Unit tests for webhook utility functions."""

import time

import pytest

from app.api.v1.routes.webhooks import (
    _alert_fingerprint,
    _alert_summary,
    _dedup_cache,
    _is_duplicate,
    _record_alert,
    _verify_webhook_signature,
)


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
