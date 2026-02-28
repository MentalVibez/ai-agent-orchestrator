"""DEX (Digital Employee Experience) API routes.

Provides endpoints for endpoint registry, DEX scoring, fleet overview,
alerts, predictive trends, sentiment feedback, and runbook search.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dex.dex_score import (
    get_latest_score,
    get_score_history,
)
from app.core.dex.endpoint_registry import (
    create_endpoint,
    deregister_endpoint,
    get_endpoint,
    list_endpoints,
    update_endpoint,
)
from app.core.rate_limit import limiter
from app.db.database import SessionLocal
from app.db.models import DexAlert, EmployeeFeedback, EndpointMetricSnapshot

router = APIRouter(prefix="/api/v1/dex", tags=["dex"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class EndpointCreate(BaseModel):
    hostname: str = Field(..., description="Unique hostname or device identifier")
    ip_address: Optional[str] = None
    owner_email: Optional[str] = None
    persona: Optional[str] = Field(
        None,
        description="Role persona: developer | salesperson | executive | tech | general",
    )
    criticality_tier: int = Field(
        default=2,
        ge=1,
        le=3,
        description="1=critical, 2=standard, 3=low",
    )
    os_platform: Optional[str] = Field(
        None, description="windows | linux | macos"
    )
    tags: Optional[Dict[str, str]] = None


class EndpointUpdate(BaseModel):
    ip_address: Optional[str] = None
    owner_email: Optional[str] = None
    persona: Optional[str] = None
    criticality_tier: Optional[int] = Field(None, ge=1, le=3)
    os_platform: Optional[str] = None
    tags: Optional[Dict[str, str]] = None
    is_active: Optional[bool] = None


class FeedbackCreate(BaseModel):
    hostname: Optional[str] = None
    rating: int = Field(..., ge=1, le=5, description="1=very poor, 5=excellent")
    comment: Optional[str] = None
    category: Optional[str] = Field(
        None,
        description="performance | connectivity | software | hardware | other",
    )


# ---------------------------------------------------------------------------
# Endpoint Registry
# ---------------------------------------------------------------------------


@router.post(
    "/endpoints",
    status_code=status.HTTP_201_CREATED,
    summary="Register a managed endpoint",
)
@limiter.limit("60/minute")
async def register_endpoint(
    request: Request,
    body: EndpointCreate,
    db: Session = Depends(get_db),
) -> dict:
    """Register a new endpoint in the DEX fleet."""
    try:
        endpoint = create_endpoint(
            db=db,
            hostname=body.hostname,
            ip_address=body.ip_address,
            owner_email=body.owner_email,
            persona=body.persona,
            criticality_tier=body.criticality_tier,
            os_platform=body.os_platform,
            tags=body.tags,
        )
        return {"ok": True, "endpoint": endpoint.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.get("/endpoints", summary="List all registered endpoints")
@limiter.limit("120/minute")
async def list_all_endpoints(
    request: Request,
    active_only: bool = Query(True),
    persona: Optional[str] = Query(None),
    criticality_tier: Optional[int] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    endpoints = list_endpoints(
        db,
        active_only=active_only,
        persona=persona,
        criticality_tier=criticality_tier,
        limit=limit,
        offset=offset,
    )
    return {"endpoints": [e.to_dict() for e in endpoints], "total": len(endpoints)}


@router.get("/endpoints/{hostname}", summary="Get endpoint detail + current DEX score")
@limiter.limit("120/minute")
async def get_endpoint_detail(
    request: Request,
    hostname: str,
    db: Session = Depends(get_db),
) -> dict:
    endpoint = get_endpoint(db, hostname)
    if not endpoint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Endpoint '{hostname}' not found.",
        )
    score_record = get_latest_score(db, hostname)
    return {
        "endpoint": endpoint.to_dict(),
        "dex_score": score_record.to_dict() if score_record else None,
    }


@router.patch("/endpoints/{hostname}", summary="Update endpoint metadata")
@limiter.limit("60/minute")
async def patch_endpoint(
    request: Request,
    hostname: str,
    body: EndpointUpdate,
    db: Session = Depends(get_db),
) -> dict:
    endpoint = update_endpoint(
        db=db,
        hostname=hostname,
        ip_address=body.ip_address,
        owner_email=body.owner_email,
        persona=body.persona,
        criticality_tier=body.criticality_tier,
        os_platform=body.os_platform,
        tags=body.tags,
        is_active=body.is_active,
    )
    if not endpoint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Endpoint '{hostname}' not found.",
        )
    return {"ok": True, "endpoint": endpoint.to_dict()}


@router.delete(
    "/endpoints/{hostname}",
    summary="Deregister (soft-delete) an endpoint",
)
@limiter.limit("30/minute")
async def delete_endpoint(
    request: Request,
    hostname: str,
    db: Session = Depends(get_db),
) -> dict:
    removed = deregister_endpoint(db, hostname)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Endpoint '{hostname}' not found.",
        )
    return {"ok": True, "message": f"Endpoint '{hostname}' deregistered."}


# ---------------------------------------------------------------------------
# On-Demand Scan
# ---------------------------------------------------------------------------


@router.post(
    "/endpoints/{hostname}/scan",
    summary="Trigger an immediate health scan for an endpoint",
)
@limiter.limit("20/minute")
async def trigger_scan(
    request: Request,
    hostname: str,
    db: Session = Depends(get_db),
) -> dict:
    """Start an AI-driven health scan for this endpoint using the dex_proactive profile.

    Returns the run_id — poll GET /api/v1/runs/{run_id} to track progress.
    """
    endpoint = get_endpoint(db, hostname)
    if not endpoint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Endpoint '{hostname}' not found.",
        )

    from app.core.dex.telemetry_collector import trigger_endpoint_scan

    try:
        run_id = await trigger_endpoint_scan(request.app, hostname)
        return {
            "ok": True,
            "hostname": hostname,
            "run_id": run_id,
            "message": "Scan started. Poll GET /api/v1/runs/{run_id} for results.",
        }
    except Exception as e:
        logger.error("DEX scan trigger failed for %s: %s", hostname, e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to start scan: {e}",
        )


# ---------------------------------------------------------------------------
# Score
# ---------------------------------------------------------------------------


@router.get("/endpoints/{hostname}/score", summary="Current DEX score with component breakdown")
@limiter.limit("120/minute")
async def get_score(
    request: Request,
    hostname: str,
    db: Session = Depends(get_db),
) -> dict:
    score_record = get_latest_score(db, hostname)
    if not score_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No score yet for '{hostname}'. Trigger a scan first.",
        )
    return score_record.to_dict()


@router.get("/endpoints/{hostname}/history", summary="DEX score history (time series)")
@limiter.limit("60/minute")
async def get_score_history_endpoint(
    request: Request,
    hostname: str,
    limit: int = Query(96, ge=1, le=1000, description="Number of readings (default 96 ≈ 24h at 15-min intervals)"),
    db: Session = Depends(get_db),
) -> dict:
    records = get_score_history(db, hostname, limit=limit)
    return {
        "hostname": hostname,
        "history": [r.to_dict() for r in records],
        "count": len(records),
    }


@router.get("/endpoints/{hostname}/snapshots", summary="Raw metric snapshots for an endpoint")
@limiter.limit("60/minute")
async def get_snapshots(
    request: Request,
    hostname: str,
    limit: int = Query(48, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    snapshots = (
        db.query(EndpointMetricSnapshot)
        .filter(EndpointMetricSnapshot.hostname == hostname)
        .order_by(EndpointMetricSnapshot.captured_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "hostname": hostname,
        "snapshots": [s.to_dict() for s in snapshots],
        "count": len(snapshots),
    }


# ---------------------------------------------------------------------------
# Predictive Trends
# ---------------------------------------------------------------------------


@router.get(
    "/endpoints/{hostname}/trends",
    summary="Predictive trend analysis (time-to-impact estimates)",
)
@limiter.limit("30/minute")
async def get_trends(
    request: Request,
    hostname: str,
    db: Session = Depends(get_db),
) -> dict:
    from app.core.dex.predictive_analysis import analyze_trends

    trends = analyze_trends(db, hostname)
    return {"hostname": hostname, "trends": trends}


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


@router.get("/alerts", summary="All active DEX alerts across the fleet")
@limiter.limit("120/minute")
async def list_alerts(
    request: Request,
    hostname: Optional[str] = Query(None),
    severity: Optional[str] = Query(None, description="info | warning | critical"),
    alert_type: Optional[str] = Query(None, description="threshold | predictive | prometheus"),
    status_filter: Optional[str] = Query(
        None, alias="status", description="active | remediating | resolved | acknowledged | needs_human"
    ),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    q = db.query(DexAlert)
    if hostname:
        q = q.filter(DexAlert.hostname == hostname)
    if severity:
        q = q.filter(DexAlert.severity == severity)
    if alert_type:
        q = q.filter(DexAlert.alert_type == alert_type)
    if status_filter:
        q = q.filter(DexAlert.status == status_filter)
    else:
        # Default: show non-resolved alerts
        q = q.filter(DexAlert.status.notin_(["resolved"]))
    alerts = q.order_by(DexAlert.created_at.desc()).limit(limit).all()
    return {"alerts": [a.to_dict() for a in alerts], "total": len(alerts)}


@router.post(
    "/alerts/{alert_id}/acknowledge",
    summary="Acknowledge a DEX alert (suppress for N hours)",
)
@limiter.limit("60/minute")
async def acknowledge_alert(
    request: Request,
    alert_id: int,
    hours: int = Query(4, ge=1, le=72, description="Suppress for this many hours"),
    db: Session = Depends(get_db),
) -> dict:
    from datetime import datetime, timedelta, timezone

    alert = db.query(DexAlert).filter(DexAlert.id == alert_id).first()
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert {alert_id} not found.",
        )
    alert.status = "acknowledged"
    alert.acknowledged_until = datetime.now(timezone.utc) + timedelta(hours=hours)
    db.commit()
    return {
        "ok": True,
        "alert_id": alert_id,
        "acknowledged_until": alert.acknowledged_until.isoformat(),
    }


# ---------------------------------------------------------------------------
# Fleet Overview
# ---------------------------------------------------------------------------


@router.get("/fleet", summary="Fleet-wide DEX summary (avg score, at-risk endpoints)")
@limiter.limit("60/minute")
async def fleet_summary(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:

    endpoints = list_endpoints(db, active_only=True)
    total = len(endpoints)
    if total == 0:
        return {
            "total_endpoints": 0,
            "avg_dex_score": None,
            "at_risk": 0,
            "critical": 0,
            "healthy": 0,
        }

    at_risk_threshold = settings.dex_score_alert_threshold
    critical_threshold = settings.dex_score_critical_threshold

    scores: List[Dict[str, Any]] = []
    for ep in endpoints:
        record = get_latest_score(db, ep.hostname)
        if record:
            scores.append(
                {"hostname": ep.hostname, "score": record.score, "scored_at": record.scored_at}
            )

    if not scores:
        return {
            "total_endpoints": total,
            "avg_dex_score": None,
            "endpoints_scored": 0,
            "at_risk": 0,
            "critical": 0,
            "healthy": 0,
        }

    avg_score = round(sum(s["score"] for s in scores) / len(scores), 1)
    at_risk = sum(1 for s in scores if s["score"] <= at_risk_threshold)
    critical = sum(1 for s in scores if s["score"] <= critical_threshold)
    healthy = sum(1 for s in scores if s["score"] > at_risk_threshold)

    return {
        "total_endpoints": total,
        "endpoints_scored": len(scores),
        "avg_dex_score": avg_score,
        "at_risk": at_risk,
        "critical": critical,
        "healthy": healthy,
        "thresholds": {
            "alert": at_risk_threshold,
            "critical": critical_threshold,
        },
    }


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------


@router.get(
    "/incidents",
    summary="Active incidents (correlated alerts per endpoint)",
)
@limiter.limit("60/minute")
async def list_incidents(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Returns endpoints that have 2+ active/remediating alerts, grouped as incidents."""
    from collections import defaultdict

    active_alerts = (
        db.query(DexAlert)
        .filter(DexAlert.status.in_(["active", "remediating", "needs_human"]))
        .order_by(DexAlert.hostname, DexAlert.created_at.desc())
        .all()
    )

    grouped: dict = defaultdict(list)
    for alert in active_alerts:
        grouped[alert.hostname].append(alert.to_dict())

    incidents = []
    for hostname, alerts in grouped.items():
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        top_severity = min(alerts, key=lambda a: severity_order.get(a["severity"], 99))[
            "severity"
        ]
        incidents.append(
            {
                "hostname": hostname,
                "alert_count": len(alerts),
                "top_severity": top_severity,
                "alerts": alerts,
            }
        )

    # Sort by severity then alert count
    incidents.sort(
        key=lambda i: ({"critical": 0, "warning": 1, "info": 2}.get(i["top_severity"], 99), -i["alert_count"])
    )
    return {"incidents": incidents, "total": len(incidents)}


# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------


@router.get("/kpis", summary="DEX KPIs: MTTR, auto-resolution rate, fleet score")
@limiter.limit("30/minute")
async def get_kpis(
    request: Request,
    lookback_days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
) -> dict:
    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    all_alerts = (
        db.query(DexAlert).filter(DexAlert.created_at >= since).all()
    )
    resolved = [a for a in all_alerts if a.status == "resolved" and a.resolved_at]
    auto_resolved = [a for a in resolved if a.remediation_run_id]

    # MTTR in minutes
    mttr_minutes: Optional[float] = None
    if resolved:
        times = [
            (a.resolved_at - a.created_at).total_seconds() / 60
            for a in resolved
            if a.resolved_at and a.created_at
        ]
        if times:
            mttr_minutes = round(sum(times) / len(times), 1)

    auto_resolution_rate = (
        round(len(auto_resolved) / len(all_alerts) * 100, 1) if all_alerts else None
    )

    # Fleet average DEX score
    endpoints = list_endpoints(db, active_only=True)
    fleet_scores = [
        r.score
        for ep in endpoints
        for r in [get_latest_score(db, ep.hostname)]
        if r
    ]
    avg_fleet_score = (
        round(sum(fleet_scores) / len(fleet_scores), 1) if fleet_scores else None
    )

    return {
        "lookback_days": lookback_days,
        "mttr_minutes": mttr_minutes,
        "auto_resolution_rate_pct": auto_resolution_rate,
        "total_alerts": len(all_alerts),
        "resolved_alerts": len(resolved),
        "auto_resolved_alerts": len(auto_resolved),
        "avg_fleet_dex_score": avg_fleet_score,
    }


