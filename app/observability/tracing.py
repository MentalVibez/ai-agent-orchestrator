"""
Optional OpenTelemetry tracing for planner runs, steps, and tool calls.
When OTEL_ENABLED is False or OpenTelemetry packages are not installed, all helpers are no-ops.
"""

import logging
from contextlib import contextmanager
from typing import Any, Generator, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_tracer: Any = None
_initialized: bool = False


def _init_tracer() -> Optional[Any]:
    """Lazily create and set global TracerProvider; return tracer or None if disabled/unavailable."""
    global _tracer, _initialized
    if _initialized:
        return _tracer
    _initialized = True
    if not getattr(settings, "otel_enabled", False):
        return None
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider()
        endpoint = getattr(settings, "otel_exporter_otlp_endpoint", None) or ""
        if endpoint:
            exporter = OTLPSpanExporter(endpoint=endpoint)
        else:
            # Default OTLP HTTP endpoint (e.g. collector on 4318)
            exporter = OTLPSpanExporter()
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("ai-agent-orchestrator", "1.0.0")
        return _tracer
    except ImportError as e:
        logger.debug("OpenTelemetry not installed; tracing disabled: %s", e)
        return None
    except Exception as e:
        logger.warning("Failed to initialize OpenTelemetry tracer: %s", e)
        return None


def tracing_enabled() -> bool:
    """Return True if tracing is active (OTEL_ENABLED and SDK available)."""
    t = _init_tracer()
    return t is not None


@contextmanager
def trace_run(run_id: str, goal: str) -> Generator[Any, None, None]:
    """
    Context manager for a planner run span. No-op when tracing is disabled.
    Use as: with trace_run(run_id, goal): ...
    """
    tracer = _init_tracer()
    if tracer is None:
        yield None
        return
    with tracer.start_as_current_span(
        "planner.run",
        attributes={
            "run_id": run_id,
            "goal": goal[:500] if goal else "",
        },
    ) as span:
        yield span


@contextmanager
def trace_step(run_id: str, step_index: int) -> Generator[Any, None, None]:
    """
    Context manager for a single planner step (LLM call + optional tool). No-op when disabled.
    """
    tracer = _init_tracer()
    if tracer is None:
        yield None
        return
    with tracer.start_as_current_span(
        "planner.step",
        attributes={
            "run_id": run_id,
            "step_index": step_index,
        },
    ) as span:
        yield span


@contextmanager
def trace_tool_call(run_id: str, server_id: str, tool_name: str) -> Generator[Any, None, None]:
    """
    Context manager for an MCP tool call span. No-op when disabled.
    """
    tracer = _init_tracer()
    if tracer is None:
        yield None
        return
    with tracer.start_as_current_span(
        "planner.tool_call",
        attributes={
            "run_id": run_id,
            "mcp.server_id": server_id,
            "mcp.tool_name": tool_name,
        },
    ) as span:
        yield span


@contextmanager
def trace_llm_call(
    provider: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> Generator[Any, None, None]:
    """
    Context manager for an LLM call span using OpenTelemetry GenAI semantic conventions (P2.4).
    Attributes follow https://opentelemetry.io/docs/specs/semconv/gen-ai/ (gen_ai.*).
    No-op when tracing is disabled.

    Args:
        provider: LLM provider name (e.g. "anthropic", "openai", "ollama")
        model: Model identifier
        input_tokens: Input token count (set after call)
        output_tokens: Output token count (set after call)

    Yields:
        span object (or None when disabled)
    """
    tracer = _init_tracer()
    if tracer is None:
        yield None
        return
    with tracer.start_as_current_span(
        "gen_ai.chat",
        attributes={
            "gen_ai.system": provider,
            "gen_ai.request.model": model,
        },
    ) as span:
        yield span
        # Caller can update token counts after the LLM call completes
        if span and input_tokens:
            span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
        if span and output_tokens:
            span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
