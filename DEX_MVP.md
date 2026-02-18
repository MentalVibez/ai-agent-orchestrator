# OpenDEX: Open-Source Digital Employee Experience Platform

> **OpenDEX** is an independent, open-source DEX platform. It is not affiliated with, endorsed by, or derived from any commercial DEX vendor.

This document describes the **MVP for OpenDEX**, a fully open-source Digital Employee Experience (DEX) platform using:

| Layer        | Role                          | Technology                    |
|-------------|--------------------------------|-------------------------------|
| **Data**    | Endpoint / device visibility   | **osquery**                   |
| **UI / metrics** | Dashboards, alerting, visualization | **Prometheus + Grafana** |
| **Remediation** | Fix issues (restart services, config) | **Ansible**            |
| **Orchestration & AI** | Route tasks, goal-based runs, workflows | **ai-agent-orchestrator** (this project) |

Together they provide: **visibility (osquery) → metrics & alerts (Prometheus/Grafana) → AI diagnosis & orchestration (orchestrator) → automated fix (Ansible)**.

OpenDEX gives you enterprise-grade endpoint visibility and automated remediation using entirely open-source components — with zero vendor lock-in and zero per-seat licensing fees.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Grafana (dashboards, UI)                         │
└─────────────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Prometheus (scrape /metrics, evaluate rules) → Alertmanager (webhook)   │
└─────────────────────────────────────────────────────────────────────────┘
                    │ scrape                    │ webhook (firing alerts)
                    ▼                           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              AI Agent Orchestrator (FastAPI)                             │
│  • GET /metrics              (Prometheus scrape)                          │
│  • POST /api/v1/webhooks/prometheus  (Alertmanager → optional run)       │
│  • POST /api/v1/run         (goal-based AI runs)                         │
│  • POST /api/v1/orchestrate  (task → agents)                             │
│  • POST /api/v1/workflows    (multi-step: diagnose → remediate)          │
│  Agents: osquery, system_monitoring, ansible, network_diagnostics, ...   │
└─────────────────────────────────────────────────────────────────────────┘
        │                       │
        │ osqueryi               │ ansible-playbook
        ▼                       ▼
┌──────────────┐        ┌──────────────┐
│   osquery    │        │   Ansible    │
│ (endpoints)  │        │ (playbooks)  │
└──────────────┘        └──────────────┘
```

---

## 1. Prerequisites

- **Python 3.10+** – orchestrator
- **osquery** – [install](https://osquery.io/downloads) on hosts you want to query (or on the orchestrator host for local data)
- **Ansible** – `pip install ansible` or system package; playbooks in `playbooks/`
- **Prometheus** – scrape orchestrator and (optionally) node_exporter on endpoints
- **Grafana** – connect to Prometheus, add dashboards

---

## 2. Orchestrator Setup

1. Install and run the API (see main [README](README.md)):
   ```bash
   pip install -r requirements.txt
   cp env.template .env   # set API_KEY, LLM provider (e.g. Bedrock)
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

2. **Prometheus metrics**  
   - Scrape `http://<orchestrator>:8000/metrics` (GET, no auth).  
   - Configure in `prometheus.yml`:
     ```yaml
     scrape_configs:
       - job_name: 'ai-agent-orchestrator'
         static_configs:
           - targets: ['localhost:8000']
         metrics_path: '/metrics'
     ```

3. **Alertmanager → orchestrator**  
   - On firing alerts, POST to the webhook to optionally start an AI run:
     ```
     http://<orchestrator>:8000/api/v1/webhooks/prometheus?trigger_run=true&agent_profile_id=default
     ```
   - Body: default Alertmanager v4 JSON (no auth by default).

---

## 3. Osquery (Data Layer)

- Install osquery on endpoints (or on the same host as the orchestrator for local visibility).
- The **Osquery agent** runs `osqueryi --json "<query>"`. No separate server required for MVP.

**Using the Osquery agent**

