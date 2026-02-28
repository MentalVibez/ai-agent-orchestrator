# Operations Guide — AI Agent Orchestrator + DEX Platform

This guide covers deployment, configuration, day-to-day operation, and troubleshooting of the full stack: the AI Agent Orchestrator API and the DEX (Digital Employee Experience) platform built on top of it.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Quick Start (Docker)](#quick-start-docker)
3. [Environment Variables](#environment-variables)
4. [DEX Platform Configuration](#dex-platform-configuration)
5. [First Steps: Registering Endpoints](#first-steps-registering-endpoints)
6. [Understanding DEX Scores](#understanding-dex-scores)
7. [Alerts and Self-Healing](#alerts-and-self-healing)
8. [Scheduled Jobs](#scheduled-jobs)
9. [Prometheus Alertmanager Integration](#prometheus-alertmanager-integration)
10. [Employee Feedback (eNPS)](#employee-feedback-enps)
11. [Runbook Management](#runbook-management)
12. [Database Backup and Restore](#database-backup-and-restore)
13. [Monitoring the Platform Itself](#monitoring-the-platform-itself)
14. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI (app/main.py)                                          │
│  ├── /api/v1/runs          — planner run lifecycle              │
│  ├── /api/v1/dex/*         — DEX endpoints, scores, alerts      │
│  ├── /api/v1/webhooks      — Prometheus Alertmanager receiver    │
│  ├── /api/v1/rag/*         — ChromaDB runbook search            │
│  └── /metrics              — Prometheus scrape endpoint         │
└────────────────────────────────┬────────────────────────────────┘
                                 │
             ┌───────────────────┼──────────────────┐
             ▼                   ▼                  ▼
        SQLite/Postgres        Redis             ChromaDB
        (run + DEX data)   (arq job queue)   (runbook RAG)
             │
             ▼
    arq Worker (app/worker.py)
    ├── run_planner       — processes enqueued AI runs
    ├── dex_scan_all_endpoints  — every N minutes (cron)
    └── dex_check_predictive_alerts — every hour (cron)
```

**Key components:**
| Component | File | Purpose |
|---|---|---|
| Planner loop | `app/planner/loop.py` | MCP-based agentic execution (15 steps max) |
| DEX score engine | `app/core/dex/dex_score.py` | 0–100 composite score (device/network/app/remediation) |
| Self-healing | `app/core/dex/self_healing.py` | Alert → auto-remediation or ticket creation |
| Predictive analysis | `app/core/dex/predictive_analysis.py` | Linear regression on metric trends |
| Telemetry collector | `app/core/dex/telemetry_collector.py` | Triggers and processes health scan runs |

---

## Quick Start (Docker)

```bash
# 1. Copy and edit environment config
cp .env.example .env
# Set: API_KEY, LLM_PROVIDER, OPENAI_API_KEY (or ANTHROPIC_API_KEY)

# 2. Start the stack
docker compose up -d

# 3. Verify health
curl http://localhost:8000/health

# 4. With Redis (enables background jobs and scheduled DEX scans)
docker compose --profile queue up -d
```

The API is now available at `http://localhost:8000`. API docs: `http://localhost:8000/docs`.

---

## Environment Variables

### Core

| Variable | Default | Description |
|---|---|---|
| `API_KEY` | `""` | Required API key for all endpoints. Empty = auth disabled (dev only). |
| `REQUIRE_API_KEY` | `true` | Set `false` to disable auth in dev/test. |
| `LLM_PROVIDER` | `openai` | `openai` \| `anthropic` \| `bedrock` \| `ollama` |
| `OPENAI_API_KEY` | — | Required when `LLM_PROVIDER=openai` |
| `ANTHROPIC_API_KEY` | — | Required when `LLM_PROVIDER=anthropic` |
| `DATABASE_URL` | `sqlite:////app/data/orchestrator.db` | PostgreSQL or SQLite URL |
| `RUN_QUEUE_URL` | `""` | Redis URL for arq. Leave empty to run jobs in-process. |
| `LOG_FORMAT` | `json` | `json` for structured logging, `text` for human-readable |
| `LOG_LEVEL` | `INFO` | Python log level |
| `PORT` | `8000` | HTTP port |

### Security

| Variable | Default | Description |
|---|---|---|
| `METRICS_TOKEN` | `""` | Bearer token for `/metrics` endpoint. Empty = open. |
| `WEBHOOK_SECRET` | `""` | HMAC-SHA256 secret for webhook signature verification. |
| `WEBHOOK_REQUIRE_AUTH` | `true` | Require `X-Webhook-Token` header. |

### DEX Platform

| Variable | Default | Description |
|---|---|---|
| `DEX_SCAN_INTERVAL_MINUTES` | `15` | How often to scan all endpoints. Must divide evenly into 60. |
| `DEX_SCORE_ALERT_THRESHOLD` | `60` | Score below this → warning alert |
| `DEX_SCORE_CRITICAL_THRESHOLD` | `40` | Score below this → critical alert |
| `DEX_SELF_HEALING_ENABLED` | `false` | Set `true` to enable auto-remediation. |
| `DEX_TICKET_WEBHOOK_URL` | `""` | External ticket system URL for unresolvable alerts. |

---

## DEX Platform Configuration

### Remediation Map

Edit `config/dex_remediation_map.yaml` to define what happens when each alert fires:

```yaml
remediation_map:
  DiskFull:
    action: ansible
    playbook: cleanup_disk
    requires_approval: false   # auto-trigger without human review

  ServiceDown:
    action: restart
    service: "{{ labels.service }}"
    requires_approval: false

  HighMemory:
    action: ansible
    playbook: clear_cache
    requires_approval: false

  KernelPanic:
    action: ticket             # always escalate — cannot auto-heal
    severity: critical
```

**Supported actions:**

| Action | Description |
|---|---|
| `ansible` | Run Ansible playbook from `config/runbooks/` on the target endpoint |
| `restart` | Restart a named service |
| `clear_cache` | Run a cache/temp cleanup |
| `ticket` | Always escalate — triggers `DEX_TICKET_WEBHOOK_URL` regardless of `DEX_SELF_HEALING_ENABLED` |

Changes to this file are picked up immediately (hot-reload on each alert evaluation).

---

## First Steps: Registering Endpoints

```bash
# Register a developer workstation
curl -X POST http://localhost:8000/api/v1/dex/endpoints \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "hostname": "dev-machine-01",
    "ip_address": "10.0.1.42",
    "owner_email": "alice@company.com",
    "persona": "developer",
    "criticality_tier": 2,
    "os_platform": "linux",
    "tags": {"dept": "engineering", "location": "HQ"}
  }'

# List all registered endpoints
curl http://localhost:8000/api/v1/dex/endpoints -H "X-API-Key: your-api-key"

# Trigger an immediate on-demand scan
curl -X POST http://localhost:8000/api/v1/dex/endpoints/dev-machine-01/scan \
  -H "X-API-Key: your-api-key"

# Poll for scan completion
curl http://localhost:8000/api/v1/runs/{run_id} -H "X-API-Key: your-api-key"

# View current DEX score
curl http://localhost:8000/api/v1/dex/endpoints/dev-machine-01/score \
  -H "X-API-Key: your-api-key"
```

**Persona values:** `developer` | `salesperson` | `executive` | `tech` | `general`

**Criticality tiers:** `1` = critical (SLA-bound), `2` = standard, `3` = low priority

---

## Understanding DEX Scores

Scores range from **0–100**. They are calculated from four weighted components:

| Component | Weight | Signals |
|---|---|---|
| Device Health | 40% | CPU, memory, disk utilization |
| Network Quality | 30% | Latency, packet loss, DNS failures |
| App Performance | 20% | Services down, log error rate |
| Remediation Rate | 10% | % of recent alerts auto-resolved |

**Score thresholds (defaults):**

| Score | Status |
|---|---|
| > 60 | Healthy |
| 40–60 | At-risk (warning alert) |
| < 40 | Critical (critical alert) |

View score history and predictive trends:

```bash
# Last 24 hours of score history
curl "http://localhost:8000/api/v1/dex/endpoints/dev-machine-01/history?limit=96" \
  -H "X-API-Key: your-api-key"

# Predictive trend analysis (projects when metrics will hit 90%)
curl http://localhost:8000/api/v1/dex/endpoints/dev-machine-01/trends \
  -H "X-API-Key: your-api-key"

# Fleet-wide summary
curl http://localhost:8000/api/v1/dex/fleet -H "X-API-Key: your-api-key"
```

---

## Alerts and Self-Healing

### Alert Lifecycle

```
Scan completes → score below threshold
         OR
Prometheus Alertmanager fires for a registered endpoint
         OR
Predictive analysis detects trend toward critical
         ↓
DexAlert created (status: active)
         ↓
self_healing.handle_alert()
   ├── Mapping found + DEX_SELF_HEALING_ENABLED=true
   │        ↓
   │   Remediation run triggered (status: remediating)
   │        ↓
   │   Run completes → alert manually resolved or auto-checked next scan
   │
   └── No mapping OR self-healing disabled
            ↓
       Ticket webhook POST'd (status: needs_human)
```

### Acknowledging Alerts

Suppress an alert for a configurable window:

```bash
curl -X POST "http://localhost:8000/api/v1/dex/alerts/42/acknowledge?hours=4" \
  -H "X-API-Key: your-api-key"
```

### Viewing Active Incidents

```bash
# All active alerts
curl "http://localhost:8000/api/v1/dex/alerts" -H "X-API-Key: your-api-key"

# Filter by hostname, severity, or type
curl "http://localhost:8000/api/v1/dex/alerts?hostname=dev-machine-01&severity=critical" \
  -H "X-API-Key: your-api-key"

# Correlated incidents (endpoints with 2+ active alerts)
curl http://localhost:8000/api/v1/dex/incidents -H "X-API-Key: your-api-key"

# KPIs (MTTR, auto-resolution rate, fleet score)
curl "http://localhost:8000/api/v1/dex/kpis?lookback_days=7" -H "X-API-Key: your-api-key"
```

---

## Scheduled Jobs

DEX scanning runs as arq cron jobs. **Requires Redis (`RUN_QUEUE_URL`).**

| Job | Schedule | Description |
|---|---|---|
| `dex_scan_all_endpoints` | Every `DEX_SCAN_INTERVAL_MINUTES` | Health scan for all active endpoints |
| `dex_check_predictive_alerts` | Every hour | Trend analysis across all endpoints |

Worker settings:
- **`max_tries = 1`** — runs are not retried (each run_id is unique)
- **`job_timeout = 600s`** — jobs killed after 10 minutes
- **`keep_result = 7200s`** — results kept in Redis for 2 hours for debugging

Start the worker:

```bash
RUN_QUEUE_URL=redis://localhost:6379 arq app.worker.WorkerSettings
```

Or via Docker Compose (with Redis profile):

```bash
docker compose --profile queue up worker
```

---

## Prometheus Alertmanager Integration

Configure Alertmanager to send firing alerts to the webhook:

```yaml
# alertmanager.yml
receivers:
  - name: orchestrator
    webhook_configs:
      - url: http://orchestrator:8000/api/v1/webhooks/alertmanager
        send_resolved: true
        http_config:
          authorization:
            credentials: "your-webhook-secret-hmac"
```

When an alert fires for a hostname that matches a registered DEX endpoint, the platform automatically:
1. Creates a `DexAlert` with `alert_type=prometheus`
2. Deduplicates (won't create a second alert if one is already active for the same `alertname`)
3. Calls `self_healing.handle_alert()` — auto-remediates or escalates to ticket

The `hostname` label is extracted from `labels.hostname` first, then `labels.instance` (stripping the port).

---

## Employee Feedback (eNPS)

Collect and analyze employee sentiment:

```bash
# Submit a pulse survey
curl -X POST http://localhost:8000/api/v1/dex/feedback \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"hostname": "dev-machine-01", "rating": 4, "comment": "VPN is slow", "category": "connectivity"}'

# Aggregated sentiment summary (last 30 days)
curl "http://localhost:8000/api/v1/dex/feedback/summary?lookback_days=30" \
  -H "X-API-Key: your-api-key"
```

**eNPS calculation:** `(promoters − detractors) / total × 100`
- Promoters: rating ≥ 4
- Passives: rating = 3
- Detractors: rating ≤ 2

---

## Runbook Management

Index runbooks into ChromaDB for AI-powered retrieval:

```bash
# Bulk index all runbooks from config/runbooks/
python scripts/index_runbooks.py

# Retrieve relevant runbooks for an endpoint's active alerts
curl "http://localhost:8000/api/v1/dex/endpoints/dev-machine-01/runbooks?alert=DiskFull" \
  -H "X-API-Key: your-api-key"

# Index a single runbook via API
curl -X POST "http://localhost:8000/api/v1/dex/runbooks/index?doc_id=disk_cleanup_v2&content=..." \
  -H "X-API-Key: your-api-key"
```

Runbook markdown files live in `config/runbooks/`. Add new ones and re-run `index_runbooks.py`.

---

## Database Backup and Restore

```bash
# Backup (creates timestamped .sql.gz in ./backups/)
./scripts/backup.sh

# Restore from a specific backup
./scripts/restore.sh backups/orchestrator_20260228_120000.sql.gz
```

For PostgreSQL in production, also configure `pg_dump` in a cron job or use managed backups.

---

## Monitoring the Platform Itself

Prometheus metrics are exposed at `GET /metrics` (protected by `METRICS_TOKEN`):

```yaml
# prometheus.yml scrape config
scrape_configs:
  - job_name: orchestrator
    static_configs:
      - targets: ["orchestrator:8000"]
    authorization:
      credentials: "${METRICS_TOKEN}"
```

Key metrics:

| Metric | Description |
|---|---|
| `orchestrator_runs_total` | Total planner runs by status |
| `orchestrator_run_duration_seconds` | Run duration histogram |
| `orchestrator_agent_calls_total` | Agent invocations by name |
| `orchestrator_llm_cost_usd_total` | Estimated LLM cost |

SLA alert rules are defined in `config/prometheus-alerts.yml`.

---

## Troubleshooting

### Scan shows "unparseable_answer"

The `dex_proactive` agent didn't return structured JSON. Check:
1. The LLM provider is reachable (`curl http://localhost:8000/health`)
2. The `dex_proactive` profile exists in `config/agent_profiles.yaml`
3. Planner logs: `docker compose logs app | grep dex_proactive`

### DEX score is always 100

No metric data is being collected. The scan run may be stuck. Check:
1. `GET /api/v1/runs/{run_id}` — is status `completed` or `failed`?
2. If `failed`, check `run.error` field
3. Agents require target endpoints to be network-reachable from the orchestrator container

### Alerts fire but self-healing does nothing

1. Confirm `DEX_SELF_HEALING_ENABLED=true` in your `.env`
2. Verify the `alert_name` has an entry in `config/dex_remediation_map.yaml`
3. Check logs: `docker compose logs worker | grep "DEX self-healing"`

### Worker jobs not running

1. Confirm Redis is reachable: `redis-cli -u $RUN_QUEUE_URL ping`
2. Check worker process: `docker compose ps worker`
3. Worker logs: `docker compose logs worker`

### Coverage gate fails in CI

The DEX platform requires ≥70% coverage of `app/core/dex/` and `app/api/v1/routes/dex`. Run locally:

```bash
pytest tests/ --cov=app/core/dex --cov=app/api/v1/routes/dex --cov-report=term-missing -q
```
