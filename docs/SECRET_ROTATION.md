# Secret Rotation Guide

Secrets must be rotated on a regular schedule to limit the blast radius of any credential exposure. This document defines the rotation procedure for every credential used by the AI Agent Orchestrator.

**Rotation schedule summary:**

| Secret | Rotation Frequency | Owner |
|--------|-------------------|-------|
| `API_KEY` (bootstrap) | 90 days | Ops |
| DB-backed API keys | 90 days or on demand | Ops / consumers |
| `METRICS_TOKEN` | 90 days | Ops |
| `WEBHOOK_SECRET` | 90 days | Ops |
| AWS IAM credentials | 90 days (or use IAM roles) | Ops / Cloud |
| Database password | 180 days | Ops / DBA |
| SMTP credentials | 180 days | Ops |
| PagerDuty service key | 180 days | Ops |

---

## 1. API Key Rotation (bootstrap `API_KEY`)

The bootstrap key is configured via the `API_KEY` environment variable. It is the permanent admin key used before the DB-backed key system is populated.

**Rotation procedure:**

```bash
# Step 1: Generate a new strong key
NEW_KEY=$(openssl rand -hex 32)
echo "New key: $NEW_KEY"  # Store this in your password manager immediately

# Step 2: Update the K8s Secret (zero-downtime — old key still works until pods restart)
kubectl patch secret orchestrator-secrets -n ai-agent-orchestrator \
  --patch "{\"stringData\":{\"API_KEY\":\"$NEW_KEY\"}}"

# Step 3: Notify all API consumers of the new key and schedule a cutover window

# Step 4: Trigger a rolling restart to pick up the new secret
kubectl rollout restart deployment/ai-agent-orchestrator -n ai-agent-orchestrator

# Step 5: Verify the new key works
curl -H "X-API-Key: $NEW_KEY" https://api.yourdomain.com/api/v1/health

# Step 6: Confirm the old key no longer works (optional — it won't after restart)
```

---

## 2. DB-Backed API Key Rotation

DB-backed keys are issued per consumer (team/service) via `POST /api/v1/admin/keys`. They support zero-downtime rotation because the old key can remain active until all clients have switched.

**Rotation procedure (zero-downtime):**

```bash
ADMIN_KEY="<your-admin-api-key>"
BASE_URL="https://api.yourdomain.com"
CONSUMER_NAME="my-service"

# Step 1: Create a new key for the consumer
NEW=$(curl -s -X POST "$BASE_URL/api/v1/admin/keys" \
  -H "X-API-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"$CONSUMER_NAME-$(date +%Y%m)\", \"role\": \"operator\"}")

echo "New key ID: $(echo $NEW | jq -r .key_id)"
echo "New raw key: $(echo $NEW | jq -r .raw_key)"
# ⚠ Copy the raw_key — it is shown only once

# Step 2: Distribute the new key to the consumer (via your secrets manager)

# Step 3: After consumer has deployed the new key, list keys to find the old one
curl -s -H "X-API-Key: $ADMIN_KEY" "$BASE_URL/api/v1/admin/keys" | jq '.[] | {key_id, name, is_active, last_used_at}'

# Step 4: Revoke the old key
OLD_KEY_ID="<old-key-id>"
curl -s -X DELETE "$BASE_URL/api/v1/admin/keys/$OLD_KEY_ID" \
  -H "X-API-Key: $ADMIN_KEY"

# Step 5: Verify old key is revoked
curl -H "X-API-Key: <old-raw-key>" "$BASE_URL/api/v1/health"
# Should return 401/503
```

---

## 3. METRICS_TOKEN Rotation

The `METRICS_TOKEN` authenticates Prometheus scrape requests to `/metrics`.

```bash
# Step 1: Generate new token
NEW_TOKEN=$(openssl rand -hex 32)

# Step 2: Update K8s Secret
kubectl patch secret orchestrator-secrets -n ai-agent-orchestrator \
  --patch "{\"stringData\":{\"METRICS_TOKEN\":\"$NEW_TOKEN\"}}"

# Step 3: Update Prometheus scrape config to use the new bearer token
# In your prometheus.yml or Kubernetes ServiceMonitor:
#   bearer_token: <new_token>
# Apply the Prometheus config and reload:
curl -X POST http://prometheus:9090/-/reload

# Step 4: Restart the orchestrator to pick up the new secret
kubectl rollout restart deployment/ai-agent-orchestrator -n ai-agent-orchestrator

# Step 5: Verify Prometheus is scraping successfully
# Check Prometheus UI → Status → Targets → ai-agent-orchestrator (should be UP)
```

---

## 4. WEBHOOK_SECRET Rotation

The `WEBHOOK_SECRET` is used to validate HMAC-SHA256 signatures on incoming Prometheus Alertmanager webhooks.

