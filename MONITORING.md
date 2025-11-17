# Monitoring Guide

This guide explains how to monitor the AI Agent Orchestrator using Prometheus metrics and observability tools.

## Prometheus Metrics

The application exposes Prometheus metrics at `/metrics` endpoint.

### Available Metrics

#### HTTP Metrics
- `http_requests_total`: Total HTTP requests by method, endpoint, and status
- `http_request_duration_seconds`: HTTP request duration histogram

#### Agent Metrics
- `agent_executions_total`: Total agent executions by agent_id and status
- `agent_execution_duration_seconds`: Agent execution duration histogram

#### LLM Metrics
- `llm_calls_total`: Total LLM API calls by provider, model, and status
- `llm_tokens_total`: Total tokens used (input/output) by provider and model
- `llm_cost_total`: Total LLM cost in USD by provider and model

#### Workflow Metrics
- `workflow_executions_total`: Total workflow executions by workflow_id and status
- `workflow_execution_duration_seconds`: Workflow execution duration histogram

#### System Metrics
- `active_agents`: Number of active agents by agent_id
- `active_workflows`: Number of active workflows by workflow_id

### Example Queries

#### Request Rate
```promql
rate(http_requests_total[5m])
```

#### Error Rate
```promql
rate(http_requests_total{status="5xx"}[5m])
```

#### Average Request Duration
```promql
rate(http_request_duration_seconds_sum[5m]) / rate(http_request_duration_seconds_count[5m])
```

#### Agent Success Rate
```promql
rate(agent_executions_total{status="success"}[5m]) / rate(agent_executions_total[5m])
```

#### LLM Cost per Hour
```promql
rate(llm_cost_total[1h]) * 3600
```

#### Top Agents by Execution Count
```promql
topk(5, sum by (agent_id) (rate(agent_executions_total[5m])))
```

## Prometheus Setup

### 1. Install Prometheus

```bash
# Download Prometheus
wget https://github.com/prometheus/prometheus/releases/download/v2.45.0/prometheus-2.45.0.linux-amd64.tar.gz
tar xvfz prometheus-2.45.0.linux-amd64.tar.gz
cd prometheus-2.45.0.linux-amd64
```

### 2. Configure Prometheus

Create `prometheus.yml`:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'ai-agent-orchestrator'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
```

### 3. Start Prometheus

```bash
./prometheus --config.file=prometheus.yml
```

Access Prometheus UI at http://localhost:9090

## Grafana Setup

### 1. Install Grafana

```bash
# Ubuntu/Debian
sudo apt-get install -y software-properties-common
sudo add-apt-repository "deb https://packages.grafana.com/oss/deb stable main"
sudo apt-get update
sudo apt-get install grafana

# Start Grafana
sudo systemctl start grafana-server
sudo systemctl enable grafana-server
```

### 2. Add Prometheus Data Source

1. Open Grafana UI: http://localhost:3000
2. Login (default: admin/admin)
3. Add data source → Prometheus
4. URL: http://localhost:9090
5. Save & Test

### 3. Import Dashboard

Create a dashboard with panels for:
- Request rate and error rate
- Agent execution metrics
- LLM cost tracking
- System health

## Alerting Rules

### Example Alert Rules

Create `alerts.yml`:

```yaml
groups:
  - name: ai_agent_orchestrator
    interval: 30s
    rules:
      - alert: HighErrorRate
        expr: rate(http_requests_total{status="5xx"}[5m]) > 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High error rate detected"
          
      - alert: HighLLMCost
        expr: rate(llm_cost_total[1h]) * 3600 > 10
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "LLM cost exceeding threshold"
          
      - alert: AgentFailureRate
        expr: rate(agent_executions_total{status="failure"}[5m]) / rate(agent_executions_total[5m]) > 0.2
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High agent failure rate"
```

Add to Prometheus config:

```yaml
rule_files:
  - "alerts.yml"
```

## Logging

### Structured Logging

The application uses structured logging with request IDs for correlation.

### Log Levels

- `DEBUG`: Detailed debugging information
- `INFO`: General informational messages
- `WARNING`: Warning messages
- `ERROR`: Error messages
- `CRITICAL`: Critical errors

### Log Aggregation

For production, consider:
- **ELK Stack**: Elasticsearch, Logstash, Kibana
- **Loki**: Grafana's log aggregation system
- **CloudWatch**: AWS native logging (if on AWS)

## Health Checks

### Health Endpoint

The `/api/v1/health` endpoint provides:
- Application status (healthy/degraded/unhealthy)
- Version information
- Timestamp

### Monitoring Health

```bash
# Check health
curl http://localhost:8000/api/v1/health

# Response
{
  "status": "healthy",
  "version": "1.0.0",
  "timestamp": "2025-01-XX..."
}
```

## Cost Monitoring

### LLM Cost Tracking

Use the cost metrics API:

```bash
curl -H "X-API-Key: your-key" \
  http://localhost:8000/api/v1/metrics/costs?days=7
```

### Prometheus Query for Cost

```promql
# Total cost in last 24 hours
sum(increase(llm_cost_total[24h]))
```

## Best Practices

1. **Set up alerts** for critical metrics
2. **Monitor cost trends** to avoid surprises
3. **Track error rates** and investigate spikes
4. **Monitor agent performance** and optimize slow agents
5. **Set up dashboards** for key metrics
6. **Regular review** of metrics and logs
7. **Capacity planning** based on usage trends

## Troubleshooting

### Metrics Not Appearing

1. Check `/metrics` endpoint is accessible
2. Verify Prometheus can scrape the endpoint
3. Check Prometheus targets: http://localhost:9090/targets

### High Memory Usage

Monitor with:
```promql
process_resident_memory_bytes
```

### Slow Requests

Investigate with:
```promql
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))
```

