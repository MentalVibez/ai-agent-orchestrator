"""Idempotency key store: prevents duplicate runs from network retries.

Usage
-----
Client sends  ``Idempotency-Key: <uuid>``  with POST /run.
- First request: creates the run, stores key → run_id mapping (24 h TTL).
- Subsequent requests with the same key: returns the existing run_id (409 is NOT raised;
  the original response body is reconstructed so the client sees a clean 201-equivalent).

The TTL is advisory (we keep records indefinitely in SQLite/Postgres and rely on the
client to generate fresh keys for genuinely new runs after 24 h).
"""

import logging
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import IdempotencyRecord

logger = logging.getLogger(__name__)

# Maximum key length accepted from clients
MAX_KEY_LENGTH = 256


def validate_idempotency_key(key: str) -> str:
    """Sanitise and validate a client-supplied idempotency key."""
    key = key.strip()
    if not key:
        raise ValueError("Idempotency-Key header must not be empty.")
    if len(key) > MAX_KEY_LENGTH:
        raise ValueError(f"Idempotency-Key must be ≤ {MAX_KEY_LENGTH} characters.")
    # Only printable ASCII to avoid header injection
    if not key.isprintable() or any(c in key for c in ("\r", "\n")):
        raise ValueError("Idempotency-Key must contain only printable ASCII characters.")
    return key


def get_existing_run_id(db: Session, idempotency_key: str) -> Optional[str]:
    """Return the run_id for a previously seen idempotency key, or None."""
    record = (
        db.query(IdempotencyRecord)
        .filter(IdempotencyRecord.idempotency_key == idempotency_key)
        .first()
    )
    return record.run_id if record else None


def store_idempotency_key(db: Session, idempotency_key: str, run_id: str) -> bool:
    """Persist the key → run_id mapping.

    Returns True on success, False if the key already exists (race condition).
    """
    record = IdempotencyRecord(idempotency_key=idempotency_key, run_id=run_id)
    db.add(record)
    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        logger.debug("Idempotency key '%s' already exists (race condition)", idempotency_key)
        return False