```bash
# Step 1: Generate new secret
NEW_SECRET=$(openssl rand -hex 32)

# Step 2: Update K8s Secret
kubectl patch secret orchestrator-secrets -n ai-agent-orchestrator \
  --patch "{\"stringData\":{\"WEBHOOK_SECRET\":\"$NEW_SECRET\"}}"

# Step 3: Update Alertmanager config with new secret (in the webhook receiver URL or header)
# Then reload Alertmanager:
curl -X POST http://alertmanager:9093/-/reload

# Step 4: Restart the orchestrator
kubectl rollout restart deployment/ai-agent-orchestrator -n ai-agent-orchestrator
```

---

## 5. AWS Credentials Rotation

**Preferred approach: Use IAM roles (no static credentials needed)**

If using EKS, associate an IAM OIDC provider with the cluster and use a Service Account with IAM annotations — no `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` needed.

**If using static credentials:**

```bash
# Step 1: Create new IAM access key in AWS Console or CLI
aws iam create-access-key --user-name ai-agent-orchestrator-bedrock

# Step 2: Update K8s Secret with new credentials
kubectl patch secret orchestrator-secrets -n ai-agent-orchestrator \
  --patch "{\"stringData\":{
    \"AWS_ACCESS_KEY_ID\":\"<new-key-id>\",
    \"AWS_SECRET_ACCESS_KEY\":\"<new-secret>\"
  }}"

# Step 3: Rolling restart to pick up new credentials
kubectl rollout restart deployment/ai-agent-orchestrator -n ai-agent-orchestrator

# Step 4: Verify Bedrock access
curl -H "X-API-Key: $API_KEY" https://api.yourdomain.com/api/v1/health

# Step 5: Deactivate then delete the old IAM access key
aws iam update-access-key --access-key-id <old-key-id> --status Inactive --user-name ai-agent-orchestrator-bedrock
# Wait 48h to ensure no usage, then:
aws iam delete-access-key --access-key-id <old-key-id> --user-name ai-agent-orchestrator-bedrock
```

---

## 6. Database Password Rotation

Database password rotation requires a coordinated update of both the DB server and the connection string.

```bash
# Step 1: Generate new password
NEW_PG_PASS=$(openssl rand -base64 32)

# Step 2: Update the password IN PostgreSQL first (while old connection string still works)
kubectl exec -n ai-agent-orchestrator statefulset/postgres -- \
  psql -U orchestrator -c "ALTER USER orchestrator PASSWORD '$NEW_PG_PASS';"

# Step 3: Update K8s Secrets with new password
# postgres-credentials secret:
kubectl patch secret postgres-credentials -n ai-agent-orchestrator \
  --patch "{\"stringData\":{\"POSTGRES_PASSWORD\":\"$NEW_PG_PASS\"}}"

# orchestrator-secrets (DATABASE_URL):
NEW_DB_URL="postgresql://orchestrator:${NEW_PG_PASS}@postgres-service:5432/orchestrator"
kubectl patch secret orchestrator-secrets -n ai-agent-orchestrator \
  --patch "{\"stringData\":{\"DATABASE_URL\":\"$NEW_DB_URL\"}}"

# Step 4: Rolling restart — new pods use new password; old pods use old (now-changed) password
# Note: brief reconnection errors are expected during rollout
kubectl rollout restart deployment/ai-agent-orchestrator -n ai-agent-orchestrator
kubectl rollout status deployment/ai-agent-orchestrator -n ai-agent-orchestrator

# Step 5: Verify
curl -H "X-API-Key: $API_KEY" https://api.yourdomain.com/api/v1/health
```

---

## 7. Emergency Revocation

When a credential is suspected compromised:

```bash
# 1. Immediately revoke DB-backed key (if a named key)
curl -X DELETE "https://api.yourdomain.com/api/v1/admin/keys/<key-id>" \
  -H "X-API-Key: $ADMIN_KEY"

# 2. If the bootstrap API_KEY is compromised — rotate immediately (see Section 1)
# The service will reject the old key after the rolling restart completes (~45s)

# 3. If AWS credentials are compromised — deactivate immediately
aws iam update-access-key --access-key-id <key-id> --status Inactive \
  --user-name ai-agent-orchestrator-bedrock

# 4. Audit logs for usage of the compromised credential
kubectl logs -n ai-agent-orchestrator -l app=ai-agent-orchestrator --since=720h \
  | jq 'select(.message | test("authenticated")) | {timestamp, api_key_id, endpoint, ip}'

# 5. Document the incident and trigger post-mortem (see DISASTER_RECOVERY.md)
```

---

## Automation Recommendation

For production, consider automating rotation with AWS Secrets Manager:

```bash
# Store secrets in Secrets Manager
aws secretsmanager create-secret --name ai-agent-orchestrator/api-key \
  --secret-string "$(openssl rand -hex 32)"

# Configure automatic rotation (Lambda-backed, 90-day schedule)
aws secretsmanager rotate-secret --secret-id ai-agent-orchestrator/api-key \
  --rotation-rules AutomaticallyAfterDays=90

# Use the External Secrets Operator to sync to K8s Secrets automatically:
# https://external-secrets.io/
```
