"""Unit tests for app/core/logging_filters.py — secrets redaction."""

import logging

import pytest

from app.core.logging_filters import SensitiveDataFilter, _is_sensitive_key, _redact_string

# ---------------------------------------------------------------------------
# Tests: _redact_string (pattern-based redaction in message strings)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRedactString:
    def test_plain_text_unchanged(self):
        text = "User logged in from 192.168.1.1"
        assert _redact_string(text) == text

    def test_redacts_orc_prefixed_key(self):
        text = "Using key orc_abc123xyz456789012345 for auth"
        result = _redact_string(text)
        assert "orc_" not in result
        assert "[REDACTED]" in result

    def test_redacts_x_api_key_header(self):
        text = "X-API-Key: supersecretvalue"
        result = _redact_string(text)
        assert "supersecretvalue" not in result
        assert "[REDACTED]" in result

    def test_redacts_authorization_bearer(self):
        text = "Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.payload.signature"
        result = _redact_string(text)
        assert "eyJhbGciOiJSUzI1NiJ9" not in result
        assert "[REDACTED]" in result

    def test_redacts_api_key_equals_pattern(self):
        text = 'api_key=mysecretkey123'
        result = _redact_string(text)
        assert "mysecretkey123" not in result
        assert "[REDACTED]" in result

    def test_redacts_password_json_pattern(self):
        text = '"password": "hunter2"'
        result = _redact_string(text)
        assert "hunter2" not in result
        assert "[REDACTED]" in result

    def test_non_sensitive_value_unchanged(self):
        text = "status=completed duration=1.23s"
        result = _redact_string(text)
        assert result == text

    def test_empty_string_unchanged(self):
        assert _redact_string("") == ""


# ---------------------------------------------------------------------------
# Tests: _is_sensitive_key
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsSensitiveKey:
    @pytest.mark.parametrize("key", [
        "api_key", "API_KEY", "apikey", "password", "PASSWORD",
        "secret", "token", "access_key", "aws_secret", "openai_api_key",
        "authorization", "credential", "private_key", "bearer",
    ])
    def test_sensitive_keys_detected(self, key):
        assert _is_sensitive_key(key) is True

    @pytest.mark.parametrize("key", [
        "run_id", "agent_id", "status", "duration", "method",
        "endpoint", "timestamp", "message", "level",
    ])
    def test_non_sensitive_keys_pass(self, key):
        assert _is_sensitive_key(key) is False


# ---------------------------------------------------------------------------
# Tests: SensitiveDataFilter as a logging.Filter
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSensitiveDataFilter:
    def _make_record(self, msg, args=None, extra_kwargs=None):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=msg,
            args=args or (),
            exc_info=None,
        )
        if extra_kwargs:
            for k, v in extra_kwargs.items():
                setattr(record, k, v)
        return record

    def test_filter_always_returns_true(self):
        f = SensitiveDataFilter()
        record = self._make_record("hello world")
        assert f.filter(record) is True

    def test_redacts_orc_key_in_message(self):
        f = SensitiveDataFilter()
        record = self._make_record("Key is orc_abc123verylongkey9876543210")
        f.filter(record)
        assert "orc_" not in record.msg

    def test_redacts_sensitive_extra_field(self):
        f = SensitiveDataFilter()
        record = self._make_record("action performed", extra_kwargs={"api_key": "supersecret"})
        f.filter(record)
        assert record.api_key == "[REDACTED]"

    def test_non_sensitive_extra_field_unchanged(self):
        f = SensitiveDataFilter()
        record = self._make_record("action", extra_kwargs={"run_id": "abc-123"})
        f.filter(record)
        assert record.run_id == "abc-123"

    def test_redacts_sensitive_dict_args(self):
        # Set args after construction to avoid Python 3.14 LogRecord.__init__
        # dict-handling path which raises KeyError: 0 on dict args.
        f = SensitiveDataFilter()
        record = self._make_record("%(api_key)s")
        record.args = {"api_key": "secretval"}
        f.filter(record)
        assert record.args["api_key"] == "[REDACTED]"

    def test_non_sensitive_dict_args_unchanged(self):
        # Set args after construction for same Python 3.14 compat reason.
        f = SensitiveDataFilter()
        record = self._make_record("%(run_id)s")
        record.args = {"run_id": "run-abc"}
        f.filter(record)
        assert record.args["run_id"] == "run-abc"

    def test_tuple_args_strings_redacted_if_matched(self):
        f = SensitiveDataFilter()
        record = self._make_record("%s", args=("orc_abc123verylongkey9876543210",))
        f.filter(record)
        assert "orc_" not in record.args[0]

    def test_non_string_args_unchanged(self):
        f = SensitiveDataFilter()
        record = self._make_record("%d", args=(42,))
        f.filter(record)
        assert record.args == (42,)

    def test_filter_attaches_to_logger(self):
        """Verify the filter integrates cleanly with the standard logging stack."""
        import io
        f = SensitiveDataFilter()
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.addFilter(f)
        logger = logging.getLogger("test.sensitive")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.info("Connecting with key orc_abc123verylongkey9876543210")
        output = stream.getvalue()
        assert "orc_" not in output
        assert "[REDACTED]" in output
        logger.removeHandler(handler)
