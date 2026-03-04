# AI Agent Orchestrator

A production-ready multi-agent backend that coordinates specialized LLM-powered agents for complex IT diagnostics and engineering workflows through a single HTTP API.

**MCP-native** — register MCP servers, define agent profiles, and run goal-based workflows that compose tools across multiple servers with native LLM tool calling, RAG, multi-agent messaging, and full observability.

> **1072 tests · 86% coverage · Kubernetes-ready · Supply-chain signed · Zero-downtime deploys**

---

## Quick Start (Docker — recommended)

```bash
git clone https://github.com/MentalVibez/ai-agent-orchestrator
cd ai-agent-orchestrator
bash scripts/setup.sh
```

The setup wizard collects your LLM credentials, generates a strong API key, and starts the full stack automatically.

Once running:

| Service | URL |
|---------|-----|
| API | http://localhost:8000 |
| Health | http://localhost:8000/api/v1/health |
| Grafana dashboards | http://localhost:3000 (admin/admin) |
| Prometheus | http://localhost:9090 |
| Alertmanager | http://localhost:9093 |
| Jaeger traces | http://localhost:16686 |
| Swagger UI (dev only) | http://localhost:8000/docs *(DEBUG=true only)* |

---

## Quick Start (local development)

| Step | Windows | Linux / macOS |
|------|---------|---------------|
| 1. Create virtualenv | `python -m venv venv` | `python3 -m venv venv` |
| 2. Activate | `venv\Scripts\activate` | `source venv/bin/activate` |
| 3. Install deps | `pip install -r requirements.txt` | `pip install -r requirements.txt` |
| 4. Copy env template | `copy .env.example .env` | `cp .env.example .env` |
| 5. Edit `.env` | Set `API_KEY`, `LLM_PROVIDER`, and provider credentials | Same |
| 6. Start | `uvicorn app.main:app --reload --port 8000` | `uvicorn app.main:app --reload --port 8000` |

> Set `DATABASE_URL=sqlite:///./orchestrator.db` in `.env` for local dev (keeps the DB file in the project folder instead of `/app/data`).

---

## OpenDEX Platform

**OpenDEX** is an independent, open-source Digital Employee Experience platform — not affiliated with any commercial DEX vendor. It combines **osquery + Prometheus/Grafana + Ansible + this orchestrator** to deliver enterprise-grade endpoint visibility and automated remediation at zero licensing cost. See **[DEX_MVP.md](DEX_MVP.md)** and **[OpenDEX_QUICKSTART.md](OpenDEX_QUICKSTART.md)**.

- **Osquery agent** — endpoint visibility (processes, ports, users, system info)
- **Ansible agent** — run playbooks for automated remediation
- **DEX scoring** — Device Health (40%) + Network Quality (30%) + App Performance (20%) + Remediation Rate (10%)
- **Predictive analysis** — anomaly detection with automated alert creation
- **Self-healing** — set `DEX_SELF_HEALING_ENABLED=true` to auto-trigger Ansible playbooks from alerts
- **Prometheus + Grafana** — pre-wired and auto-provisioned in `docker-compose.yml`

---

## Architecture

### Core Components

| Component | File | Role |
|-----------|------|------|
| Orchestrator | `app/core/orchestrator.py` | Routes tasks to agents; coordinates workflows |
| Planner Loop | `app/planner/loop.py` | MCP-centric goal executor with checkpointing |
| MCP Client Manager | `app/mcp/client_manager.py` | Connects to stdio + HTTP SSE MCP servers |
| Workflow Executor | `app/core/workflow_executor.py` | DAG execution with conditional edges |
| LLM Manager | `app/llm/manager.py` | Provider selection, init, and fallback |
| RAG Manager | `app/core/rag_manager.py` | ChromaDB-backed document indexing and search |
| Agent Message Bus | `app/core/agent_bus.py` | asyncio.Queue peer-to-peer messaging |
| Agent Memory | `app/core/agent_memory.py` | DB-backed session state per agent/run |
| Cost Tracker | `app/core/cost_tracker.py` | Token usage analytics, persisted to DB |
| Circuit Breaker | `app/core/circuit_breaker.py` | Fast-fail on sustained LLM provider failures |

### Agents (7 active)

