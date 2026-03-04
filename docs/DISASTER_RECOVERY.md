# Disaster Recovery Runbook

## Overview

This document describes recovery procedures for the AI Agent Orchestrator in the event of outages, data loss, or infrastructure failures.

**Maintained by:** Operations team
**Review cadence:** Quarterly (or after any DR drill)
**Last reviewed:** 2026-03-03

---

## SLA Targets

| Target | Value |
|--------|-------|
| **RTO** (Recovery Time Objective) | 1 hour for P0; 4 hours for P1 |
| **RPO** (Recovery Point Objective) | 24 hours (daily backups at 01:00 UTC) |
| **Uptime SLA** | 99.5% monthly |

---

## Incident Severity Levels

| Level | Description | Example | Response Time |
|-------|-------------|---------|---------------|
| **P0** | Total service unavailability | All pods crash-looping; DB unreachable | Immediate, 24/7 |
| **P1** | Significant degradation | Error rate > 10%; LLM provider down | Within 1 hour |
| **P2** | Minor degradation | Elevated latency; single pod unhealthy | Within 4 hours |
| **P3** | Non-urgent | Log errors; metrics gap | Next business day |

---

## Runbooks by Scenario

### 1. Application Pods All Down (P0)

**Symptoms:** `kubectl get pods -n ai-agent-orchestrator` shows all pods in `CrashLoopBackOff` or `Error`

**Steps:**
```bash
# 1. Check pod logs for root cause
kubectl logs -n ai-agent-orchestrator -l app=ai-agent-orchestrator --previous

# 2. Check events for scheduling/config issues
kubectl get events -n ai-agent-orchestrator --sort-by='.lastTimestamp'

# 3. Verify secrets are present
kubectl get secret orchestrator-secrets -n ai-agent-orchestrator

# 4. Verify DB connectivity from a debug pod
kubectl run debug --rm -it --image=postgres:16-alpine -n ai-agent-orchestrator \
  --env="PGPASSWORD=<password>" -- psql -h postgres-service -U orchestrator -c '\l'

# 5. If config issue, update ConfigMap and force rollout
kubectl apply -f k8s/configmap.yaml
kubectl rollout restart deployment/ai-agent-orchestrator -n ai-agent-orchestrator

# 6. Monitor rollout
kubectl rollout status deployment/ai-agent-orchestrator -n ai-agent-orchestrator
```

---

### 2. Rollback to Previous Version (P0/P1)

**When:** New deployment introduced a regression or crash

```bash
# Immediate rollback to previous ReplicaSet
kubectl rollout undo deployment/ai-agent-orchestrator -n ai-agent-orchestrator

# Verify rollback
kubectl rollout status deployment/ai-agent-orchestrator -n ai-agent-orchestrator

# Check which image is now running
kubectl get pods -n ai-agent-orchestrator -o jsonpath='{.items[0].spec.containers[0].image}'

# If the previous version also has DB schema issues, run downgrade:
# (Apply the previous migration image as a Job first)
# alembic downgrade -1
```

---

### 3. PostgreSQL Pod Failure (P0/P1)

**Symptoms:** API pods show DB connection errors; `kubectl get pods -n ai-agent-orchestrator | grep postgres` shows non-Running state

```bash
# Check postgres pod
kubectl describe pod -n ai-agent-orchestrator postgres-0

# Check postgres logs
kubectl logs -n ai-agent-orchestrator postgres-0

# Check PVC is bound
kubectl get pvc -n ai-agent-orchestrator

# If pod is in Pending (PVC issue), describe the PVC
kubectl describe pvc postgres-data-postgres-0 -n ai-agent-orchestrator

# Restart postgres StatefulSet
kubectl rollout restart statefulset/postgres -n ai-agent-orchestrator
kubectl rollout status statefulset/postgres -n ai-agent-orchestrator

# If PVC is lost — trigger DB restore from backup (see Section 4 below)
```

---

### 4. Database Restore from Backup (P0 — Data Loss)

**Warning: This is destructive. It drops and recreates the database.**

```bash
# Step 1: Locate the most recent backup
aws s3 ls s3://<BACKUP_BUCKET>/db-backups/ --recursive | sort | tail -5

# Step 2: Scale down the API to prevent writes during restore
kubectl scale deployment/ai-agent-orchestrator -n ai-agent-orchestrator --replicas=0

# Step 3: Port-forward to postgres for the restore script
kubectl port-forward -n ai-agent-orchestrator svc/postgres-service 5432:5432 &

# Step 4: Set DATABASE_URL and run restore
export DATABASE_URL="postgresql://orchestrator:<password>@localhost:5432/orchestrator"
export S3_BUCKET="<BACKUP_BUCKET>"
export CONFIRM=yes
./scripts/restore.sh s3://<BACKUP_BUCKET>/db-backups/<filename>.dump.gz

# Step 5: Verify tables are present
psql "$DATABASE_URL" -c "\dt"

# Step 6: Scale the API back up
kubectl scale deployment/ai-agent-orchestrator -n ai-agent-orchestrator --replicas=3
kubectl rollout status deployment/ai-agent-orchestrator -n ai-agent-orchestrator

# Step 7: Verify health
curl -H "X-API-Key: $API_KEY" https://api.yourdomain.com/api/v1/health
```

