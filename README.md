# AI Agent Orchestrator

A multi-agent backend system that coordinates specialized LLM-powered agents to handle complex IT diagnostics and engineering workflows through a single HTTP API. **Now with MCP (Model Context Protocol)**: register MCP servers, define agent profiles, and run goal-based workflows that compose tools from multiple MCP servers (or fall back to legacy agents when no MCP tools are configured).

> **Production-Ready System**: Fully functional with 7 active agents, 3 LLM providers (Bedrock, OpenAI, Ollama), MCP client layer, SQLite persistence, Docker deployment, and a comprehensive test suite at 70%+ coverage.

---

## Quick Start (Docker — recommended)

```bash
# 1. Clone the repo
git clone https://github.com/MentalVibez/ai-agent-orchestrator
cd ai-agent-orchestrator

# 2. Run the interactive setup wizard
bash scripts/setup.sh
```

The wizard will:
- Ask which LLM provider to use (Bedrock / OpenAI / Ollama)
- Collect credentials and generate a random API key
- Write `.env` and start the Docker stack automatically

Once running:
- **API:** http://localhost:8000
- **Health:** http://localhost:8000/api/v1/health
- **Console:** http://localhost:8000/console
- **Docs (dev only):** http://localhost:8000/docs *(only when `DEBUG=true`)*

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

**OpenDEX** is an independent, open-source Digital Employee Experience (DEX) platform — not affiliated with any commercial DEX vendor. It combines **osquery + Prometheus/Grafana + Ansible + this orchestrator** to deliver enterprise-grade endpoint visibility and automated remediation at zero licensing cost. See **[DEX_MVP.md](DEX_MVP.md)**. To run the orchestrator with Prometheus and Grafana in one go: **[OpenDEX_QUICKSTART.md](OpenDEX_QUICKSTART.md)**.

- **Osquery agent** — endpoint visibility (processes, ports, users, system info)
- **Ansible agent** — run playbooks for automated remediation
- **Prometheus metrics** — `GET /metrics` (auth required)
- **Alertmanager webhook** — `POST /api/v1/webhooks/prometheus`
- **Example workflow** — diagnose → remediate

---

## Architecture

### Core Components

- **Orchestrator** — routes tasks to appropriate agents; coordinates multi-agent workflows
- **Agent Registry** — manages all registered agents and their capabilities
- **Workflow Executor** — executes multi-step workflows with parallel step support
- **LLM Manager** — handles provider selection, initialization, and fallback
- **Planner Loop** — MCP-centric goal executor: LLM chooses tools iteratively until done
- **MCP Client Manager** — connects to stdio MCP servers, discovers tools

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

| Provider | When to use | Cost |
|----------|-------------|------|
| **AWS Bedrock** | Production / cloud | ~$0.001 per request (Claude Haiku) |
| **OpenAI** | GPT-4o alternative | Pay-per-token |
| **Ollama** | Local / self-hosted | **Free** |

Set `LLM_PROVIDER=bedrock`, `openai`, or `ollama` in `.env`.

### MCP-Centric Runs

- **Agent Profiles** — defined in `config/agent_profiles.yaml` (role prompt + allowed MCP servers)
- **Planner Loop** — for a run, the LLM picks tools iteratively until FINISH. Falls back to legacy orchestrator if no MCP tools are configured.
- **Runs API** — `POST /api/v1/run` → returns `run_id`. Poll `GET /api/v1/runs/{run_id}` for status, steps, and final answer; or stream progress via `GET /api/v1/runs/{run_id}/stream` (SSE).

See **[docs/ORCHESTRATION.md](docs/ORCHESTRATION.md)** for when to use `POST /run` vs `POST /orchestrate`, when the planner falls back to legacy agents, and what `agent_profile_id` controls.

