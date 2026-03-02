#!/usr/bin/env bash
# =============================================================================
# K8s deployment script for AI Agent Orchestrator
# Usage:  ./scripts/k8s-deploy.sh <image-tag>
# Example: ./scripts/k8s-deploy.sh v1.2.3
#
# What this script does (in order):
#   1. Validate prerequisites (kubectl, kustomize, image tag)
#   2. Ensure the namespace exists
#   3. Run the Alembic migration Job and wait for it to succeed
#   4. Apply the full manifest set (kustomize) with the new image tag
#   5. Wait for the rolling update to complete
#   6. Run a post-deploy health check
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration — edit these for your environment
# ---------------------------------------------------------------------------
NAMESPACE="ai-agent-orchestrator"
REGISTRY="ghcr.io"
# Repository owner (lowercase — GHCR requires lowercase)
OWNER="$(echo "${GITHUB_REPOSITORY_OWNER:-mentalvibez}" | tr '[:upper:]' '[:lower:]')"
IMAGE_BASE="${REGISTRY}/${OWNER}/ai-agent-orchestrator"
DEPLOY_TIMEOUT="300s"   # Maximum time to wait for rollout
MIGRATION_TIMEOUT="300s" # Maximum time to wait for migration Job

# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------
if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <image-tag>"
  echo "  image-tag: semver tag (e.g. v1.2.3) or 'latest'"
  exit 1
fi

IMAGE_TAG="$1"
IMAGE_FULL="${IMAGE_BASE}:${IMAGE_TAG}"

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------
for cmd in kubectl kustomize; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "ERROR: $cmd is not installed or not in PATH"
    exit 1
  fi
done

echo "=============================================="
echo "  AI Agent Orchestrator — K8s Deploy"
echo "  Image:     $IMAGE_FULL"
echo "  Namespace: $NAMESPACE"
echo "  Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "=============================================="
echo ""

# ---------------------------------------------------------------------------
# Step 1: Ensure namespace exists
# ---------------------------------------------------------------------------
echo "[1/5] Ensuring namespace '$NAMESPACE' exists..."
kubectl apply -f "$(dirname "$0")/../k8s/namespace.yaml"
echo "      Namespace OK."
echo ""

# ---------------------------------------------------------------------------
# Step 2: Apply ConfigMap and Secrets (idempotent)
#   Secrets must have been created manually from secret.yaml.example.
#   This step applies the ConfigMap; secrets are pre-existing.
# ---------------------------------------------------------------------------
echo "[2/5] Applying ConfigMap..."
kubectl apply -f "$(dirname "$0")/../k8s/configmap.yaml" -n "$NAMESPACE"
echo "      ConfigMap applied."
echo ""

# ---------------------------------------------------------------------------
# Step 3: Run Alembic migrations as a one-shot K8s Job
#   The Job uses the SAME image being deployed, ensuring migration code is
#   aligned with app code. The Job must succeed before pods are updated.
# ---------------------------------------------------------------------------
echo "[3/5] Running database migrations..."

# Delete any previous migration Job (Completed or Failed) to allow re-apply.
# K8s Jobs are immutable once created — we delete and recreate on each deploy.
MIGRATION_JOB_NAME="orchestrator-migration-${IMAGE_TAG//[^a-z0-9]/-}"
kubectl delete job "$MIGRATION_JOB_NAME" -n "$NAMESPACE" --ignore-not-found=true

# Substitute the image into the migration Job manifest
MIGRATION_MANIFEST=$(
  sed \
    -e "s|ghcr.io/OWNER/ai-agent-orchestrator:IMAGE_TAG|${IMAGE_FULL}|g" \
    -e "s|name: orchestrator-migration|name: ${MIGRATION_JOB_NAME}|g" \
    "$(dirname "$0")/../k8s/migration-job.yaml"
)
echo "$MIGRATION_MANIFEST" | kubectl apply -f - -n "$NAMESPACE"

echo "      Waiting up to $MIGRATION_TIMEOUT for migration to complete..."
if ! kubectl wait \
    --for=condition=complete \
    "job/${MIGRATION_JOB_NAME}" \
    -n "$NAMESPACE" \
    --timeout="$MIGRATION_TIMEOUT"; then
  echo ""
  echo "ERROR: Migration Job failed or timed out."
  echo "       Check logs with:"
  echo "       kubectl logs -l job-name=${MIGRATION_JOB_NAME} -n $NAMESPACE"
  exit 1
fi
echo "      Migrations complete."
echo ""

# ---------------------------------------------------------------------------
# Step 4: Apply the full manifest set with the new image tag
# ---------------------------------------------------------------------------
echo "[4/5] Applying K8s manifests (kustomize)..."

# Compute a config checksum so pod template changes when ConfigMap changes
CONFIG_CHECKSUM=$(kubectl get configmap orchestrator-config -n "$NAMESPACE" -o json 2>/dev/null \
  | sha256sum | cut -c1-16 || echo "unknown")

# Build kustomize output and substitute the image tag + checksum
kustomize build "$(dirname "$0")/../k8s/" \
  | sed \
      -e "s|ghcr.io/OWNER/ai-agent-orchestrator:latest|${IMAGE_FULL}|g" \
      -e "s|placeholder-updated-by-deploy-script|${CONFIG_CHECKSUM}|g" \
  | kubectl apply -f - -n "$NAMESPACE"

echo "      Manifests applied."
echo ""

# ---------------------------------------------------------------------------
# Step 5: Wait for the rolling update to complete
# ---------------------------------------------------------------------------
echo "[5/5] Waiting for deployment rollout (timeout: $DEPLOY_TIMEOUT)..."
if ! kubectl rollout status deployment/ai-agent-orchestrator \
    -n "$NAMESPACE" \
    --timeout="$DEPLOY_TIMEOUT"; then
  echo ""
  echo "ERROR: Deployment rollout did not complete within $DEPLOY_TIMEOUT."
  echo "       Rolling back to previous version..."
  kubectl rollout undo deployment/ai-agent-orchestrator -n "$NAMESPACE"
  echo "       Rollback initiated. Check pod events:"
  echo "       kubectl describe pods -l app=ai-agent-orchestrator -n $NAMESPACE"
  exit 1
fi

echo ""
echo "=============================================="
echo "  Deploy SUCCESSFUL"
echo "  Image:   $IMAGE_FULL"
echo "  Pods running:"
kubectl get pods -l app=ai-agent-orchestrator -n "$NAMESPACE" \
  --no-headers \
  -o custom-columns="NAME:.metadata.name,STATUS:.status.phase,READY:.status.conditions[-1].status"
echo ""
echo "  Post-deploy: check health endpoint on one pod:"
echo "  kubectl exec -it \$(kubectl get pod -l app=ai-agent-orchestrator -n $NAMESPACE -o name | head -1) \\"
echo "    -n $NAMESPACE -- curl -s localhost:8000/api/v1/health | python3 -m json.tool"
echo "=============================================="
