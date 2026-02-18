"""Unit tests for optional OpenTelemetry tracing (app.observability.tracing)."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestTracingDisabled:
    """When OTEL_ENABLED is False or OpenTelemetry is not installed, tracing is no-op."""

    def test_tracing_enabled_false_when_otel_disabled(self):
        import app.observability.tracing as tracing

        tracing._initialized = False
        tracing._tracer = None
        with patch("app.observability.tracing.settings") as mock_settings:
            mock_settings.otel_enabled = False
            mock_settings.otel_exporter_otlp_endpoint = ""
            assert tracing.tracing_enabled() is False

    def test_trace_run_no_op_when_disabled(self):
        import app.observability.tracing as tracing

        tracing._initialized = False
        tracing._tracer = None
        with patch("app.observability.tracing.settings") as mock_settings:
            mock_settings.otel_enabled = False
            with tracing.trace_run("run-1", "my goal"):
                pass  # should not raise

    def test_trace_step_no_op_when_disabled(self):
        import app.observability.tracing as tracing

        tracing._initialized = False
        tracing._tracer = None
        with patch("app.observability.tracing.settings") as mock_settings:
            mock_settings.otel_enabled = False
            with tracing.trace_step("run-1", 1):
                pass

    def test_trace_tool_call_no_op_when_disabled(self):
        import app.observability.tracing as tracing

        tracing._initialized = False
        tracing._tracer = None
        with patch("app.observability.tracing.settings") as mock_settings:
            mock_settings.otel_enabled = False
            with tracing.trace_tool_call("run-1", "srv", "tool"):
                pass


@pytest.mark.unit
class TestTracingEnabled:
    """When a tracer is provided (e.g. OTEL enabled and SDK available), spans are created."""

    def test_trace_run_starts_span_when_tracer_set(self):
        import app.observability.tracing as tracing

        mock_tracer = MagicMock()
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=None)
        mock_tracer.start_as_current_span.return_value = mock_span

        with patch.object(tracing, "_init_tracer", return_value=mock_tracer):
            with tracing.trace_run("run-1", "my goal"):
                pass
            mock_tracer.start_as_current_span.assert_called_once()
            call_args = mock_tracer.start_as_current_span.call_args
            assert call_args[0][0] == "planner.run"
            assert call_args[1]["attributes"]["run_id"] == "run-1"
            assert "goal" in call_args[1]["attributes"]

    def test_trace_tool_call_starts_span_when_tracer_set(self):
        import app.observability.tracing as tracing

        mock_tracer = MagicMock()
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=None)
        mock_tracer.start_as_current_span.return_value = mock_span

        with patch.object(tracing, "_init_tracer", return_value=mock_tracer):
            with tracing.trace_tool_call("run-1", "srv-id", "tool_name"):
                pass
            mock_tracer.start_as_current_span.assert_called_once()
            call_args = mock_tracer.start_as_current_span.call_args
            assert call_args[0][0] == "planner.tool_call"
            assert call_args[1]["attributes"]["mcp.server_id"] == "srv-id"
            assert call_args[1]["attributes"]["mcp.tool_name"] == "tool_name"