**Run queue (optional):** Set `RUN_QUEUE_URL=redis://localhost:6379` to enqueue runs instead of running the planner in-process. Then start a worker (same env, e.g. `DATABASE_URL`, `LLM_PROVIDER`) with: `RUN_QUEUE_URL=redis://localhost:6379 arq app.worker.WorkerSettings`. Requires `pip install arq`. SSE (`GET /runs/{id}/stream`) still works because events are stored in the DB.

**Human-in-the-loop (HITL):** In `config/agent_profiles.yaml`, set `approval_required_tools: [tool_name, ...]` on a profile. When the planner is about to run one of those tools, the run status becomes `awaiting_approval` and the tool is not executed until approved. `GET /api/v1/runs/{run_id}` returns `pending_approval: { server_id, tool_name, arguments, step_index }`. Send `POST /api/v1/runs/{run_id}/approve` with body `{"approved": true}` (or `{"approved": false}` to reject), and optionally `modified_arguments: {...}` to override arguments when approving. After approval, the tool runs and the planner resumes.

---

## Setup

### Prerequisites

- Python 3.10+
- Docker + Docker Compose (for Docker deployment)
- Node.js 20+ in Docker image (auto-installed — needed for MCP servers using `npx`)
- AWS credentials, OpenAI API key, or Ollama running locally

### Environment Variables

Key variables (see `.env.example` for full list):

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `bedrock` | `bedrock` / `openai` / `ollama` |
| `API_KEY` | *(required)* | Must be set — auth fails if empty with `REQUIRE_API_KEY=true` |
| `REQUIRE_API_KEY` | `true` | Set to `false` to disable auth (dev only) |
| `AWS_REGION` | `us-east-1` | Bedrock region |
| `AWS_ACCESS_KEY_ID` | | Bedrock credentials |
| `AWS_SECRET_ACCESS_KEY` | | Bedrock credentials |
| `OPENAI_API_KEY` | | OpenAI API key |
| `OPENAI_MODEL` | `gpt-4o` | OpenAI model |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `llama3.2` | Ollama model name |
| `DEBUG` | `false` | Enables Swagger UI (`/docs`) and verbose errors |
| `DATABASE_URL` | `sqlite:////app/data/orchestrator.db` | SQLite (default) or PostgreSQL URL; for multi-instance/high concurrency use PostgreSQL |
| `CORS_ORIGINS` | `https://yourdomain.com,...` | Comma-separated allowed origins |
| `WEBHOOK_SECRET` | | HMAC secret for Prometheus webhook (leave blank = unauthenticated) |
| `USE_LLM_ROUTING` | `false` | If `true`, `POST /orchestrate` uses LLM to pick agent; else keyword-based |
| `LLM_ROUTING_TIMEOUT_SECONDS` | `10` | Timeout for LLM routing call (fallback to keyword on timeout/failure) |
| `RUN_QUEUE_URL` | *(empty)* | When set (e.g. `redis://localhost:6379`), runs are enqueued; start worker with `arq app.worker.WorkerSettings` |
| `OTEL_ENABLED` | `false` | When `true`, trace runs and planner steps/tool calls via OpenTelemetry (OTLP) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | *(empty)* | OTLP endpoint for traces (e.g. `http://localhost:4318/v1/traces`). Empty = SDK default |

### Database (SQLite and PostgreSQL)

- **SQLite** (default): single-file DB; fine for local dev and single-instance. Set `DATABASE_URL=sqlite:///./orchestrator.db` for a file in the project folder. The app creates tables on startup if they don't exist (`init_db()`).
- **PostgreSQL**: supported for production and multi-instance (e.g. with run-queue workers). Set `DATABASE_URL=postgresql://user:pass@host:5432/dbname`. Create tables with **Alembic**: run `alembic upgrade head` before starting the app (and workers). Migrations live in `alembic/versions/`.

---

## API Endpoints

All endpoints require `X-API-Key: <your-key>` header (unless `REQUIRE_API_KEY=false`).

### Health

```http
GET /api/v1/health
```

