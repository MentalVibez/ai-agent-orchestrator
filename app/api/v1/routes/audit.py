"""Admin audit log routes.

All endpoints require admin role. Provides paginated, filterable access
to the HTTP request audit trail.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi import Query as Q
from pydantic import BaseModel

from app.core.auth import require_role, verify_api_key
from app.core.rate_limit import limiter
from app.db.database import SessionLocal

router = APIRouter(prefix="/api/v1/admin/audit", tags=["audit"])

_admin_deps = [Depends(verify_api_key), Depends(require_role("admin"))]


class AuditEntry(BaseModel):
    id: int
    request_id: Optional[str]
    timestamp: Optional[str]
    method: str
    path: str
    status_code: Optional[int]
    api_key_id: Optional[str]
    api_key_role: Optional[str]
    client_ip: Optional[str]
    user_agent: Optional[str]
    request_body: Optional[str]


class AuditListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[AuditEntry]


@router.get(
    "",
    response_model=AuditListResponse,
    summary="List audit log entries (admin only)",
    dependencies=_admin_deps,
)
@limiter.limit("30/minute")
async def list_audit_log(
    request: Request,
    page: int = Q(default=1, ge=1),
    page_size: int = Q(default=50, ge=1, le=500),
    api_key_id: Optional[str] = Q(default=None),
    path: Optional[str] = Q(default=None, description="Substring match on path"),
    status_code: Optional[int] = Q(default=None),
    since: Optional[datetime] = Q(default=None, description="ISO-8601 lower bound"),
    until: Optional[datetime] = Q(default=None, description="ISO-8601 upper bound"),
) -> AuditListResponse:
    from app.db.models import AuditLogRecord

    db = SessionLocal()
    try:
        q = db.query(AuditLogRecord)
        if api_key_id:
            q = q.filter(AuditLogRecord.api_key_id == api_key_id)
        if path:
            q = q.filter(AuditLogRecord.path.contains(path))
        if status_code is not None:
            q = q.filter(AuditLogRecord.status_code == status_code)
        if since:
            q = q.filter(AuditLogRecord.timestamp >= since)
        if until:
            q = q.filter(AuditLogRecord.timestamp <= until)

        total = q.count()
        records = (
            q.order_by(AuditLogRecord.timestamp.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
    finally:
        db.close()

    return AuditListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[AuditEntry(**r.to_dict()) for r in records],
    )
