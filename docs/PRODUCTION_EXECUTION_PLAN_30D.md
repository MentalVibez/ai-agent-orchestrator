# 30-Day Production Readiness Execution Plan

This plan is optimized for speed. It focuses on objective go-live gates, not feature expansion.

## Exit Criteria (Go/No-Go)

A release is production-ready only when all are true:

1. Reliability gate passes in CI and staging for 7 consecutive days.
2. Security gate has zero unresolved High/Critical findings.
3. Postgres backup/restore drill completes with documented RTO/RPO.
4. On-call runbook drill completed for top 5 incidents.
5. SLO dashboards/alerts are live and alert routing is validated.

## Week 1 (Days 1-7): Security + Correctness Lockdown

1. Complete security fixes
- Replace all unsafe dynamic execution patterns in runtime paths.
- Enforce outbound webhook signing in all environments.
- Validate RBAC and row-level run ownership using integration tests.

2. CI security gates
- Keep Bandit + pip-audit + Trivy as blocking checks.
- Add dependency/license policy review before merge.

3. Acceptance checks
- No raw secrets in logs/events.
- Signed webhook verification test passes.
- Authz regression tests pass.

## Week 2 (Days 8-14): Reliability Under Failure

1. Staging topology
- Run API + worker + Postgres + Redis in staging-like compose/k8s.
- Validate queue mode and in-process mode both work.

2. Failure drills
- DB unavailable at startup and mid-run.
- Redis unavailable (queue fallback and recovery behavior).
- LLM provider timeouts and circuit breaker behavior.
- MCP server disconnect and reconnect.

3. Acceptance checks
- No stuck runs after component recovery.
- Retry/backoff and circuit-breaker metrics visible.
- Run completion SLI stable during controlled failures.

## Week 3 (Days 15-21): Data + Ops Readiness

1. Data lifecycle
- Backup + restore automation for Postgres.
- Retention policy for runs/events/audit log.
- Confirm migration rollback procedures.

2. Observability
- SLOs: API availability, run success rate, p95 run start latency.
- Dashboards: queue depth, stuck runs, tool timeout rate, per-key error/cost trends.
- Alert tuning to remove noise and ensure pager relevance.

3. Acceptance checks
- Restore drill done and documented.
- Alert runbook links embedded in alerts.
- No unactionable alert spam for 5 days.

## Week 4 (Days 22-30): Release Safety + Go-Live Drill

1. Release controls
- Canary/blue-green with automated rollback conditions.
- Pre-deploy checks: migrations, health, critical route smoke tests.
- Post-deploy checks: error budget burn + queue health + webhook delivery rate.

2. Operational rehearsal
- Simulated incident response drill with real escalation path.
- Measure MTTA/MTTR and update runbooks.

3. Acceptance checks
- Deployment rollback tested end-to-end.
- Incident drill complete with corrective actions closed.
- Final go/no-go review signed off.

## Immediate Tasks (Execute Now)

1. Apply critical security/reliability fixes in code (in progress in this branch).
2. Run full test suite and static checks locally and in CI.
3. Create a staging validation checklist and start daily gate tracking.
4. Schedule backup/restore drill date and owner.

## Daily Gate Template

Track daily in standup:

1. Security gate status: pass/fail + blocker.
2. Reliability gate status: pass/fail + blocker.
3. SLO status: within budget / burn risk.
4. Open P0/P1 incidents and ETA.
5. Go-live confidence (%).

## Recommended Owners

1. Security lead: authz, secrets, webhook signing verification.
2. Platform lead: CI gates, deployment, rollback automation.
3. Backend lead: run lifecycle correctness, queue/worker behavior.
4. SRE lead: SLOs, alerting, incident drills.
5. Product owner: go/no-go decision and risk acceptance.