# ---------------------------------------------------------------------------
# Runbooks (Phase 4 — RAG-backed)
# ---------------------------------------------------------------------------


@router.get(
    "/endpoints/{hostname}/runbooks",
    summary="Retrieve relevant runbooks for an endpoint's active alerts",
)
@limiter.limit("30/minute")
async def get_endpoint_runbooks(
    request: Request,
    hostname: str,
    alert: Optional[str] = Query(None, description="Filter runbooks by alert name"),
    limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
) -> dict:
    """Search ChromaDB for runbooks relevant to this endpoint's current alerts."""
    try:
        from app.core.rag import search_documents  # type: ignore

        query = alert or f"IT remediation for {hostname}"
        results = search_documents(query=query, n_results=limit)
        return {"hostname": hostname, "runbooks": results, "query": query}
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG module not available (chromadb not installed).",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/runbooks/index", summary="Index a runbook document into ChromaDB")
@limiter.limit("20/minute")
async def index_runbook(
    request: Request,
    content: str = Query(..., description="Runbook markdown content"),
    doc_id: str = Query(..., description="Unique document ID (e.g. 'disk_cleanup_v1')"),
    collection: str = Query("runbooks", description="ChromaDB collection name"),
) -> dict:
    try:
        from app.core.rag import index_document  # type: ignore

        index_document(doc_id=doc_id, content=content, collection=collection)
        return {"ok": True, "doc_id": doc_id, "collection": collection}
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG module not available.",
        )