- **Orchestrate** with task + context:
  ```json
  POST /api/v1/orchestrate
  { "task": "List top processes by CPU", "context": { "query_key": "processes" } }
  ```
- **Context options**:  
  - `query_key`: one of `processes`, `system_info`, `listening_ports`, `logged_in_users`, `os_version`  
  - `query`: raw osquery SQL (e.g. `SELECT * FROM processes LIMIT 10`)

- **Workflows**  
  Use the `dex_diagnose_remediate_workflow`: it runs osquery (system_info) → system_monitoring → Ansible playbook.

---

## 4. Ansible (Remediation)

- Playbooks live in **`playbooks/`** (e.g. `restart_service.yml`, `ping.yml`).
- The **Ansible agent** runs `ansible-playbook` with context:
  - **playbook** (required): filename, e.g. `restart_service.yml`
  - **inventory**: path (optional)
  - **limit**: host/group (optional)
  - **extra_vars**: dict, e.g. `{"service_name": "nginx"}`

**Example – run playbook via orchestrate**

```json
POST /api/v1/orchestrate
{
  "task": "Run restart_service playbook for nginx",
  "context": {
    "playbook": "restart_service.yml",
    "inventory": "inventory.yml",
    "extra_vars": { "service_name": "nginx" }
  },
  "agent_ids": ["ansible"]
}
```

**Example – DEX workflow (diagnose + remediate)**

```json
POST /api/v1/workflows
{
  "workflow_id": "dex_diagnose_remediate_workflow",
  "input_data": {
    "playbook": "restart_service.yml",
    "extra_vars": { "service_name": "nginx" }
  }
}
```

---

## 5. Prometheus + Grafana

- **Prometheus**: scrape `GET /metrics` from the orchestrator; add other jobs (e.g. node_exporter) as needed.
- **Alertmanager**: configure a webhook receiver to `POST /api/v1/webhooks/prometheus?trigger_run=true` when you want alerts to start an AI run.
- **Grafana**: add Prometheus as data source; use existing [MONITORING.md](MONITORING.md) for metric names (e.g. `http_requests_total`, `agent_executions_total`, `workflow_executions_total`). You can build dashboards for run volume, agent usage, and workflow success.

---

## 6. Summary of Additions in This MVP

| Component | Description |
|----------|-------------|
| **GET /metrics** | Prometheus scrape endpoint (orchestrator metrics). |
| **Osquery agent** | Runs `osqueryi` for endpoint data (processes, ports, system_info, etc.). |
| **Ansible agent** | Runs playbooks from `playbooks/` with context (playbook, inventory, limit, extra_vars). |
| **POST /api/v1/webhooks/prometheus** | Alertmanager webhook; optional `?trigger_run=true` to start a diagnostic run. |
| **Workflow** `dex_diagnose_remediate_workflow` | Steps: osquery → system_monitoring → ansible. |
| **Playbooks** | `playbooks/restart_service.yml`, `playbooks/ping.yml`, `playbooks/inventory.yml`. |

---

## 7. Quick Test

1. Start orchestrator: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
2. **Metrics**: `curl http://localhost:8000/metrics`
3. **Osquery** (if osquery installed):  
   `POST /api/v1/orchestrate` with `task: "System info"`, `context: { "query_key": "system_info" }`, `agent_ids: ["osquery"]`
4. **Ansible** (if Ansible installed):  
   `POST /api/v1/orchestrate` with `task: "Ping"`, `context: { "playbook": "ping.yml" }`, `agent_ids: ["ansible"]`
5. **Webhook**: `POST /api/v1/webhooks/prometheus` with Alertmanager v4 JSON; add `?trigger_run=true` to start a run.

This gives you a minimal **osquery (data) + Prometheus/Grafana (UI) + Ansible (fix) + ai-agent-orchestrator (AI & orchestration)** stack — the **OpenDEX** platform — with no commercial licensing costs.