Returns `healthy` / `degraded` / `unhealthy` with agent count, DB status, and LLM status.

### Orchestrate (legacy)

```http
POST /api/v1/orchestrate
Content-Type: application/json

{
  "task": "Diagnose network connectivity issues",
  "context": {"hostname": "example.com", "port": 443}
}
```

### MCP Goal-Based Run (recommended)

```http
POST /api/v1/run
Content-Type: application/json

{
  "goal": "Check connectivity to example.com on port 443",
  "agent_profile_id": "default"
}
```

Returns `{ "run_id": "..." }`. Then poll:

```http
GET /api/v1/runs/{run_id}
```

Returns status, steps, tool calls, and `answer` when complete.

**Stream run progress (SSE)**

```http
GET /api/v1/runs/{run_id}/stream
```

Server-Sent Events stream: `status`, `step`, `answer`, and `end` when the run finishes. If the run was started with `stream_tokens: true` in the body of `POST /run`, event type `token` carries LLM output chunks. Best-effort; use `GET /api/v1/runs/{run_id}` for authoritative final state.

### Other Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/runs/{run_id}/stream` | SSE stream of run progress (status, step, answer) |
| `POST /api/v1/runs/{run_id}/approve` | HITL: approve or reject pending tool call (body: `approved`, optional `modified_arguments`) |
| `GET /api/v1/agents` | List all agents |
| `GET /api/v1/agents/{id}` | Agent details |
| `POST /api/v1/workflows` | Execute a workflow |
| `GET /api/v1/metrics/costs` | Cost analytics |
| `GET /api/v1/agent-profiles` | List MCP agent profiles |
| `GET /api/v1/mcp/servers` | List connected MCP servers |
| `POST /api/v1/webhooks/prometheus` | Alertmanager webhook |
| `GET /metrics` | Prometheus scrape (auth required) |

**Prometheus scrape config** — add `X-API-Key` header to your Prometheus job:
```yaml
scrape_configs:
  - job_name: orchestrator
    static_configs:
      - targets: ["localhost:8000"]
    params: {}
    authorization:
      type: Bearer
      credentials_file: /etc/prometheus/api_key
```

---

## Usage Examples

### Goal-based run (MCP)

