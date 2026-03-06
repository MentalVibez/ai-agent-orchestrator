# Branch Protection Setup

Use this script to apply baseline protection on `main`:

```bash
GH_REPO=MentalVibez/ai-agent-orchestrator ./scripts/set-branch-protection.sh
```

Optional: override required check contexts:

```bash
GH_REPO=MentalVibez/ai-agent-orchestrator \
CHECKS="Tests / lint,Tests / test,Staging Reliability Gate / reliability-gate,Backup Restore Gate / backup-restore" \
./scripts/set-branch-protection.sh
```

Notes:
- Requires `gh auth login` with permissions to administer branch protection.
- Check context names are case-sensitive and must match GitHub check names exactly.
