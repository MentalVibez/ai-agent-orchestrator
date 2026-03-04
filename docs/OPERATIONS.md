# Operations Guide

Operational reference for the AI Agent Orchestrator. Covers common failure modes, diagnostic commands, and remediation steps.

---

## Table of Contents

1. [Health Check Returns 503](#1-health-check-returns-503)
2. [OOM / Pod Killed](#2-oom--pod-killed)
3. [MCP Server Timeout or Crash](#3-mcp-server-timeout-or-crash)
4. [Database Connection Pool Exhaustion](#4-database-connection-pool-exhaustion)
5. [LLM Provider Failover](#5-llm-provider-failover)
6. [Log Querying Patterns](#6-log-querying-patterns)
7. [Useful kubectl Commands](#7-useful-kubectl-commands)
8. [Prometheus Alert Remediation Map](#8-prometheus-alert-remediation-map)

---

## 1. Health Check Returns 503

**Symptom:** `GET /api/v1/health` → 503; pods marked NotReady; traffic stops

### Diagnostic Checklist

```bash
# 1. Check pod status
kubectl get pods -n ai-agent-orchestrator

# 2. Read recent pod logs (last 200 lines)
kubectl logs -n ai-agent-orchestrator -l app=ai-agent-orchestrator --tail=200

# 3. Verify DB connectivity
kubectl exec -n ai-agent-orchestrator deploy/ai-agent-orchestrator -- \
  python -c "from app.db.database import engine; print(engine.execute('SELECT 1').scalar())"

# 4. Check if API_KEY is configured (empty key → 503)
kubectl get secret orchestrator-secrets -n ai-agent-orchestrator -o jsonpath='{.data.API_KEY}' | base64 -d | wc -c
# Should be > 0

# 5. Check REQUIRE_API_KEY setting
kubectl get configmap orchestrator-config -n ai-agent-orchestrator -o jsonpath='{.data.REQUIRE_API_KEY}'
```

**Common causes:**
- `API_KEY=""` with `REQUIRE_API_KEY=true` → auth misconfiguration → returns 503
- DB migrations failed on startup → `alembic upgrade head` error in logs
- PostgreSQL unreachable → wait-for-postgres init container should block startup

**Fix:**
```bash
# Update secret with a valid API key
kubectl create secret generic orchestrator-secrets \
  --from-literal=API_KEY=$(openssl rand -hex 32) \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/ai-agent-orchestrator -n ai-agent-orchestrator
```

---

## 2. OOM / Pod Killed

**Symptom:** Pod restarts with `OOMKilled` reason; `kubectl describe pod` shows `Exit Code: 137`

```bash
# Identify OOM'd pod
kubectl get pods -n ai-agent-orchestrator -o wide

# Check events for OOMKilled
kubectl describe pod <pod-name> -n ai-agent-orchestrator | grep -A5 "OOMKilled\|Killed"

# Current memory usage across all pods
kubectl top pods -n ai-agent-orchestrator
```

**Tuning options:**

| Cause | Fix |
|-------|-----|
| LLM response with very large context | Reduce `LLM_MAX_TOKENS` in ConfigMap |
| Many concurrent runs | Scale horizontally (increase HPA maxReplicas) or reduce `RATE_LIMIT_PER_MINUTE` |
| ChromaDB embedding cache | Mount PVC for Chroma instead of in-memory |
| Memory limit too low | Increase limit in `k8s/deployment.yaml` (default: 2Gi) |

```bash
# Temporarily increase memory limit (edit deployment)
kubectl patch deployment ai-agent-orchestrator -n ai-agent-orchestrator \
  --patch '{"spec":{"template":{"spec":{"containers":[{"name":"orchestrator","resources":{"limits":{"memory":"4Gi"}}}]}}}}'
```

---

## 3. MCP Server Timeout or Crash

**Symptom:** Runs hang at a tool call step; logs show `MCP server process exited` or `timeout`

### stdio servers (default)

Each run spawns an MCP server subprocess (e.g., `npx @modelcontextprotocol/server-filesystem`). The process lives for the duration of the run.

```bash
# See MCP-related log lines
kubectl logs -n ai-agent-orchestrator -l app=ai-agent-orchestrator | grep -i "mcp\|stdio\|subprocess"

# Check config/mcp_servers.yaml for correct command
kubectl exec -n ai-agent-orchestrator deploy/ai-agent-orchestrator -- \
  cat /app/config/mcp_servers.yaml
```

**Common causes:**

| Issue | Symptom | Fix |
|-------|---------|-----|
| `npx` not found | `command not found: npx` | Verify Node.js installed in image |
| `uvx` not found | `command not found: uvx` | Verify `uv` installed in image |
| Server crashes on bad input | `process exited with code 1` | Check tool arguments in run logs |
| Network timeout (SSE transport) | Connection reset | Check `mcp_servers.yaml` `url` field |

### SSE (HTTP) servers

```bash
# Test SSE server reachability from inside the pod
kubectl exec -n ai-agent-orchestrator deploy/ai-agent-orchestrator -- \
  curl -v http://<mcp-server-host>:<port>/sse
```

---

## 4. Database Connection Pool Exhaustion

**Symptom:** `sqlalchemy.exc.TimeoutError: QueuePool limit of size X overflow Y reached` in logs

```bash
# Check current DB connections
kubectl exec -n ai-agent-orchestrator statefulset/postgres -- \
  psql -U orchestrator -c "SELECT count(*), state FROM pg_stat_activity GROUP BY state;"
```

**Tuning options:**

```bash
# Increase pool size via DATABASE_URL options
# In k8s/secret.yaml, append pool params:
DATABASE_URL=postgresql://orchestrator:pass@postgres-service:5432/orchestrator?pool_size=20&max_overflow=10
```

If the orchestrator is spawning too many concurrent runs, reduce worker concurrency or add Redis queue (`RUN_QUEUE_URL`) to control throughput.

---

## 5. LLM Provider Failover

**Symptom:** `LLMCallFailureSpike` alert; runs failing with `LLMProviderError`

```bash
# Quick check — which provider is failing?
kubectl logs -n ai-agent-orchestrator -l app=ai-agent-orchestrator | grep "LLMProviderError\|provider.*error"

# Switch to backup provider (e.g., openai)
kubectl patch configmap orchestrator-config -n ai-agent-orchestrator \
  --patch '{"data":{"LLM_PROVIDER":"openai"}}'

# Roll out the change
kubectl rollout restart deployment/ai-agent-orchestrator -n ai-agent-orchestrator

# Verify new provider in logs
kubectl logs -n ai-agent-orchestrator -l app=ai-agent-orchestrator --tail=50 | grep "provider"
```

**Provider status pages:**
- AWS Bedrock: https://health.aws.amazon.com/
- OpenAI: https://status.openai.com/
- Ollama: local process — check `systemctl status ollama` on the host

---

## 6. Log Querying Patterns

All logs are structured JSON when `LOG_FORMAT=json` (production default). Each line includes:

```json
{
  "timestamp": "2026-03-03T12:00:00.000Z",
  "level": "INFO",
  "logger": "app.api.v1.routes.runs",
  "message": "Run started",
  "run_id": "abc123",
  "request_id": "req-456",
  "provider": "bedrock",
  "tokens_in": 512,
  "tokens_out": 256,
  "cost_usd": 0.0003
}
```

### Useful queries (via `kubectl logs | jq`)

```bash
# All errors in last 10 minutes
kubectl logs -n ai-agent-orchestrator -l app=ai-agent-orchestrator --since=10m \
  | jq 'select(.level == "ERROR")'

# Slow requests (> 5s)
kubectl logs -n ai-agent-orchestrator -l app=ai-agent-orchestrator --since=1h \
  | jq 'select(.duration_ms > 5000) | {path, duration_ms, run_id}'

# LLM cost by run
kubectl logs -n ai-agent-orchestrator -l app=ai-agent-orchestrator --since=1h \
  | jq 'select(.cost_usd != null) | {run_id, cost_usd, provider}'

# Rate limit hits
kubectl logs -n ai-agent-orchestrator -l app=ai-agent-orchestrator --since=1h \
  | jq 'select(.message | test("Rate limit"))'
```

### Log aggregation (if forwarded to CloudWatch / Loki)

```
# CloudWatch Insights query for error rate
fields @timestamp, level, message, run_id
| filter level = "ERROR"
| stats count(*) as errors by bin(5m)

# Loki / Grafana query
{app="ai-agent-orchestrator"} | json | level="ERROR"
```

---

## 7. Useful kubectl Commands

```bash
# All pods with status
kubectl get pods -n ai-agent-orchestrator -o wide

# Tail logs from all API pods simultaneously
kubectl logs -n ai-agent-orchestrator -l app=ai-agent-orchestrator -f --max-log-requests=10

# Describe a specific pod (events, resource usage, probes)
kubectl describe pod <pod-name> -n ai-agent-orchestrator

# Resource usage (requires metrics-server)
kubectl top pods -n ai-agent-orchestrator
kubectl top nodes

# Check HPA status (current vs desired replicas)
kubectl get hpa -n ai-agent-orchestrator

# Force immediate scale-up (temporarily override HPA)
kubectl patch hpa ai-agent-orchestrator-hpa -n ai-agent-orchestrator \
  --patch '{"spec":{"minReplicas":5}}'

# List all secrets (without values)
kubectl get secrets -n ai-agent-orchestrator

# Check network policy
kubectl describe networkpolicy -n ai-agent-orchestrator

# Execute a shell in a running pod (debugging)
kubectl exec -it -n ai-agent-orchestrator deploy/ai-agent-orchestrator -- /bin/bash

# Run a DB migration manually
kubectl apply -f k8s/migration-job.yaml -n ai-agent-orchestrator
kubectl wait --for=condition=complete job/orchestrator-migration -n ai-agent-orchestrator --timeout=300s
kubectl logs -n ai-agent-orchestrator -l component=migration
```

---

## 8. Prometheus Alert Remediation Map

| Alert | Severity | First Response | Escalation |
|-------|----------|---------------|------------|
| `ServiceDown` | critical | Check pod status; check DB; restart deployment | Page on-call if > 5 min |
| `HealthCheckDegraded` | warning | Check logs for repeated 5xx; check DB pool | Investigate root cause |
| `HighErrorRate` | critical | Check logs for error pattern; consider rollback | Page on-call |
| `ElevatedErrorRate` | warning | Monitor trend; check recent deployment | Self-assign and investigate |
| `OrchestrateLatencyHigh` | warning | Check LLM provider latency; check DB queries | Tune or switch provider |
| `RunStartLatencyHigh` | warning | Check queue depth (Redis if enabled); check DB | Add replicas if sustained |
| `LLMCallFailureSpike` | critical | Check provider status page; switch provider | Notify LLM provider support |
| `LLMCostSpike` | warning | Check which team/key is consuming; add per-key limits | Finance team alert |
| `RateLimitSustained` | warning | Check if legitimate traffic surge or abuse | Block offending IP/key |

### Silencing an alert (during maintenance)

```bash
# Via Alertmanager UI: http://localhost:9093/#/silences (or your alertmanager URL)
# Or via API:
curl -X POST http://alertmanager:9093/api/v2/silences \
  -H 'Content-Type: application/json' \
  -d '{
    "matchers": [{"name": "alertname", "value": "ServiceDown", "isRegex": false}],
    "startsAt": "2026-03-03T12:00:00Z",
    "endsAt": "2026-03-03T14:00:00Z",
    "createdBy": "ops-engineer",
    "comment": "Planned maintenance window"
  }'
```
