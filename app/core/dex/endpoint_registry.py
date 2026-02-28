"""Endpoint Registry — CRUD operations for DEX managed endpoints."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.db.models import Endpoint

logger = logging.getLogger(__name__)


def create_endpoint(
    db: Session,
    hostname: str,
    ip_address: Optional[str] = None,
    owner_email: Optional[str] = None,
    persona: Optional[str] = None,
    criticality_tier: int = 2,
    os_platform: Optional[str] = None,
    tags: Optional[dict] = None,
) -> Endpoint:
    """Register a new managed endpoint. Raises ValueError if hostname already exists."""
    existing = db.query(Endpoint).filter(Endpoint.hostname == hostname).first()
    if existing:
        raise ValueError(f"Endpoint '{hostname}' is already registered.")
    endpoint = Endpoint(
        hostname=hostname,
        ip_address=ip_address,
        owner_email=owner_email,
        persona=persona,
        criticality_tier=criticality_tier,
        os_platform=os_platform,
        tags=tags or {},
    )
    db.add(endpoint)
    db.commit()
    db.refresh(endpoint)
    logger.info("DEX: registered endpoint hostname=%s tier=%d", hostname, criticality_tier)
    return endpoint


def get_endpoint(db: Session, hostname: str) -> Optional[Endpoint]:
    """Return the Endpoint record for a hostname, or None if not found."""
    return db.query(Endpoint).filter(Endpoint.hostname == hostname).first()


def list_endpoints(
    db: Session,
    active_only: bool = True,
    persona: Optional[str] = None,
    criticality_tier: Optional[int] = None,
    limit: int = 200,
    offset: int = 0,
) -> List[Endpoint]:
    """List registered endpoints with optional filters."""
    q = db.query(Endpoint)
    if active_only:
        q = q.filter(Endpoint.is_active == True)  # noqa: E712
    if persona:
        q = q.filter(Endpoint.persona == persona)
    if criticality_tier is not None:
        q = q.filter(Endpoint.criticality_tier == criticality_tier)
    return q.order_by(Endpoint.hostname).offset(offset).limit(limit).all()


def update_endpoint(
    db: Session,
    hostname: str,
    ip_address: Optional[str] = None,
    owner_email: Optional[str] = None,
    persona: Optional[str] = None,
    criticality_tier: Optional[int] = None,
    os_platform: Optional[str] = None,
    tags: Optional[dict] = None,
    is_active: Optional[bool] = None,
) -> Optional[Endpoint]:
    """Update mutable metadata fields on an endpoint. Returns None if not found."""
    endpoint = db.query(Endpoint).filter(Endpoint.hostname == hostname).first()
    if not endpoint:
        return None
    if ip_address is not None:
        endpoint.ip_address = ip_address
    if owner_email is not None:
        endpoint.owner_email = owner_email
    if persona is not None:
        endpoint.persona = persona
    if criticality_tier is not None:
        endpoint.criticality_tier = criticality_tier
    if os_platform is not None:
        endpoint.os_platform = os_platform
    if tags is not None:
        endpoint.tags = tags
    if is_active is not None:
        endpoint.is_active = is_active
    db.commit()
    db.refresh(endpoint)
    return endpoint


def deregister_endpoint(db: Session, hostname: str) -> bool:
    """Soft-delete an endpoint by marking it inactive. Returns True if found."""
    endpoint = db.query(Endpoint).filter(Endpoint.hostname == hostname).first()
    if not endpoint:
        return False
    endpoint.is_active = False
    db.commit()
    logger.info("DEX: deregistered endpoint hostname=%s", hostname)
    return True


def touch_last_scanned(db: Session, hostname: str) -> None:
    """Update last_scanned_at to now for an endpoint (called after each telemetry scan)."""
    endpoint = db.query(Endpoint).filter(Endpoint.hostname == hostname).first()
    if endpoint:
        endpoint.last_scanned_at = datetime.now(timezone.utc)
        db.commit()