| Agent | ID | Capabilities |
|-------|----|-------------|
| Network Diagnostics | `network_diagnostics` | ping, traceroute, DNS, port checks |
| System Monitoring | `system_monitoring` | CPU, memory, disk, processes |
| Code Review | `code_review` | security analysis, quality review |
| Log Analysis | `log_analysis` | log parsing, error detection, journalctl |
| Infrastructure | `infrastructure` | systemd services, Docker containers, AWS summary |
| Osquery | `osquery` | endpoint visibility via SQL queries |
| Ansible | `ansible` | run validated Ansible playbooks |

### LLM Providers (3 implemented)

| Provider | Tool Calling | When to use | Cost |
|----------|-------------|-------------|------|
| **AWS Bedrock** | ✅ Converse API | Production / cloud | ~$0.001/request (Claude Haiku) |
| **OpenAI** | ✅ `tools` parameter | GPT-4o alternative | Pay-per-token |
| **Ollama** | Text fallback | Local / self-hosted | **Free** |

Set `LLM_PROVIDER=bedrock`, `openai`, or `ollama` in `.env`.

> **Native tool calling**: Bedrock uses the Converse API with `toolConfig`; OpenAI uses the `tools` parameter. Both map MCP tool schemas automatically via `app/llm/tool_schema.py`. Ollama falls back to JSON text parsing.

---

## MCP-Centric Runs

- **Agent Profiles** — defined in `config/agent_profiles.yaml` (role prompt + allowed MCP servers)
- **Planner Loop** — LLM picks tools iteratively until FINISH. Falls back to legacy orchestrator if no MCP tools are configured.
- **Checkpointing** — `checkpoint_step_index` saved to DB after each tool call. If the planner crashes mid-run, `resume_planner_loop` skips already-completed steps.
- **Idempotency** — include `Idempotency-Key: <uuid>` header on `POST /run` to prevent duplicate runs on retries.
- **Human-in-the-loop (HITL)** — set `approval_required_tools: [tool_name]` in a profile; run pauses at `awaiting_approval` status. Resume with `POST /api/v1/runs/{run_id}/approve`.

See **[docs/ORCHESTRATION.md](docs/ORCHESTRATION.md)** for when to use `POST /run` vs `POST /orchestrate`.

### MCP Transport Support

Both **stdio** and **HTTP SSE** transports are supported:

```yaml
# config/mcp_servers.yaml
mcp_servers:
  fetch:
    transport: stdio
    command: uvx            # Python-based (uv installed in Docker)
    args: ["mcp-server-fetch"]

  my_http_server:
    transport: sse
    url: http://localhost:8001/sse
    name: My HTTP MCP Server
```

---

## Setup

### Prerequisites

- Python 3.10+
- Docker + Docker Compose (for Docker deployment)
- Node.js 20+ in Docker image (auto-installed — needed for MCP servers using `npx`)
- AWS credentials, OpenAI API key, or Ollama running locally

### Environment Variables

Key variables (see `.env.example` for full list, `.env.production.example` for production template):

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `bedrock` | `bedrock` / `openai` / `ollama` |
| `API_KEY` | *(required)* | Bootstrap admin key — rotate every 90 days |
| `REQUIRE_API_KEY` | `true` | Set `false` for dev only |
| `METRICS_TOKEN` | | Separate bearer token for Prometheus `/metrics` scrape |
| `WEBHOOK_SECRET` | | HMAC-SHA256 secret for Alertmanager webhook |
| `AWS_REGION` | `us-east-1` | Bedrock region |
| `DATABASE_URL` | `sqlite:////app/data/orchestrator.db` | SQLite (default) or PostgreSQL |
| `CORS_ORIGINS` | `https://yourdomain.com,...` | Comma-separated allowed origins |
| `OTEL_ENABLED` | `false` | Enable OpenTelemetry tracing |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | | OTLP endpoint (Jaeger, Tempo, etc.) |
| `RUN_QUEUE_URL` | | Redis URL for async run queue |
| `CIRCUIT_BREAKER_FAIL_MAX` | `5` | Failures before circuit opens |
| `GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS` | `30` | Drain time on SIGTERM |
| `LOG_FORMAT` | | `json` for structured logging (recommended in production) |

### RBAC — Named API Keys

Beyond the bootstrap `API_KEY`, create per-consumer named keys with roles:

```bash
# Create an operator key for your CI pipeline
curl -X POST https://api.yourdomain.com/api/v1/admin/keys \
  -H "X-API-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "ci-pipeline", "role": "operator"}'

# Response includes raw_key — shown once only; store in your secrets manager
```

| Role | Permissions |
|------|-------------|
| `viewer` | Read-only: GET /runs, GET /agents, health |
| `operator` | viewer + start/cancel runs, approve HITL |
| `admin` | operator + create/revoke API keys |

