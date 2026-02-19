# AI Agent Orchestrator

A multi-agent backend system that coordinates specialized LLM-powered agents to handle complex IT diagnostics and engineering workflows through a single HTTP API. **Now with MCP (Model Context Protocol)**: register MCP servers, define agent profiles, and run goal-based workflows that compose tools from multiple MCP servers — with native LLM tool calling, RAG, multi-agent messaging, and full observability.

> **Production-Ready System**: 7 active agents · 3 LLM providers (Bedrock, OpenAI, Ollama) · Native tool calling (Bedrock Converse API + OpenAI) · RAG via ChromaDB · SQLite/PostgreSQL persistence · Docker deployment · 371 tests passing.

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

### MCP-Centric Runs

- **Agent Profiles** — defined in `config/agent_profiles.yaml` (role prompt + allowed MCP servers)
- **Planner Loop** — LLM picks tools iteratively until FINISH. Falls back to legacy orchestrator if no MCP tools are configured.
- **Checkpointing** — `checkpoint_step_index` saved to DB after each tool call. If the planner crashes mid-run, `resume_planner_loop` skips already-completed steps.
- **Runs API** — `POST /api/v1/run` → returns `run_id`. Poll `GET /api/v1/runs/{run_id}` for status, steps, and final answer; or stream progress via `GET /api/v1/runs/{run_id}/stream` (SSE).

See **[docs/ORCHESTRATION.md](docs/ORCHESTRATION.md)** for when to use `POST /run` vs `POST /orchestrate`, when the planner falls back to legacy agents, and what `agent_profile_id` controls.

**Run queue (optional):** Set `RUN_QUEUE_URL=redis://localhost:6379` to enqueue runs instead of running the planner in-process. Then start a worker with: `RUN_QUEUE_URL=redis://localhost:6379 arq app.worker.WorkerSettings`. Requires `pip install arq`. SSE (`GET /runs/{id}/stream`) still works because events are stored in the DB.

**Human-in-the-loop (HITL):** In `config/agent_profiles.yaml`, set `approval_required_tools: [tool_name, ...]` on a profile. When the planner is about to run one of those tools, the run status becomes `awaiting_approval`. Send `POST /api/v1/runs/{run_id}/approve` with `{"approved": true}` and optionally `modified_arguments: {...}` to override arguments. After approval, the tool runs and the planner resumes.

### MCP Transport Support

Both **stdio** and **HTTP SSE** transports are supported:

```yaml
# config/mcp_servers.yaml
mcp_servers:
  my_local_server:
    transport: stdio
    command: npx
    args: ["-y", "@my/mcp-server"]

  my_http_server:
    transport: sse
    url: http://localhost:8001/sse
    name: My HTTP MCP Server
```

---

## RAG (Retrieval-Augmented Generation)

Built-in semantic search powered by ChromaDB. Install the optional dependency with:

```bash
pip install chromadb>=0.4
```

If ChromaDB is not installed, RAG endpoints return `503 Service Unavailable` — the rest of the API is unaffected.

### RAG API

```http
# Index a document
POST /api/v1/rag/index
{
  "collection": "my_docs",
  "document_id": "doc-001",
  "text": "The nginx service is configured on port 443...",
  "metadata": {"source": "runbook", "team": "ops"}
}

# Semantic search
POST /api/v1/rag/search
{
  "collection": "my_docs",
  "query": "nginx configuration",
  "n_results": 5
}

# Delete a collection
DELETE /api/v1/rag/collection/{collection_name}

# List all collections
GET /api/v1/collections
```

---

## Multi-Agent Communication

Agents can send and receive messages via an in-process asyncio.Queue message bus:

```python
# From within any agent subclass:
await self.send_to_agent("target_agent_id", {"action": "diagnose", "host": "10.0.0.1"})

# In the target agent:
msg = await self.receive_from_agent(timeout=5.0)
```

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
| `DATABASE_URL` | `sqlite:////app/data/orchestrator.db` | SQLite (default) or PostgreSQL URL |
| `CORS_ORIGINS` | `https://yourdomain.com,...` | Comma-separated allowed origins |
| `WEBHOOK_SECRET` | | HMAC secret for Prometheus webhook (leave blank = unauthenticated) |
| `USE_LLM_ROUTING` | `false` | If `true`, `POST /orchestrate` uses LLM to pick agent |
| `RUN_QUEUE_URL` | *(empty)* | Redis URL for async run queue; start worker with `arq app.worker.WorkerSettings` |
| `OTEL_ENABLED` | `false` | Enable OpenTelemetry tracing (GenAI semantic conventions) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | *(empty)* | OTLP endpoint (e.g. `http://localhost:4318/v1/traces`) |

