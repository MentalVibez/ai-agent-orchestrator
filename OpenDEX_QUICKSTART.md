# OpenDEX Quick Start

Get the **AI Agent Orchestrator + Prometheus + Grafana** stack running in a few minutes. This is the observability core of [OpenDEX](DEX_MVP.md); add osquery and Ansible on your hosts for full endpoint visibility and remediation.

## 1. Start the stack

From the repo root (with `.env` configured — see main [README](README.md)):

```bash
docker-compose -f docker-compose.opendex.yml up -d
```

This starts:

| Service   | URL                     | Purpose                    |
|-----------|-------------------------|----------------------------|
| Orchestrator | http://localhost:8000 | API, metrics, health      |
| Prometheus   | http://localhost:9090 | Scrapes orchestrator `/metrics` |
| Grafana      | http://localhost:3000 | Dashboards (admin / admin) |

## 2. Check health and metrics

- **Health:** `curl http://localhost:8000/api/v1/health`
- **Metrics (Prometheus format):** `curl http://localhost:8000/metrics`  
  (If your app requires an API key, add `-H "X-API-Key: YOUR_KEY"`.)

Prometheus is already scraping the orchestrator; targets: http://localhost:9090/targets.

## 3. Grafana

1. Open http://localhost:3000 and log in with **admin** / **admin** (change in production).
2. The default datasource **Prometheus** points to `http://prometheus:9090`.
3. Go to **Explore** and run a query, e.g. `http_requests_total` or `agent_executions_total`, to see orchestrator metrics.

You can add dashboards for run volume, agent usage, and workflow executions (see [DEX_MVP.md](DEX_MVP.md) and [MONITORING.md](MONITORING.md) if present).

## 4. Optional: run the DEX workflow

With the orchestrator running and agents (e.g. osquery, Ansible) configured, you can run the diagnose-then-remediate workflow:

```bash
curl -X POST http://localhost:8000/api/v1/workflows \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{
    "workflow_id": "dex_diagnose_remediate_workflow",
    "input_data": {
      "playbook": "restart_service.yml",
      "extra_vars": { "service_name": "nginx" }
    }
  }'
```

See [DEX_MVP.md](DEX_MVP.md) for workflow steps, playbooks, and webhook setup (Alertmanager → `POST /api/v1/webhooks/prometheus`).

## 5. Stop the stack

```bash
docker-compose -f docker-compose.opendex.yml down
```

Data in the orchestrator DB and Grafana is kept in Docker volumes until you remove them with `docker-compose -f docker-compose.opendex.yml down -v`.