---

### 5. LLM Provider Outage (P1)

**Symptoms:** `LLMCallFailureSpike` alert firing; runs stalling with LLM errors

```bash
# 1. Check which provider is failing (Prometheus query)
# sum(rate(llm_calls_total{status="error"}[5m])) by (provider)

# 2. Switch to a backup provider via ConfigMap
kubectl patch configmap orchestrator-config -n ai-agent-orchestrator \
  --patch '{"data": {"LLM_PROVIDER": "openai"}}'

# 3. Force pod restart to pick up new config
kubectl rollout restart deployment/ai-agent-orchestrator -n ai-agent-orchestrator

# 4. If all providers down, circuit breaker will reject calls after FAIL_MAX failures.
#    Runs will fail with a clear error message rather than hanging.
#    Notify users, monitor for provider recovery.
```

---

### 6. Kubernetes Node Failure (P1)

**Symptoms:** Pods rescheduled; some briefly unavailable; PDB may trigger

```bash
# Check node status
kubectl get nodes

# Check if PDB is blocking evictions
kubectl get pdb -n ai-agent-orchestrator

# If a node is NotReady for > 5 minutes, manually cordon and drain
kubectl cordon <node-name>
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data

# Pods will reschedule on healthy nodes. With 3 replicas and PDB minAvailable=2,
# service remains available during single-node failures.
```

---

### 7. Full Cluster Loss (P0 — DR Scenario)

**When:** Entire K8s cluster is unrecoverable (AZ outage, accidental deletion, etc.)

```bash
# Step 1: Provision a new cluster (EKS/GKE/AKS CLI commands — cluster-specific)
# Step 2: Apply namespace
kubectl apply -f k8s/namespace.yaml

# Step 3: Create secrets (from secure storage — never from git)
kubectl apply -f k8s/postgres-secret.yaml -n ai-agent-orchestrator
kubectl apply -f k8s/secret.yaml -n ai-agent-orchestrator

# Step 4: Apply all K8s manifests
kubectl apply -k k8s/

# Step 5: Run migration job before starting API
kubectl apply -f k8s/migration-job.yaml -n ai-agent-orchestrator
kubectl wait --for=condition=complete job/orchestrator-migration -n ai-agent-orchestrator --timeout=300s

# Step 6: If data recovery needed, restore from backup (see Section 4)
# Note: PostgreSQL PVC will be empty on a new cluster — restore is required
#       unless this was a stateless (all data in DB) deployment.

# Step 7: Verify service
kubectl get pods -n ai-agent-orchestrator
kubectl get svc -n ai-agent-orchestrator
curl https://<new-cluster-ip>/api/v1/health
```

---

## Backup Schedule

| Backup | Frequency | Retention | Storage |
|--------|-----------|-----------|---------|
| PostgreSQL dump | Daily 01:00 UTC | 7 days local, 30 days S3 | `s3://<BACKUP_BUCKET>/db-backups/` |
| K8s manifests | On every commit (git) | Permanent | GitHub |
| Secrets | Manual, encrypted | Permanent | AWS Secrets Manager / Vault |

**Setup daily backup cron (in K8s):**
```bash
# Run scripts/backup.sh as a CronJob — add a CronJob manifest if needed:
# Schedule: "0 1 * * *"
# Image: same orchestrator image (has pg_dump via postgres client)
# Env: DATABASE_URL, S3_BUCKET, RETENTION_DAYS from Secret/ConfigMap
```

---

## DR Drill Procedure (Quarterly)

Run this checklist every quarter to verify recovery procedures still work:

1. [ ] Trigger a manual database backup: `S3_BUCKET=<bucket> ./scripts/backup.sh`
2. [ ] Restore to a **staging** environment: `./scripts/restore.sh <backup-file>`
3. [ ] Verify staging API health after restore: `curl staging-api/api/v1/health`
4. [ ] Test rollback: deploy to staging, then `kubectl rollout undo`
5. [ ] Test LLM provider failover: set `LLM_PROVIDER=openai` in staging ConfigMap
6. [ ] Document any gaps found → update this runbook
7. [ ] Update "Last reviewed" date at the top of this file

---

## Post-Incident Checklist

After any P0/P1 incident:

- [ ] Incident timeline documented (start, detection, mitigation, resolution)
- [ ] Root cause identified
- [ ] Prometheus alert fired as expected (or gap noted)
- [ ] PagerDuty escalation worked correctly
- [ ] Corrective actions identified with owners and due dates
- [ ] This runbook updated if procedure was incorrect or missing
- [ ] README updated if architecture changed
- [ ] Post-mortem shared with stakeholders within 48 hours (P0) or 5 days (P1)

---

## Key Contacts

| Role | Contact |
|------|---------|
| On-call engineer | PagerDuty escalation → `ai-agent-orchestrator` service |
| Database admin | ops@yourdomain.com |
| Finance (cost alerts) | finance@yourdomain.com |
| LLM provider support | AWS Support / OpenAI status page |
