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


class CreateKeyResponse(BaseModel):
    key_id: str
    raw_key: str
    name: str
    role: str
    message: str


class KeyInfoResponse(BaseModel):
    key_id: str
    name: str
    role: str
    is_active: bool
    created_at: str | None
    last_used_at: str | None
    revoked_at: str | None


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
        key_id, raw_key, record = create_api_key(db, name=body.name, role=body.role)
    finally:
        db.close()

    return CreateKeyResponse(
        key_id=key_id,
        raw_key=raw_key,
        name=record.name,
        role=record.role,
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