```python
import requests, time

r = requests.post(
    "http://localhost:8000/api/v1/run",
    headers={"X-API-Key": "your-api-key"},
    json={"goal": "Check connectivity to example.com on port 443", "agent_profile_id": "default"},
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

### Specific agent (osquery)

```python
requests.post(
    "http://localhost:8000/api/v1/orchestrate",
    headers={"X-API-Key": "your-api-key"},
    json={
        "task": "Show running processes",
        "agent_ids": ["osquery"],
        "context": {"query_key": "processes"},
    },
)
```

### Run an Ansible playbook

```python
requests.post(
    "http://localhost:8000/api/v1/orchestrate",
    headers={"X-API-Key": "your-api-key"},
    json={
        "task": "Restart nginx service",
        "agent_ids": ["ansible"],
        "context": {
            "playbook": "restart_service.yml",
            "extra_vars": {"service_name": "nginx"},
        },
    },
)
```

---

## Project Structure

```
ai-agent-orchestrator/
├── app/
│   ├── main.py                   # FastAPI entry point
│   ├── api/v1/routes/            # Route handlers
│   ├── core/
│   │   ├── auth.py               # API key auth (timing-safe)
│   │   ├── config.py             # Settings (pydantic-settings)
│   │   ├── orchestrator.py       # Task routing
│   │   ├── services.py           # Dependency injection / service container
│   │   ├── workflow_executor.py  # Parallel workflow execution
│   │   └── prompt_injection.py   # Input sanitization
│   ├── planner/loop.py           # MCP planner loop
│   ├── mcp/                      # MCP client layer
│   ├── agents/                   # 7 agent implementations
│   ├── llm/                      # Bedrock, OpenAI, Ollama providers
│   ├── db/                       # SQLAlchemy models + migrations
│   └── models/                   # Pydantic request/response models
├── config/
│   ├── agents.yaml
│   ├── mcp_servers.yaml          # MCP server definitions
│   └── agent_profiles.yaml       # Agent profiles (role + allowed tools)
├── playbooks/                    # Ansible playbooks
├── scripts/
│   └── setup.sh                  # Interactive setup wizard
├── tests/
│   ├── unit/                     # 70%+ coverage
│   └── integration/
├── .env.example                  # Environment template
├── Dockerfile                    # Node.js 20 + Python 3.11
├── docker-compose.yml            # With named volume for SQLite persistence
└── alembic/                      # DB migrations
```

---

## Security

This project has undergone a security audit. Key measures in place:

- **API key auth** — timing-safe comparison (`hmac.compare_digest`); server refuses to start if `REQUIRE_API_KEY=true` but `API_KEY` is not set
- **Rate limiting** — `slowapi` on all endpoints including `/metrics`
- **No shell injection** — all subprocess calls use argument lists, never `shell=True`
- **Input validation** — hostname, service name, playbook name, SQL keyword blocklist all validated via strict regex
- **No exception leakage** — raw exception messages never exposed in HTTP responses
- **Security headers** — `X-Frame-Options`, `X-Content-Type-Options`, `X-XSS-Protection`, HSTS (HTTPS only), CSP
- **CORS** — narrowed to specific methods (`GET`, `POST`, `DELETE`) and headers (`X-API-Key`, `Content-Type`, `Accept`)
- **Swagger UI** — disabled in production (`DEBUG=false`)
- **Docker** — non-root `appuser` (UID 1000)

See [SECURITY.md](SECURITY.md) for full details.

---

## Testing

```bash
# Run full test suite with coverage
python -m pytest tests/ -v --tb=short --cov=app --cov-report=term-missing

# Lint
python -m ruff check app/ tests/

# Security audit of dependencies
pip install pip-audit && pip-audit
```

---

## Ultra-Low Cost Deployment

| Component | Cost |
|-----------|------|
| LLM — Ollama + llama3.2 (local) | **$0** |
| LLM — AWS Bedrock Claude Haiku | ~$0.001/request |
| osquery + Prometheus + Grafana + Ansible | **$0** |
| SQLite (built-in) | **$0** |
| Self-hosted (8 GB RAM PC) | **$0** |
| Cloud VPS (Hetzner CX22) | ~$5–6/month |

```bash
# Zero-cost local setup with Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2
echo "LLM_PROVIDER=ollama" >> .env
echo "OLLAMA_BASE_URL=http://localhost:11434" >> .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## Current Status

**All core functionality implemented and tested.**

| Area | Status |
|------|--------|
| Agents | ✅ 7/7 (Network, System, Code Review, Log Analysis, Infrastructure, Osquery, Ansible) |
| LLM Providers | ✅ 3/3 (Bedrock, OpenAI, Ollama) |
| MCP client + planner | ✅ Complete |
| Runs API | ✅ Complete |
| Workflows | ✅ Complete |
| Security (auth, rate limit, injection) | ✅ Audited and hardened |
| Docker + persistence | ✅ Named volume for SQLite |
| Test coverage | ✅ 70%+ |

---

## Contributing

1. Fork the repository
2. Create a feature branch
3. Run `pytest` and `ruff check` — all checks must pass
4. Submit a pull request

See [CONTRIBUTING.md](CONTRIBUTING.md) for full guidelines (including privacy: do not commit paths, usernames, or secrets). See [ADDING_AGENTS.md](ADDING_AGENTS.md) to add new agents.

---

## License

**Apache License 2.0** — see [LICENSE](LICENSE).

- Free for commercial and personal use
- Modify and distribute freely
- Attribution required; document significant changes
- Explicit patent grant (stronger than MIT)

---

## Support

Open an issue on the repository for bugs, questions, or feature requests.
