#!/usr/bin/env bash
# =============================================================================
# scripts/set-branch-protection.sh
#
# Apply baseline branch protection for main via GitHub API.
#
# Requirements:
#   - gh CLI installed and authenticated
#   - token with repo:admin permissions (or equivalent)
#
# Usage:
#   GH_REPO=owner/repo ./scripts/set-branch-protection.sh
#   GH_REPO=owner/repo CHECKS="Tests / lint,Tests / test,Staging Reliability Gate / reliability-gate" ./scripts/set-branch-protection.sh
# =============================================================================
set -euo pipefail

if ! command -v gh >/dev/null 2>&1; then
  echo "ERROR: gh CLI is required." >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "ERROR: gh auth is not configured. Run: gh auth login" >&2
  exit 1
fi

GH_REPO="${GH_REPO:-}"
if [[ -z "${GH_REPO}" ]]; then
  GH_REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
fi

BRANCH="${BRANCH:-main}"

# Comma-separated check contexts; tune for your repo's exact check names.
DEFAULT_CHECKS="Tests / lint,Tests / test,Staging Reliability Gate / reliability-gate,Backup Restore Gate / backup-restore"
CHECKS="${CHECKS:-$DEFAULT_CHECKS}"

# Convert comma-separated string to JSON array objects: [{"context":"..."}, ...]
IFS=',' read -r -a check_items <<< "$CHECKS"
checks_json="[]"
for item in "${check_items[@]}"; do
  ctx="$(echo "$item" | xargs)"
  checks_json="$(echo "$checks_json" | jq --arg c "$ctx" '. + [{"context": $c}]')"
done

payload="$(jq -n \
  --argjson checks "$checks_json" \
  '{
    required_status_checks: {
      strict: true,
      checks: $checks
    },
    enforce_admins: true,
    required_pull_request_reviews: {
      dismiss_stale_reviews: true,
      require_code_owner_reviews: true,
      required_approving_review_count: 1
    },
    restrictions: null,
    required_linear_history: true,
    allow_force_pushes: false,
    allow_deletions: false,
    block_creations: false,
    required_conversation_resolution: true,
    lock_branch: false,
    allow_fork_syncing: true
  }')"

echo "Applying branch protection to ${GH_REPO}:${BRANCH}"
gh api \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  "/repos/${GH_REPO}/branches/${BRANCH}/protection" \
  --input - <<< "$payload"

echo "Branch protection applied successfully."