# ---------------------------------------------------------------------------
# Employee Feedback / Sentiment
# ---------------------------------------------------------------------------


@router.post("/feedback", status_code=status.HTTP_201_CREATED, summary="Submit a pulse survey")
@limiter.limit("20/minute")
async def submit_feedback(
    request: Request,
    body: FeedbackCreate,
    db: Session = Depends(get_db),
) -> dict:
    if body.hostname:
        endpoint = get_endpoint(db, body.hostname)
        if not endpoint:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Endpoint '{body.hostname}' not found.",
            )

    fb = EmployeeFeedback(
        hostname=body.hostname,
        rating=body.rating,
        comment=body.comment,
        category=body.category,
    )
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return {"ok": True, "feedback": fb.to_dict()}


@router.get("/feedback/summary", summary="Aggregated sentiment summary and eNPS")
@limiter.limit("30/minute")
async def feedback_summary(
    request: Request,
    lookback_days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict:
    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    records = (
        db.query(EmployeeFeedback)
        .filter(EmployeeFeedback.submitted_at >= since)
        .all()
    )
    if not records:
        return {
            "lookback_days": lookback_days,
            "total_responses": 0,
            "avg_rating": None,
            "enps": None,
        }

    ratings = [r.rating for r in records]
    avg_rating = round(sum(ratings) / len(ratings), 2)
    promoters = sum(1 for r in ratings if r >= 4)
    detractors = sum(1 for r in ratings if r <= 2)
    enps = round((promoters - detractors) / len(ratings) * 100, 1)

    category_counts: Dict[str, int] = {}
    for r in records:
        if r.category:
            category_counts[r.category] = category_counts.get(r.category, 0) + 1

    return {
        "lookback_days": lookback_days,
        "total_responses": len(records),
        "avg_rating": avg_rating,
        "enps": enps,
        "promoters": promoters,
        "detractors": detractors,
        "passives": len(ratings) - promoters - detractors,
        "top_categories": sorted(category_counts.items(), key=lambda x: -x[1]),
    }