### Database

- **SQLite** — single-file DB; fine for local dev. Set `DATABASE_URL=sqlite:///./orchestrator.db`.
- **PostgreSQL** — required for production and multi-instance. Run `alembic upgrade head` before starting the app. Migrations live in `alembic/versions/`.

---

## API Endpoints

All endpoints require `X-API-Key: <your-key>` header (unless `REQUIRE_API_KEY=false`).

### Health

```http
GET /api/v1/health
```

Returns `healthy` / `degraded` / `unhealthy` with agent count, DB status, and LLM status.

### MCP Goal-Based Run (recommended)

```http
POST /api/v1/run
Idempotency-Key: <uuid>          (optional — prevents duplicate runs on retry)
Content-Type: application/json

{
  "goal": "Check connectivity to example.com on port 443",
  "agent_profile_id": "default"
}
```

Returns `{ "run_id": "..." }`. Then poll `GET /api/v1/runs/{run_id}` or stream with `GET /api/v1/runs/{run_id}/stream` (SSE).

### Orchestrate (legacy)

```http
POST /api/v1/orchestrate
Content-Type: application/json

{
  "task": "Diagnose network connectivity issues",
  "context": {"hostname": "example.com", "port": 443}
}
```

### Full Endpoint Reference

| Endpoint | Role required | Description |
|----------|--------------|-------------|
| `GET /api/v1/health` | — | Health check (DB, agents, LLM status) |
| `POST /api/v1/run` | operator | Start a goal-based MCP run |
| `GET /api/v1/runs` | viewer | List runs (filter by status) |
| `GET /api/v1/runs/{run_id}` | viewer | Get run status, steps, answer |
| `GET /api/v1/runs/{run_id}/stream` | viewer | SSE stream of run progress |
| `POST /api/v1/runs/{run_id}/approve` | operator | HITL: approve/reject pending tool call |
| `DELETE /api/v1/runs/{run_id}` | operator | Cancel a run |
| `POST /api/v1/orchestrate` | operator | Legacy multi-agent orchestration |
| `GET /api/v1/agents` | viewer | List all agents |
| `GET /api/v1/agent-profiles` | viewer | List MCP agent profiles |
| `GET /api/v1/mcp/servers` | viewer | List connected MCP servers |
| `POST /api/v1/workflows` | operator | Execute a YAML workflow |
| `GET /api/v1/metrics/costs` | viewer | LLM cost analytics |
| `POST /api/v1/rag/index` | operator | Index a document into ChromaDB |
| `POST /api/v1/rag/search` | viewer | Semantic search over a collection |
| `GET /api/v1/rag/collections` | viewer | List all collections |
| `DELETE /api/v1/rag/collection/{name}` | admin | Delete a ChromaDB collection |
| `POST /api/v1/admin/keys` | admin | Create a named API key |
| `GET /api/v1/admin/keys` | admin | List all API keys |
| `DELETE /api/v1/admin/keys/{key_id}` | admin | Revoke an API key |
| `POST /api/v1/webhooks/prometheus` | — | Alertmanager webhook receiver |
| `GET /metrics` | bearer `METRICS_TOKEN` | Prometheus scrape endpoint |

---

## Usage Examples

### Goal-based run (MCP)

```python
import requests, time

r = requests.post(
    "http://localhost:8000/api/v1/run",
    headers={"X-API-Key": "your-api-key", "Idempotency-Key": "run-001"},
    json={"goal": "Check connectivity to example.com on port 443"},
)
run_id = r.json()["run_id"]

while True:
    run = requests.get(
        f"http://localhost:8000/api/v1/runs/{run_id}",
        headers={"X-API-Key": "your-api-key"},
    ).json()
    if run["status"] in ("completed", "failed", "cancelled"):
        break
    time.sleep(1)

print(run.get("answer"))
```

### RAG: index and search

```python
# Index a runbook
requests.post(
    "http://localhost:8000/api/v1/rag/index",
    headers={"X-API-Key": "your-api-key"},
    json={
        "collection": "runbooks",
        "document_id": "nginx-restart",
        "text": "To restart nginx: systemctl restart nginx. Check status with systemctl status nginx.",
        "metadata": {"service": "nginx", "team": "ops"},
    },
)

# Semantic search
results = requests.post(
    "http://localhost:8000/api/v1/rag/search",
    headers={"X-API-Key": "your-api-key"},
    json={"collection": "runbooks", "query": "how to restart a web server", "n_results": 3},
).json()
```

### Conditional workflow (YAML)

