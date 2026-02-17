"""Prometheus metrics for monitoring."""

from prometheus_client import REGISTRY, Counter, Gauge, Histogram, generate_latest

# Request metrics
http_requests_total = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "endpoint", "status"]
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)

# Agent metrics
agent_executions_total = Counter(
    "agent_executions_total", "Total agent executions", ["agent_id", "status"]
)

agent_execution_duration_seconds = Histogram(
    "agent_execution_duration_seconds",
    "Agent execution duration in seconds",
    ["agent_id"],
    buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)

# LLM metrics
llm_calls_total = Counter("llm_calls_total", "Total LLM API calls", ["provider", "model", "status"])

llm_tokens_total = Counter(
    "llm_tokens_total",
    "Total LLM tokens used",
    ["provider", "model", "type"],  # type: input or output
)

llm_cost_total = Counter("llm_cost_total", "Total LLM cost in USD", ["provider", "model"])

# Workflow metrics
workflow_executions_total = Counter(
    "workflow_executions_total", "Total workflow executions", ["workflow_id", "status"]
)

workflow_execution_duration_seconds = Histogram(
    "workflow_execution_duration_seconds",
    "Workflow execution duration in seconds",
    ["workflow_id"],
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 600.0],
)

# System metrics
active_agents = Gauge("active_agents", "Number of active agents", ["agent_id"])

active_workflows = Gauge("active_workflows", "Number of active workflows", ["workflow_id"])


def record_http_request(method: str, endpoint: str, status_code: int, duration: float):
    """Record HTTP request metrics."""
    status = f"{status_code // 100}xx"
    http_requests_total.labels(method=method, endpoint=endpoint, status=status).inc()
    http_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(duration)


def record_agent_execution(agent_id: str, success: bool, duration: float):
    """Record agent execution metrics."""
    status = "success" if success else "failure"
    agent_executions_total.labels(agent_id=agent_id, status=status).inc()
    agent_execution_duration_seconds.labels(agent_id=agent_id).observe(duration)


def record_llm_call(
    provider: str,
    model: str,
    success: bool,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost: float = 0.0,
):
    """Record LLM call metrics."""
    status = "success" if success else "failure"
    llm_calls_total.labels(provider=provider, model=model, status=status).inc()

    if input_tokens > 0:
        llm_tokens_total.labels(provider=provider, model=model, type="input").inc(input_tokens)
    if output_tokens > 0:
        llm_tokens_total.labels(provider=provider, model=model, type="output").inc(output_tokens)
    if cost > 0:
        llm_cost_total.labels(provider=provider, model=model).inc(cost)


def record_workflow_execution(workflow_id: str, success: bool, duration: float):
    """Record workflow execution metrics."""
    status = "success" if success else "failure"
    workflow_executions_total.labels(workflow_id=workflow_id, status=status).inc()
    workflow_execution_duration_seconds.labels(workflow_id=workflow_id).observe(duration)


def set_active_agents(agent_counts: dict):
    """Set active agent counts."""
    for agent_id, count in agent_counts.items():
        active_agents.labels(agent_id=agent_id).set(count)


def set_active_workflows(workflow_counts: dict):
    """Set active workflow counts."""
    for workflow_id, count in workflow_counts.items():
        active_workflows.labels(workflow_id=workflow_id).set(count)


def get_metrics() -> bytes:
    """Get Prometheus metrics in text format."""
    return generate_latest(REGISTRY)
