"""Unit tests for optional OpenTelemetry tracing (app.observability.tracing)."""

import sys
from unittest.mock import MagicMock, call, patch

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

    def test_trace_llm_call_no_op_when_disabled(self):
        """trace_llm_call yields None without raising when tracing is disabled."""
        import app.observability.tracing as tracing

        tracing._initialized = False
        tracing._tracer = None
        with patch("app.observability.tracing.settings") as mock_settings:
            mock_settings.otel_enabled = False
            yielded = []
            with tracing.trace_llm_call("openai", "gpt-4", 0, 0) as span:
                yielded.append(span)
        assert yielded == [None]


@pytest.mark.unit
class TestTracingInitializer:
    """Tests for _init_tracer() error paths and idempotency."""

    def _reset(self):
        import app.observability.tracing as tracing
        tracing._initialized = False
        tracing._tracer = None

    def test_returns_none_when_otel_disabled(self):
        """Returns None when settings.otel_enabled is False."""
        self._reset()
        import app.observability.tracing as tracing
        with patch("app.observability.tracing.settings") as mock_settings:
            mock_settings.otel_enabled = False
            result = tracing._init_tracer()
        assert result is None

    def test_returns_none_on_import_error(self):
        """Returns None (no exception raised) when OTel SDK is not installed."""
        self._reset()
        import app.observability.tracing as tracing

        otel_modules = {
            "opentelemetry": None,
            "opentelemetry.trace": None,
            "opentelemetry.sdk": None,
            "opentelemetry.sdk.trace": None,
            "opentelemetry.sdk.trace.export": None,
            "opentelemetry.exporter": None,
            "opentelemetry.exporter.otlp": None,
            "opentelemetry.exporter.otlp.proto": None,
            "opentelemetry.exporter.otlp.proto.http": None,
            "opentelemetry.exporter.otlp.proto.http.trace_exporter": None,
        }
        with patch("app.observability.tracing.settings") as mock_settings:
            mock_settings.otel_enabled = True
            with patch.dict(sys.modules, otel_modules):
                result = tracing._init_tracer()
        assert result is None

    def test_returns_none_on_general_exception(self):
        """Returns None when TracerProvider() raises an unexpected exception."""
        self._reset()
        import app.observability.tracing as tracing

        mock_trace = MagicMock()
        mock_provider_cls = MagicMock(side_effect=Exception("config error"))
        mock_exporter_cls = MagicMock()
        mock_batch = MagicMock()

        otel_sdk = MagicMock()
        otel_sdk.TracerProvider = mock_provider_cls
        otel_export = MagicMock()
        otel_export.BatchSpanProcessor = mock_batch
        otel_exporter = MagicMock()
        otel_exporter.OTLPSpanExporter = mock_exporter_cls

        with patch("app.observability.tracing.settings") as mock_settings:
            mock_settings.otel_enabled = True
            mock_settings.otel_exporter_otlp_endpoint = ""
            with patch.dict(sys.modules, {
                "opentelemetry": MagicMock(trace=mock_trace),
                "opentelemetry.trace": mock_trace,
                "opentelemetry.sdk.trace": otel_sdk,
                "opentelemetry.sdk.trace.export": otel_export,
                "opentelemetry.exporter.otlp.proto.http.trace_exporter": otel_exporter,
            }):
                result = tracing._init_tracer()
        assert result is None

    def test_is_idempotent_after_first_call(self):
        """_init_tracer() returns the same result on repeated calls; only initializes once."""
        self._reset()
        import app.observability.tracing as tracing
        with patch("app.observability.tracing.settings") as mock_settings:
            mock_settings.otel_enabled = False
            r1 = tracing._init_tracer()
            r2 = tracing._init_tracer()
        assert r1 is r2  # both None
        assert tracing._initialized is True


@pytest.mark.unit
class TestTracingEnabled:
    """When a tracer is provided (e.g. OTEL enabled and SDK available), spans are created."""

    def _make_tracer_and_span(self):
        mock_tracer = MagicMock()
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=None)
        mock_tracer.start_as_current_span.return_value = mock_span
        return mock_tracer, mock_span

    def test_trace_run_starts_span_when_tracer_set(self):
        import app.observability.tracing as tracing

        mock_tracer, mock_span = self._make_tracer_and_span()

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

        mock_tracer, mock_span = self._make_tracer_and_span()

        with patch.object(tracing, "_init_tracer", return_value=mock_tracer):
            with tracing.trace_tool_call("run-1", "srv-id", "tool_name"):
                pass
            mock_tracer.start_as_current_span.assert_called_once()
            call_args = mock_tracer.start_as_current_span.call_args
            assert call_args[0][0] == "planner.tool_call"
            assert call_args[1]["attributes"]["mcp.server_id"] == "srv-id"
            assert call_args[1]["attributes"]["mcp.tool_name"] == "tool_name"

    def test_trace_step_starts_span_when_tracer_set(self):
        """trace_step creates a planner.step span with run_id and step_index attributes."""
        import app.observability.tracing as tracing

        mock_tracer, mock_span = self._make_tracer_and_span()

        with patch.object(tracing, "_init_tracer", return_value=mock_tracer):
            with tracing.trace_step("run-2", 3):
                pass
            mock_tracer.start_as_current_span.assert_called_once()
            call_args = mock_tracer.start_as_current_span.call_args
            assert call_args[0][0] == "planner.step"
            assert call_args[1]["attributes"]["run_id"] == "run-2"
            assert call_args[1]["attributes"]["step_index"] == 3

    def test_trace_llm_call_starts_span_when_tracer_set(self):
        """trace_llm_call creates a gen_ai.chat span with provider and model attributes."""
        import app.observability.tracing as tracing

        mock_tracer, mock_span = self._make_tracer_and_span()

        with patch.object(tracing, "_init_tracer", return_value=mock_tracer):
            with tracing.trace_llm_call("openai", "gpt-4o"):
                pass
            mock_tracer.start_as_current_span.assert_called_once()
            call_args = mock_tracer.start_as_current_span.call_args
            assert call_args[0][0] == "gen_ai.chat"
            assert call_args[1]["attributes"]["gen_ai.system"] == "openai"
            assert call_args[1]["attributes"]["gen_ai.request.model"] == "gpt-4o"

    def test_trace_llm_call_sets_token_attributes_after_yield(self):
        """span.set_attribute is called for input/output tokens after the with-block exits."""
        import app.observability.tracing as tracing

        mock_tracer, mock_span = self._make_tracer_and_span()

        with patch.object(tracing, "_init_tracer", return_value=mock_tracer):
            with tracing.trace_llm_call("anthropic", "claude-3", 100, 50):
                pass  # yield point; token attrs set after this

        mock_span.set_attribute.assert_any_call("gen_ai.usage.input_tokens", 100)
        mock_span.set_attribute.assert_any_call("gen_ai.usage.output_tokens", 50)

    def test_trace_llm_call_skips_token_attrs_when_zero(self):
        """span.set_attribute is NOT called when input/output tokens are 0."""
        import app.observability.tracing as tracing

        mock_tracer, mock_span = self._make_tracer_and_span()

        with patch.object(tracing, "_init_tracer", return_value=mock_tracer):
            with tracing.trace_llm_call("openai", "gpt-4", 0, 0):
                pass

        mock_span.set_attribute.assert_not_called()