```yaml
steps:
  - step_id: diagnose
    name: Diagnose Network
    agent_id: network_diagnostics
    task: "Check connectivity to 10.0.0.1"

  - step_id: remediate
    name: Run Remediation
    agent_id: ansible
    task: "Restart network service"
    depends_on: [diagnose]
    condition: "context.get('is_error') == True"
```

---

## Security

Security-audited and hardened for production. Key measures:

- **API key auth** — timing-safe comparison (`hmac.compare_digest`); DB-backed RBAC (viewer/operator/admin roles)
- **Per-key rate limiting** — each API key gets its own independent bucket; no shared-IP quota starvation
- **Idempotency keys** — `Idempotency-Key` header on `POST /run` prevents duplicate runs on network retries
- **Prompt injection filter** — all user-controlled strings sanitized before reaching the LLM
- **Input validation** — hostname, playbook name, agent ID validated via strict regex
- **Secrets redaction** — log filter strips API keys from all log output
- **No shell injection** — all subprocess calls use argument lists, never `shell=True`
- **Security headers** — `X-Frame-Options: DENY`, `X-Content-Type-Options`, HSTS, CSP
- **Docker** — multi-stage build (no build tools in production image); non-root `appuser` (UID 1000)
- **Kubernetes** — Pod Security Standards enforced (`readOnlyRootFilesystem`, `allowPrivilegeEscalation: false`, `capabilities: drop ALL`, `seccompProfile: RuntimeDefault`); dedicated ServiceAccount with empty rules
- **Supply chain** — Docker images signed with **cosign** (keyless OIDC); **SBOM** (SPDX-JSON) attached as cosign attestation on every release

See [SECURITY.md](SECURITY.md) for full details, [docs/SECRET_ROTATION.md](docs/SECRET_ROTATION.md) for rotation procedures.

---

## Observability

### Full Stack (included in `docker-compose.yml`)

| Tool | Port | Purpose |
|------|------|---------|
| Prometheus | 9090 | Metrics scraping + alert evaluation |
| Grafana | 3000 | Pre-provisioned dashboards (auto-configured) |
| Alertmanager | 9093 | Alert routing — PagerDuty, email, webhook |
| Jaeger | 16686 | Distributed trace UI |

All services auto-start with `docker-compose up`. Grafana connects to Prometheus automatically via provisioning. Prometheus scrapes the API at `/metrics` using `METRICS_TOKEN`.

### Prometheus Metrics

```
http_requests_total             — by endpoint, method, status
http_request_duration_seconds   — histogram for latency percentiles
llm_calls_total                 — by provider, status
llm_cost_total                  — cumulative cost in USD
llm_tokens_total                — input + output token counts
planner_steps_total             — by run_id
rate_limit_exceeded_total       — 429 responses
```

### SLA Alert Rules (`config/prometheus-alerts.yml`)

| Alert | Condition | Severity |
|-------|-----------|----------|
| ServiceDown | `up == 0` for 1m | critical |
| HighErrorRate | 5xx > 1% for 5m | critical |
| OrchestrateLatencyHigh | p95 > 5s for 5m | warning |
| LLMCallFailureSpike | failure rate > 10% for 5m | critical |
| LLMCostSpike | cost increase > $10/hr | warning (finance team) |

### OpenTelemetry Tracing

When `OTEL_ENABLED=true`, the orchestrator emits traces using the **GenAI semantic conventions** (`gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`). Traces span full run lifecycles, individual planner steps, and MCP tool calls.

Export to Jaeger (included in compose), Grafana Tempo, Honeycomb, or any OTLP backend.

---

## Kubernetes Deployment

Full K8s manifests in `k8s/`:

```bash
# 1. Create namespace + secrets
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/postgres-secret.yaml   # copied from secret.yaml.example
kubectl apply -f k8s/secret.yaml            # API_KEY, METRICS_TOKEN, etc.

# 2. Run migrations first
kubectl apply -f k8s/migration-job.yaml -n ai-agent-orchestrator
kubectl wait --for=condition=complete job/orchestrator-migration \
  -n ai-agent-orchestrator --timeout=300s

# 3. Deploy everything else
kubectl apply -k k8s/

# Or use the deploy script (substitutes image tag, waits for rollout)
scripts/k8s-deploy.sh v1.2.3
```

**What's included:**

