"""Locust load test suite for the AI Agent Orchestrator.

Usage
-----
Install locust (separate from main deps — do not add to requirements.txt):
    pip install locust

Run interactively (opens browser UI at http://localhost:8089):
    locust -f tests/load/locustfile.py --host http://localhost:8000

Run headless (CI / nightly benchmark):
    locust -f tests/load/locustfile.py \
        --host http://localhost:8000 \
        --users 20 \
        --spawn-rate 2 \
        --run-time 60s \
        --headless \
        --csv tests/load/results/benchmark

SLA targets (enforced by the CI nightly job):
    p50 < 200ms  for read endpoints (health, list runs, list agents)
    p95 < 2000ms for POST /orchestrate
    p99 < 10000ms for POST /run (async — returns immediately)
    error rate < 1%

Environment variables consumed:
    LOAD_TEST_API_KEY  — X-API-Key header value (required)
    LOAD_TEST_HOST     — override --host (optional)
"""

import os
import random
import uuid

from locust import HttpUser, between, events, task

# ── SLA thresholds ─────────────────────────────────────────────────────────────
# These mirror the targets documented in the module docstring and the Prometheus
# alert rules in config/prometheus-alerts.yml.  The quitting listener below
# fails the CI job (exit code 1) if any threshold is breached.
_SLA = {
    "p50_read_ms": 200,      # p50 for health / list endpoints
    "p95_write_ms": 2_000,   # p95 for POST /orchestrate
    "p99_run_ms": 10_000,    # p99 for POST /run (async — returns immediately)
    "error_rate_pct": 1.0,   # global 5xx error rate ceiling
}


@events.quitting.add_listener
def _check_sla(environment, **_kwargs):
    """Fail the process (exit code 1) when any SLA target is breached.

    This makes the GitHub Actions nightly load-test job fail visibly rather
    than silently uploading results and passing the workflow.
    """
    stats = environment.runner.stats
    violations: list[str] = []

    # Helper: safe percentile lookup (returns 0 if endpoint not hit)
    def p(name: str, method: str, pct: float) -> float:
        entry = stats.get(name, method)
        if entry is None or entry.num_requests == 0:
            return 0.0
        return entry.get_response_time_percentile(pct)

    # p50 for read endpoints
    for endpoint, method in [
        ("/api/v1/health", "GET"),
        ("/api/v1/runs", "GET"),
        ("/api/v1/agents", "GET"),
    ]:
        val = p(endpoint, method, 0.50)
        if val and val > _SLA["p50_read_ms"]:
            violations.append(f"p50 {method} {endpoint} = {val:.0f}ms > {_SLA['p50_read_ms']}ms")

    # p95 for POST /orchestrate
    val = p("/api/v1/orchestrate", "POST", 0.95)
    if val and val > _SLA["p95_write_ms"]:
        violations.append(f"p95 POST /orchestrate = {val:.0f}ms > {_SLA['p95_write_ms']}ms")

    # p99 for POST /run
    val = p("/api/v1/run", "POST", 0.99)
    if val and val > _SLA["p99_run_ms"]:
        violations.append(f"p99 POST /run = {val:.0f}ms > {_SLA['p99_run_ms']}ms")

    # Global error rate
    total = stats.total
    if total.num_requests > 0:
        error_rate = 100.0 * total.num_failures / total.num_requests
        if error_rate > _SLA["error_rate_pct"]:
            violations.append(f"Error rate = {error_rate:.2f}% > {_SLA['error_rate_pct']}%")

    if violations:
        print("\n[LOAD TEST] SLA VIOLATIONS DETECTED:")
        for v in violations:
            print(f"  ✗ {v}")
        environment.process_exit_code = 1
    else:
        print("\n[LOAD TEST] All SLA targets met.")

API_KEY = os.getenv("LOAD_TEST_API_KEY", "change-me")


def _headers() -> dict:
    return {"X-API-Key": API_KEY, "Content-Type": "application/json"}


def _rand_goal() -> str:
    topics = [
        "Check CPU usage on the primary server",
        "Verify network connectivity to 8.8.8.8",
        "Summarise recent error logs",
        "List running Docker containers",
        "Check disk usage",
    ]
    return random.choice(topics)


class ReadOnlyUser(HttpUser):
    """Simulates a dashboard / monitoring client — read-heavy, no mutations."""

    weight = 3  # 3x more read users than write users
    wait_time = between(0.5, 2)

    @task(5)
    def health_check(self):
        self.client.get("/api/v1/health", name="/api/v1/health")

    @task(3)
    def list_runs(self):
        self.client.get(
            "/api/v1/runs?limit=20&offset=0",
            headers=_headers(),
            name="/api/v1/runs",
        )

    @task(2)
    def list_agents(self):
        self.client.get("/api/v1/agents", headers=_headers(), name="/api/v1/agents")

    @task(1)
    def list_profiles(self):
        self.client.get(
            "/api/v1/agent-profiles", headers=_headers(), name="/api/v1/agent-profiles"
        )


class OrchestrateUser(HttpUser):
    """Simulates API clients submitting diagnostic tasks."""

    weight = 1
    wait_time = between(1, 5)

    @task(4)
    def orchestrate(self):
        """POST /orchestrate — synchronous, exercises keyword routing."""
        self.client.post(
            "/api/v1/orchestrate",
            json={
                "task": _rand_goal(),
                "context": {"test_run": True},
            },
            headers=_headers(),
            name="/api/v1/orchestrate",
        )

    @task(2)
    def start_run_with_idempotency(self):
        """POST /run — async, exercises idempotency key handling."""
        idem_key = f"load-test-{uuid.uuid4()}"
        payload = {
            "goal": _rand_goal(),
            "agent_profile_id": "default",
        }
        with self.client.post(
            "/api/v1/run",
            json=payload,
            headers={**_headers(), "Idempotency-Key": idem_key},
            name="/api/v1/run",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (201, 200):
                resp.failure(f"Unexpected status: {resp.status_code}")
            else:
                resp.success()
                run_id = resp.json().get("run_id")
                if run_id:
                    # Immediately poll status — exercises GET /runs/{id}
                    self.client.get(
                        f"/api/v1/runs/{run_id}",
                        headers=_headers(),
                        name="/api/v1/runs/{run_id}",
                    )

    @task(1)
    def duplicate_idempotency_key(self):
        """Send same Idempotency-Key twice — must return original run, not duplicate."""
        idem_key = f"dup-{uuid.uuid4()}"
        payload = {"goal": _rand_goal(), "agent_profile_id": "default"}
        headers = {**_headers(), "Idempotency-Key": idem_key}

        r1 = self.client.post("/api/v1/run", json=payload, headers=headers, name="/api/v1/run [idem-1]")
        r2 = self.client.post("/api/v1/run", json=payload, headers=headers, name="/api/v1/run [idem-2]")

        if r1.status_code in (200, 201) and r2.status_code in (200, 201):
            id1 = r1.json().get("run_id")
            id2 = r2.json().get("run_id")
            if id1 and id2 and id1 != id2:
                r2.failure(f"Idempotency violated: got different run_ids {id1} vs {id2}")
