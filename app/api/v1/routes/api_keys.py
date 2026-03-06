"""Admin API key management routes.

All endpoints require admin role.
The raw key is shown once at creation — it cannot be retrieved again.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.core.auth import require_role, verify_api_key
from app.core.rate_limit import limiter
from app.db.database import SessionLocal

router = APIRouter(prefix="/api/v1/admin/keys", tags=["api-key-management"])

_admin_deps = [Depends(verify_api_key), Depends(require_role("admin"))]


class CreateKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120, description="Human label for this key")
    role: str = Field(default="operator", description="viewer | operator | admin")
    max_monthly_cost_usd: float | None = Field(
        default=None, ge=0, description="Monthly LLM spend cap in USD. NULL = no limit."
    )
    webhook_url: str | None = Field(
        default=None, description="URL to POST run terminal events (completed/failed/cancelled)."
    )


class UpdateKeyRequest(BaseModel):
    webhook_url: str | None = Field(
        default=None, description="Webhook URL for run terminal events. Pass null to clear."
    )
    max_monthly_cost_usd: float | None = Field(
        default=None, ge=0, description="Monthly LLM spend cap in USD. Pass null to remove cap."
    )


class CreateKeyResponse(BaseModel):
    key_id: str
    raw_key: str
    name: str
    role: str
    max_monthly_cost_usd: float | None
    webhook_url: str | None
    message: str


class KeyInfoResponse(BaseModel):
    key_id: str
    name: str
    role: str
    is_active: bool
    created_at: str | None
    last_used_at: str | None
    revoked_at: str | None
    max_monthly_cost_usd: float | None
    webhook_url: str | None = None


@router.post(
    "",
    response_model=CreateKeyResponse,
    status_code=201,
    summary="Create a new API key (admin only)",
    dependencies=_admin_deps,
)
@limiter.limit("10/minute")
async def create_key(request: Request, body: CreateKeyRequest) -> CreateKeyResponse:
    """Create a named API key with a given role. The raw key is shown once."""
    from app.core.api_keys import VALID_ROLES, create_api_key

    if body.role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid role '{body.role}'. Valid roles: {sorted(VALID_ROLES)}",
        )

    db = SessionLocal()
    try:
        key_id, raw_key, record = create_api_key(
            db,
            name=body.name,
            role=body.role,
            max_monthly_cost_usd=body.max_monthly_cost_usd,
            webhook_url=body.webhook_url,
        )
    finally:
        db.close()

    return CreateKeyResponse(
        key_id=key_id,
        raw_key=raw_key,
        name=record.name,
        role=record.role,
        max_monthly_cost_usd=record.max_monthly_cost_usd,
        webhook_url=record.webhook_url,
        message="Store this key securely — it will not be shown again.",
    )


@router.get(
    "",
    response_model=list[KeyInfoResponse],
    summary="List all API keys (admin only)",
    dependencies=_admin_deps,
)
@limiter.limit("30/minute")
async def list_keys(request: Request) -> list[KeyInfoResponse]:
    """List all API keys with metadata (no raw keys returned)."""
    from app.core.api_keys import list_api_keys

    db = SessionLocal()
    try:
        records = list_api_keys(db)
    finally:
        db.close()

    return [KeyInfoResponse(**r.to_dict()) for r in records]


@router.delete(
    "/{key_id}",
    summary="Revoke an API key (admin only)",
    dependencies=_admin_deps,
)
@limiter.limit("10/minute")
async def revoke_key(request: Request, key_id: str) -> dict:
    """Revoke (soft-delete) a key by key_id. Revoked keys are rejected immediately."""
    from app.core.api_keys import revoke_api_key

    db = SessionLocal()
    try:
        record = revoke_api_key(db, key_id)
    finally:
        db.close()

    if not record:
        raise HTTPException(status_code=404, detail=f"Key '{key_id}' not found.")

    return {
        "key_id": key_id,
        "revoked": True,
        "revoked_at": record.revoked_at.isoformat() if record.revoked_at else None,
        "message": f"Key '{key_id}' ({record.name}) has been revoked.",
    }


@router.patch(
    "/{key_id}",
    response_model=KeyInfoResponse,
    summary="Update mutable fields on an API key (admin only)",
    dependencies=_admin_deps,
)
@limiter.limit("10/minute")
async def update_key(request: Request, key_id: str, body: UpdateKeyRequest) -> KeyInfoResponse:
    """Update webhook_url and/or max_monthly_cost_usd on an existing key.

    Pass null explicitly to clear a field. Only fields present in the request body
    are changed; omitted fields are left unchanged.
    """
    from app.core.api_keys import update_api_key

    # Build kwargs only for fields the caller explicitly included in the request body.
    # model_fields_set distinguishes "omitted" (skip) from "passed null" (clear).
    kwargs: dict = {}
    if "webhook_url" in body.model_fields_set:
        kwargs["webhook_url"] = body.webhook_url
    if "max_monthly_cost_usd" in body.model_fields_set:
        kwargs["max_monthly_cost_usd"] = body.max_monthly_cost_usd

    db = SessionLocal()
    try:
        record = update_api_key(db, key_id, **kwargs)
    finally:
        db.close()

    if not record:
        raise HTTPException(status_code=404, detail=f"Key '{key_id}' not found.")

    return KeyInfoResponse(**record.to_dict())