| Manifest | Purpose |
|----------|---------|
| `deployment.yaml` | 3 replicas, rolling update, readiness/liveness probes |
| `hpa.yaml` | Auto-scales 3→10 replicas on CPU/memory pressure |
| `pdb.yaml` | minAvailable: 2 — tolerates single-node failures |
| `networkpolicy.yaml` | Restricts ingress/egress to only what's needed |
| `ingress.yaml` | NGINX + cert-manager TLS, 20 RPS ingress rate limit |
| `rbac.yaml` | Dedicated ServiceAccount with empty rules (least privilege) |
| `postgres.yaml` | StatefulSet with 20Gi PVC |
| `migration-job.yaml` | Runs `alembic upgrade head` before app rollout |

---

## Project Structure

```
ai-agent-orchestrator/
├── app/
│   ├── main.py                    # FastAPI entry point + middleware stack
│   ├── api/v1/routes/
│   │   ├── runs.py                # Run lifecycle (create, poll, SSE, approve)
│   │   ├── orchestrator.py        # Legacy orchestrate endpoint
│   │   ├── agents.py              # Agent listing
│   │   ├── metrics.py             # Cost and metrics APIs
│   │   ├── api_keys.py            # RBAC key management (admin only)
│   │   ├── rag.py                 # RAG endpoints
│   │   ├── dex.py                 # DEX platform endpoints
│   │   └── webhooks.py            # Prometheus Alertmanager webhook
│   ├── core/
│   │   ├── auth.py                # API key auth + RBAC
│   │   ├── api_keys.py            # DB-backed key registry
│   │   ├── idempotency.py         # Idempotency-Key deduplication
│   │   ├── rate_limit.py          # Per-key rate limiting
│   │   ├── circuit_breaker.py     # LLM fast-fail
│   │   ├── logging_config.py      # Structured JSON logging
│   │   ├── logging_filters.py     # Secrets redaction
│   │   ├── dex/                   # DEX scoring, telemetry, self-healing
│   │   └── ...
│   ├── planner/loop.py            # MCP planner + HITL + checkpointing
│   ├── mcp/                       # stdio + HTTP SSE transport
│   ├── agents/                    # 7 agent implementations
│   ├── llm/                       # Bedrock, OpenAI, Ollama providers
│   ├── db/                        # SQLAlchemy models + migrations
│   └── observability/tracing.py   # OTel GenAI semantic conventions
├── config/
│   ├── agents.yaml
│   ├── agent_profiles.yaml        # MCP profiles (role + tools + HITL)
│   ├── mcp_servers.yaml           # stdio + SSE server definitions
│   ├── llm.yaml                   # LLM provider templates
│   ├── prometheus.yml             # Prometheus scrape + alert config
│   ├── prometheus-alerts.yml      # 15 SLA-driven alert rules
│   ├── alertmanager.yml           # Alert routing (PagerDuty, email, webhook)
│   └── grafana/                   # Auto-provisioned dashboards
├── k8s/                           # Kubernetes manifests
├── docs/
│   ├── ORCHESTRATION.md
│   ├── API_VERSIONING.md
│   ├── DISASTER_RECOVERY.md       # RTO/RPO, 7 recovery runbooks
│   ├── OPERATIONS.md              # Troubleshooting guide
│   └── SECRET_ROTATION.md        # 90-day rotation procedures
├── scripts/
│   ├── setup.sh                   # Interactive setup wizard
│   ├── k8s-deploy.sh              # K8s deployment automation
│   ├── backup.sh                  # PostgreSQL backup (+ S3 upload)
│   └── restore.sh                 # PostgreSQL restore
├── tests/
│   ├── unit/                      # 1000+ unit tests
│   ├── integration/               # Integration tests
│   └── load/locustfile.py         # SLA-enforced Locust load tests
├── .env.example                   # Dev environment template
├── .env.production.example        # Production environment template
├── Dockerfile                     # Multi-stage build (builder + runtime)
├── docker-compose.yml             # Full stack: API + DB + Prometheus + Grafana + Alertmanager + Jaeger
├── docker-compose.staging.yml     # Staging variant
└── alembic/                       # DB migrations (5 versions)
```

---

## Testing

```bash
# Full test suite (1072 tests)
python -m pytest tests/ -q

# With coverage report
python -m pytest tests/ --cov=app --cov-report=term-missing

# Lint
python -m ruff check app/ tests/

# Type checking
python -m mypy app/

# Security audit
pip-audit

# Load test (requires running API + locust)
locust -f tests/load/locustfile.py --host http://localhost:8000 --users 20 --spawn-rate 2 --run-time 60s --headless
```

### CI Pipeline

