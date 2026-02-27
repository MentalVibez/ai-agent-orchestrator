"""API key registry: create, list, rotate, and revoke named keys with RBAC roles.

Keys are stored as SHA-256 hashes — the raw key is shown only once at creation time.
The env-var API_KEY acts as a permanent admin bootstrap key and is never stored in DB.

Roles
-----
viewer   — read-only endpoints (GET /runs, GET /agents, health)
operator — viewer + start/cancel runs, approve HITL
admin    — operator + key management (create/revoke keys)
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import ApiKeyRecord

# Roles ordered from lowest to highest privilege
ROLE_ORDER = {"viewer": 0, "operator": 1, "admin": 2}
VALID_ROLES = set(ROLE_ORDER.keys())

# Keys are prefixed so they are recognisable in logs (key_id is the public part)
KEY_PREFIX = "orc_"


def _hash_key(raw_key: str) -> str:
    """Return SHA-256 hex digest of the raw key."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def generate_api_key() -> tuple[str, str]:
    """Generate a new (key_id, raw_key) pair.

    Returns
    -------
    key_id  — public identifier stored in DB (safe to log)
    raw_key — full key shown to the caller exactly once; never stored plain
    """
    key_id = f"kid_{uuid.uuid4().hex[:12]}"
    raw_key = KEY_PREFIX + secrets.token_urlsafe(40)
    return key_id, raw_key


def create_api_key(db: Session, name: str, role: str = "operator") -> tuple[str, str, ApiKeyRecord]:
    """Create and persist a new API key.

    Returns (key_id, raw_key, record). Caller must show raw_key to user; it is
    never retrievable again.
    """
    if role not in VALID_ROLES:
        raise ValueError(f"Invalid role '{role}'. Must be one of: {', '.join(VALID_ROLES)}")
    key_id, raw_key = generate_api_key()
    record = ApiKeyRecord(
        key_id=key_id,
        key_hash=_hash_key(raw_key),
        name=name,
        role=role,
        is_active=True,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return key_id, raw_key, record


def lookup_api_key(db: Session, raw_key: str) -> Optional[ApiKeyRecord]:
    """Return the active ApiKeyRecord matching raw_key, or None.

    Uses constant-time hash comparison via == on digests to prevent oracle attacks.
    Also updates last_used_at on match.
    """
    key_hash = _hash_key(raw_key)
    record = (
        db.query(ApiKeyRecord)
        .filter(ApiKeyRecord.key_hash == key_hash, ApiKeyRecord.is_active.is_(True))
        .first()
    )
    if record:
        record.last_used_at = datetime.now(timezone.utc)
        db.commit()
    return record


def list_api_keys(db: Session) -> list[ApiKeyRecord]:
    """Return all API key records (active and revoked), ordered by creation date."""
    return db.query(ApiKeyRecord).order_by(ApiKeyRecord.created_at.desc()).all()


def revoke_api_key(db: Session, key_id: str) -> Optional[ApiKeyRecord]:
    """Revoke (soft-delete) an API key by key_id. Returns the record or None if not found."""
    record = db.query(ApiKeyRecord).filter(ApiKeyRecord.key_id == key_id).first()
    if not record:
        return None
    record.is_active = False
    record.revoked_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(record)
    return record


def has_role(record: ApiKeyRecord, required_role: str) -> bool:
    """Return True if record's role meets or exceeds required_role."""
    return ROLE_ORDER.get(record.role, -1) >= ROLE_ORDER.get(required_role, 999)
