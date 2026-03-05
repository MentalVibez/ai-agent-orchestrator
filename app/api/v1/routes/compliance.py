"""Compliance report endpoint — admin-only aggregated evidence for HIPAA/SOC2 auditors.

GET /api/v1/admin/compliance/report
  Query params:
    since   (datetime, ISO-8601)  — start of reporting period (default: 30 days ago)
    until   (datetime, ISO-8601)  — end of reporting period (default: now)
    format  ("json" | "csv")      — response format (default: json)

JSON response includes:
  - request counts by method/status class, auth failures, top paths
  - per-key LLM spend vs monthly cap
  - run counts by status
  - total LLM cost by provider

CSV response has one row per api_key_id with the same key-level metrics.
"""

import csv
import io
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from app.core.auth import verify_api_key
from app.core.rate_limit import limiter
from app.db.database import SessionLocal
from app.db.models import ApiKeyRecord, AuditLogRecord, CostRecordDB, Run

router = APIRouter(prefix="/api/v1/admin", tags=["compliance"])


@router.get(
    "/compliance/report",
    summary="Compliance evidence report",
    description=(
        "Admin-only. Returns aggregated audit, cost, and run evidence for HIPAA/SOC2 auditors. "
        "Pass ?format=csv for a CSV attachment suitable for spreadsheet analysis."
    ),
)
@limiter.limit("10/minute")
async def compliance_report(
    request: Request,
    since: Optional[datetime] = Query(
        None,
        description="Start of period (ISO-8601). Default: 30 days ago.",
    ),
    until: Optional[datetime] = Query(
        None,
        description="End of period (ISO-8601). Default: now.",
    ),
    format: str = Query("json", description="Response format: json or csv"),
    api_key: str = Depends(verify_api_key),
) -> Response:
    """Generate compliance evidence report (admin only)."""
    role = getattr(request.state, "api_key_role", None)
    if role != "admin":
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Admin role required for compliance reports.")

    now = datetime.now(timezone.utc)
    _since = since or (now - timedelta(days=30))
    _until = until or now

    # Strip tz for naive DB timestamps where needed
    since_naive = _since.replace(tzinfo=None) if _since.tzinfo else _since
    until_naive = _until.replace(tzinfo=None) if _until.tzinfo else _until

    db = SessionLocal()
    try:
        # ── Audit log aggregation ────────────────────────────────────────────
        audit_q = db.query(AuditLogRecord).filter(
            AuditLogRecord.timestamp >= since_naive,
            AuditLogRecord.timestamp <= until_naive,
        ).all()

        total_requests = len(audit_q)
        by_method: dict = Counter(r.method for r in audit_q)
        by_status_class: dict = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}
        auth_failures = 0
        path_counter: dict = Counter()

        for r in audit_q:
            sc = r.status_code or 0
            cls = f"{sc // 100}xx"
            if cls in by_status_class:
                by_status_class[cls] += 1
            if sc in (401, 403):
                auth_failures += 1
            path_counter[r.path] += 1

        top_paths = [{"path": p, "count": c} for p, c in path_counter.most_common(10)]

        # Requests per api_key_id
        key_request_counts: dict = Counter(r.api_key_id for r in audit_q if r.api_key_id)

        # ── LLM cost aggregation ─────────────────────────────────────────────
        cost_q = db.query(CostRecordDB).filter(
            CostRecordDB.timestamp >= since_naive,
            CostRecordDB.timestamp <= until_naive,
        ).all()

        total_llm_cost = sum(r.cost_usd or 0.0 for r in cost_q)
        by_provider: dict = defaultdict(float)
        key_llm_spend: dict = defaultdict(float)
        for r in cost_q:
            by_provider[r.provider] += r.cost_usd or 0.0
            if r.api_key_id:
                key_llm_spend[r.api_key_id] += r.cost_usd or 0.0

        # ── Run aggregation ──────────────────────────────────────────────────
        # Run.created_at is tz-aware in the model but may be stored naive in SQLite
        try:
            run_q = db.query(Run).filter(
                Run.created_at >= _since,
                Run.created_at <= _until,
            ).all()
        except Exception:
            run_q = db.query(Run).filter(
                Run.created_at >= since_naive,
                Run.created_at <= until_naive,
            ).all()

        total_runs = len(run_q)
        by_status: dict = Counter(r.status for r in run_q)

        # ── API keys metadata ─────────────────────────────────────────────────
        all_keys = db.query(ApiKeyRecord).all()

        # ── Current-month spend per key (for cap comparison) ─────────────────
        month_since = datetime(now.year, now.month, 1)
        month_cost_q = db.query(CostRecordDB).filter(
            CostRecordDB.timestamp >= month_since,
        ).all()
        monthly_key_spend: dict = defaultdict(float)
        for r in month_cost_q:
            if r.api_key_id:
                monthly_key_spend[r.api_key_id] += r.cost_usd or 0.0

        api_keys_data = [
            {
                "api_key_id": k.key_id,
                "name": k.name,
                "role": k.role,
                "is_active": k.is_active,
                "request_count": key_request_counts.get(k.key_id, 0),
                "period_llm_spend_usd": round(key_llm_spend.get(k.key_id, 0.0), 4),
                "monthly_llm_spend_usd": round(monthly_key_spend.get(k.key_id, 0.0), 4),
                "monthly_cap_usd": k.max_monthly_cost_usd,
            }
            for k in all_keys
        ]

    finally:
        db.close()

    # ── Build response ────────────────────────────────────────────────────────
    report = {
        "generated_at": now.isoformat(),
        "period": {
            "since": _since.isoformat(),
            "until": _until.isoformat(),
        },
        "requests": {
            "total": total_requests,
            "by_method": dict(by_method),
            "by_status_class": by_status_class,
            "auth_failures": auth_failures,
            "top_paths": top_paths,
        },
        "api_keys": api_keys_data,
        "runs": {
            "total": total_runs,
            "by_status": dict(by_status),
        },
        "llm_cost": {
            "total_usd": round(total_llm_cost, 4),
            "by_provider": {k: round(v, 4) for k, v in by_provider.items()},
        },
    }

    if format.lower() == "csv":
        return _build_csv_response(report)

    from fastapi.responses import JSONResponse
    return JSONResponse(content=report)


def _build_csv_response(report: dict) -> Response:
    """Build a CSV attachment with one row per API key."""
    output = io.StringIO()
    fieldnames = [
        "api_key_id", "name", "role", "is_active",
        "request_count", "period_llm_spend_usd",
        "monthly_llm_spend_usd", "monthly_cap_usd",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in report.get("api_keys", []):
        writer.writerow(row)
    csv_content = output.getvalue()
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=compliance_report.csv"},
    )