Every push/PR runs:
1. **Lint** — ruff, mypy (type warnings), bandit (SAST, medium+ severity)
2. **Security** — pip-audit (hard fail on unresolved CVEs)
3. **Tests** — pytest matrix (Python 3.11 + 3.12); coverage gates 80% (auth/security), 70% (general)
4. **Migrations** — `alembic upgrade head` + `downgrade base` smoke test
5. **Docker build** — smoke-builds the multi-stage image

On merge to `main` or semver tag:
- **Docker publish** — pushes to GHCR (`ghcr.io/<owner>/ai-agent-orchestrator`)
- **cosign signing** — keyless OIDC signature attached to image
- **SBOM** — SPDX-JSON generated by syft, attached as cosign attestation

Nightly:
- **Load test** — Locust SLA enforcement (p50 < 200ms, p95 < 2s, error rate < 1%); fails CI on SLA breach

---

## Operations

| Document | Contents |
|----------|---------|
| [docs/DISASTER_RECOVERY.md](docs/DISASTER_RECOVERY.md) | RTO/RPO targets, 7 recovery runbooks, quarterly DR drill |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | 503 debug, OOM tuning, MCP timeout, DB pool, LLM failover, log queries, kubectl commands |
| [docs/SECRET_ROTATION.md](docs/SECRET_ROTATION.md) | 90-day rotation procedures for all credentials |

---

## Ultra-Low Cost Deployment

| Component | Cost |
|-----------|------|
| LLM — Ollama + llama3.2 (local) | **$0** |
| LLM — AWS Bedrock Claude Haiku | ~$0.001/request |
| osquery + Prometheus + Grafana + Ansible | **$0** |
| SQLite (built-in) | **$0** |
| ChromaDB RAG (local, in-memory) | **$0** |
| Self-hosted (8 GB RAM PC) | **$0** |
| Cloud VPS (Hetzner CX22) | ~$5–6/month |

```bash
# Zero-cost local setup with Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2
echo "LLM_PROVIDER=ollama" >> .env
echo "OLLAMA_BASE_URL=http://localhost:11434" >> .env
docker-compose up
```

---

## Current Status

**1072 tests · 86% coverage · Production-ready**

| Area | Status |
|------|--------|
| Agents | ✅ 7/7 (Network, System, Code Review, Log Analysis, Infrastructure, Osquery, Ansible) |
| LLM Providers | ✅ 3/3 — native tool calling on Bedrock + OpenAI; text fallback on Ollama |
| MCP transport | ✅ stdio + HTTP SSE |
| Planner + HITL | ✅ Complete — with crash-safe checkpointing |
| RAG (ChromaDB) | ✅ Optional — `/api/v1/rag/*` endpoints |
| DEX Platform | ✅ Endpoint registry, scoring, predictive analysis, self-healing |
| Multi-agent messaging | ✅ asyncio.Queue message bus |
| RBAC API keys | ✅ DB-backed (viewer/operator/admin) + key rotation |
| Idempotency | ✅ `Idempotency-Key` header on `POST /run` |
| Circuit breaker | ✅ LLM fast-fail with configurable thresholds |
| Observability | ✅ Prometheus + Grafana + Alertmanager + Jaeger — all in docker-compose |
| OTel tracing | ✅ GenAI semantic conventions |
| Kubernetes | ✅ HA (3+ replicas), HPA, PDB, network policies, Pod Security Standards, RBAC |
| Supply chain | ✅ cosign image signing + SBOM (SPDX-JSON) on every release |
| Load testing | ✅ SLA-enforced Locust — fails CI on p50/p95/p99/error rate breach |
| Backup / restore | ✅ `scripts/backup.sh` + `scripts/restore.sh` with S3 support |
| Documentation | ✅ DR runbook, operations guide, secret rotation guide |
| Security | ✅ Audited — SAST, pip-audit, secrets redaction, PSS, image signing |
| Tests | ✅ 1072 passing, 86% coverage |

---

## Contributing

1. Fork the repository
2. Create a feature branch
3. Run `pytest` and `ruff check` — all checks must pass
4. Submit a pull request

See [CONTRIBUTING.md](CONTRIBUTING.md) for full guidelines. See [ADDING_AGENTS.md](ADDING_AGENTS.md) to add new agents.

---

## License

**Apache License 2.0** — see [LICENSE](LICENSE).

Free for commercial and personal use. Modify and distribute freely. Attribution required; document significant changes. Explicit patent grant (stronger than MIT).

---

## Support

Open an issue on the repository for bugs, questions, or feature requests.
