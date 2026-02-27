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
import string
import uuid

from locust import HttpUser, between, task


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
