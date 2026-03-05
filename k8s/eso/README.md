# External Secrets Operator — HashiCorp Vault (Self-Hosted)

Pulls all orchestrator secrets from an **internal** HashiCorp Vault instance so
that no secrets are stored in Kubernetes manifests or etcd in plain text.

## Prerequisites

1. [ESO installed](https://external-secrets.io/latest/introduction/getting-started/)
   in your cluster (one-time, cluster-wide):
   ```bash
   helm repo add external-secrets https://charts.external-secrets.io
   helm install external-secrets external-secrets/external-secrets \
     -n external-secrets-operator --create-namespace
   ```

2. HashiCorp Vault running internally (self-hosted — data never leaves company).

## One-Time Vault Setup

```bash
# 1. Enable Kubernetes auth backend
vault auth enable kubernetes

# 2. Configure it (run from inside the cluster or with cluster credentials)
vault write auth/kubernetes/config \
  kubernetes_host="https://kubernetes.default.svc"

# 3. Create a read-only policy for the orchestrator
vault policy write ai-agent-orchestrator - <<'EOF'
path "secret/data/ai-agent-orchestrator" {
  capabilities = ["read"]
}
EOF

# 4. Bind the K8s Service Account to the Vault role
vault write auth/kubernetes/role/ai-agent-orchestrator \
  bound_service_account_names=ai-agent-orchestrator \
  bound_service_account_namespaces=ai-agent-orchestrator \
  policies=ai-agent-orchestrator \
  ttl=1h

# 5. Store the secrets in Vault
vault kv put secret/ai-agent-orchestrator \
  api_key="orc_<generate>" \
  database_url="postgresql://user:pass@postgres-service:5432/orchestrator" \
  metrics_token="<generate>" \
  webhook_secret="<generate>" \
  aws_access_key_id="" \
  aws_secret_access_key=""
```

## Apply ESO Manifests

```bash
kubectl apply -f k8s/eso/secret-store.yaml
kubectl apply -f k8s/eso/external-secret.yaml

# Verify sync status
kubectl get externalsecret -n ai-agent-orchestrator
# NAME                    STORE                REFRESH INTERVAL   STATUS         READY
# orchestrator-secrets    vault-secret-store   1h                 SecretSynced   True

# Confirm the K8s Secret was created
kubectl get secret orchestrator-secrets -n ai-agent-orchestrator
```

## How It Works

```
Vault (internal) ──► ESO (cluster) ──► K8s Secret ──► App pods
     ↑                     │
     │                     └── Refreshes every 1h
     └── SA token auth (no static tokens)
```

- Secrets are refreshed every **1 hour** automatically.
- The app deployment reads `orchestrator-secrets` via `envFrom.secretRef` —
  no app code changes required.
- For emergency rotation: `vault kv patch secret/ai-agent-orchestrator api_key=<new>`,
  then force a refresh: `kubectl annotate externalsecret orchestrator-secrets \
  force-sync=$(date +%s) -n ai-agent-orchestrator --overwrite`.

## Using the Helm Chart Instead

If you prefer to manage ESO via the Helm chart:

```bash
helm upgrade ai-agent-orchestrator helm/ai-agent-orchestrator \
  --set externalSecrets.enabled=true \
  --set externalSecrets.vault.server=https://vault.internal:8200 \
  --set externalSecrets.vault.path=secret/ai-agent-orchestrator
```