### Database (SQLite and PostgreSQL)

- **SQLite** (default): single-file DB; fine for local dev and single-instance. Set `DATABASE_URL=sqlite:///./orchestrator.db` for a file in the project folder. The app creates tables on startup via `init_db()`.
- **PostgreSQL**: supported for production and multi-instance. Set `DATABASE_URL=postgresql://user:pass@host:5432/dbname`. Create tables with **Alembic**: run `alembic upgrade head` before starting the app. Migrations live in `alembic/versions/`.

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

Server-Sent Events stream: `status`, `step`, `answer`, `token` (when `stream_tokens: true`), and `end` when the run finishes.

### Full Endpoint Reference

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/health` | Health check (DB, agents, LLM status) |
| `POST /api/v1/run` | Start a goal-based MCP run |
| `GET /api/v1/runs` | List runs (filter by status) |
| `GET /api/v1/runs/{run_id}` | Get run status, steps, answer |
| `GET /api/v1/runs/{run_id}/stream` | SSE stream of run progress |
| `POST /api/v1/runs/{run_id}/approve` | HITL: approve/reject pending tool call |
| `DELETE /api/v1/runs/{run_id}` | Cancel a run |
| `POST /api/v1/orchestrate` | Legacy multi-agent orchestration |
| `GET /api/v1/agents` | List all agents |
| `GET /api/v1/agents/{id}` | Agent details |
| `POST /api/v1/workflows` | Execute a YAML workflow |
| `GET /api/v1/metrics/costs` | LLM cost analytics |
| `GET /api/v1/agent-profiles` | List MCP agent profiles |
| `GET /api/v1/mcp/servers` | List connected MCP servers |
| `POST /api/v1/rag/index` | Index a document into ChromaDB |
| `POST /api/v1/rag/search` | Semantic search over a collection |
| `DELETE /api/v1/rag/collection/{name}` | Delete a ChromaDB collection |
| `GET /api/v1/rag/collections` | List all collections |
| `POST /api/v1/webhooks/prometheus` | Alertmanager webhook |
| `GET /metrics` | Prometheus scrape endpoint (auth required) |

**Prometheus scrape config** — add `X-API-Key` header to your Prometheus job:
```yaml
scrape_configs:
  - job_name: orchestrator
    static_configs:
      - targets: ["localhost:8000"]
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
# Workflow with conditional step — remediate only if diagnosis finds an issue
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

---

## Project Structure

```
ai-agent-orchestrator/
├── app/
│   ├── main.py                    # FastAPI entry point + lifespan
│   ├── api/v1/routes/
│   │   ├── runs.py                # Run lifecycle (create, poll, SSE, approve)
│   │   ├── rag.py                 # RAG endpoints (index, search, collections)
│   │   ├── orchestrator.py        # Legacy orchestrate endpoint
│   │   ├── agents.py              # Agent listing
│   │   ├── metrics.py             # Cost and metrics APIs
│   │   └── webhooks.py            # Prometheus Alertmanager webhook
│   ├── core/
│   │   ├── run_store.py           # Async DB wrappers for runs/events
│   │   ├── persistence.py         # Async DB wrappers for history/state
│   │   ├── agent_memory.py        # DB-backed agent session memory
│   │   ├── agent_bus.py           # Multi-agent asyncio.Queue message bus
│   │   ├── rag_manager.py         # ChromaDB RAG integration
│   │   ├── cost_tracker.py        # Token cost tracking (persisted to DB)
│   │   ├── workflow_executor.py   # DAG execution + conditional edges
│   │   ├── orchestrator.py        # Task routing
│   │   ├── sandbox.py             # Async tool timeout (asyncio.wait_for)
│   │   ├── auth.py                # API key auth (timing-safe)
│   │   ├── config.py              # Settings (pydantic-settings)
│   │   └── prompt_injection.py    # Input sanitization
│   ├── planner/loop.py            # MCP planner loop + HITL + checkpointing
│   ├── mcp/
│   │   ├── client_manager.py      # stdio + HTTP SSE MCP transport
│   │   └── config_loader.py       # Agent profile loader
│   ├── agents/
│   │   ├── base.py                # BaseAgent (tool use, memory, messaging)
│   │   └── ...                    # 7 agent implementations
│   ├── llm/
│   │   ├── tool_schema.py         # MCP → Bedrock/OpenAI tool schema converter
│   │   ├── bedrock.py             # Bedrock Converse API + native tool calling
│   │   ├── openai.py              # OpenAI tools parameter + native tool calling
│   │   ├── ollama.py              # Ollama (text fallback for tool calls)
│   │   └── base.py                # Abstract LLMProvider interface
│   ├── db/
│   │   ├── models.py              # Run, RunEvent, CostRecordDB, AgentState, ...
│   │   └── database.py            # SQLAlchemy engine + SessionLocal
│   ├── observability/
│   │   └── tracing.py             # OTel tracing + GenAI semantic conventions
│   ├── models/
│   │   └── workflow.py            # WorkflowStep (with condition field)
│   └── worker.py                  # arq worker for Redis run queue
├── config/
│   ├── agents.yaml
│   ├── mcp_servers.yaml           # stdio + SSE MCP server definitions
│   └── agent_profiles.yaml        # Agent profiles (role + allowed tools + HITL)
├── playbooks/                     # Ansible playbooks
├── scripts/
│   └── setup.sh                   # Interactive setup wizard
├── tests/
│   ├── unit/                      # 350+ unit tests
│   └── integration/               # 21 integration tests
├── .env.example                   # Environment template
├── Dockerfile                     # Node.js 20 + Python 3.11
├── docker-compose.yml             # With named volume for SQLite persistence
└── alembic/                       # DB migrations
```

---

## Security

This project has undergone a security audit. Key measures in place:

- **API key auth** — timing-safe comparison (`hmac.compare_digest`); server refuses to start if `REQUIRE_API_KEY=true` but `API_KEY` is not set
- **Rate limiting** — `slowapi` on all endpoints including `/metrics`
- **No shell injection** — all subprocess calls use argument lists, never `shell=True`
- **Input validation** — hostname, service name, playbook name, SQL keyword blocklist all validated via strict regex
- **Prompt injection filter** — all user-controlled strings sanitized before reaching the LLM
- **No exception leakage** — raw exception messages never exposed in HTTP responses
- **Security headers** — `X-Frame-Options`, `X-Content-Type-Options`, `X-XSS-Protection`, HSTS (HTTPS only), CSP
- **CORS** — narrowed to specific methods (`GET`, `POST`, `DELETE`) and headers (`X-API-Key`, `Content-Type`, `Accept`)
- **Swagger UI** — disabled in production (`DEBUG=false`)
- **Docker** — non-root `appuser` (UID 1000)

See [SECURITY.md](SECURITY.md) for full details.

---

## Observability

When `OTEL_ENABLED=true`, the orchestrator emits OpenTelemetry traces using the **GenAI semantic conventions**:

| Attribute | Value |
|-----------|-------|
| `gen_ai.system` | `anthropic` / `openai` / `ollama` |
| `gen_ai.request.model` | Model ID (e.g. `anthropic.claude-3-haiku-...`) |
| `gen_ai.usage.input_tokens` | Input token count |
| `gen_ai.usage.output_tokens` | Output token count |

Traces cover full run lifecycles (`trace_run`), individual planner steps (`trace_step`), and tool calls (`trace_tool_call`). Export to any OTLP-compatible backend (Jaeger, Grafana Tempo, Honeycomb, etc.) via `OTEL_EXPORTER_OTLP_ENDPOINT`.

---

## Testing

```bash
# Run full test suite (371 tests)
python -m pytest tests/ -v --tb=short --no-cov

# Run with coverage report
python -m pytest tests/ --cov=app --cov-report=term-missing

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
| ChromaDB RAG (local, in-memory) | **$0** |
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

**All features implemented and 371 tests passing.**

| Area | Status |
|------|--------|
| Agents | ✅ 7/7 (Network, System, Code Review, Log Analysis, Infrastructure, Osquery, Ansible) |
| LLM Providers | ✅ 3/3 — native tool calling on Bedrock + OpenAI; text fallback on Ollama |
| MCP transport | ✅ stdio + HTTP SSE |
| Planner + HITL | ✅ Complete — with crash-safe checkpointing |
| RAG (ChromaDB) | ✅ Optional — `/api/v1/rag/*` endpoints |
| Multi-agent messaging | ✅ asyncio.Queue message bus |
| Async DB layer | ✅ All DB calls non-blocking (`asyncio.to_thread`) |
| Conditional workflows | ✅ Python expression edges on workflow steps |
| Cost tracking | ✅ In-memory + DB-persisted (`CostRecordDB`) |
| Agent session memory | ✅ DB-backed per agent/run |
| OTel observability | ✅ GenAI semantic conventions |
| Security | ✅ Audited and hardened |
| Docker + persistence | ✅ Named volume for SQLite |
| Tests | ✅ 371 passing |

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
