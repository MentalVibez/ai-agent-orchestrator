"""Authentication and authorization middleware.

Auth flow
---------
1. If REQUIRE_API_KEY=false — allow all (dev mode).
2. Check the DB key registry first (hashed comparison, tracks last_used_at).
3. If no DB match, fall back to the env-var API_KEY as a permanent admin bootstrap key.
   This lets you bootstrap the very first admin key without a chicken-and-egg problem.
4. If neither matches — 401.
5. If API_KEY is set to "" and REQUIRE_API_KEY=true and DB is empty — 503 (misconfigured).
"""

import hmac
import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from app.core.config import settings

logger = logging.getLogger(__name__)

# API Key header name
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def _check_env_key(raw_key: str) -> bool:
    """Constant-time comparison against the env-var bootstrap key."""
    expected = getattr(settings, "api_key", "")
    if not expected:
        return False
    return hmac.compare_digest(raw_key, expected)


async def verify_api_key(
    request: Request,
    api_key: str = Security(API_KEY_HEADER),
) -> str:
    """Verify API key from X-API-Key header.

    Returns the raw key string on success (used by RBAC helpers).
    Raises HTTPException on failure.
    """
    require_key = getattr(settings, "require_api_key", True)

    if not require_key:
        return api_key or "no-key-required"

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # --- DB key registry check ---
    try:
        from app.core.api_keys import lookup_api_key
        from app.db.database import SessionLocal

        db = SessionLocal()
        try:
            record = lookup_api_key(db, api_key)
            # Read attributes while the session is still open to avoid
            # DetachedInstanceError after db.close() expires them.
            if record:
                _role = record.role
                _key_id = record.key_id
            else:
                _role = None
                _key_id = None
        finally:
            db.close()

        if _role is not None:
            # Attach role info to request state for downstream RBAC checks
            request.state.api_key_role = _role
            request.state.api_key_id = _key_id
            return api_key
    except Exception as e:
        # DB unavailable — fall through to env-var check, log the error
        logger.warning("auth: DB key lookup failed, falling back to env key: %s", e)

    # --- Env-var bootstrap key (permanent admin) ---
    expected_api_key = getattr(settings, "api_key", "")
    if not expected_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "API key authentication is enabled but no API_KEY is configured "
                "and the key registry is empty or unreachable."
            ),
        )

    if not _check_env_key(api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Please provide a valid X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Env-var key is always admin
    request.state.api_key_role = "admin"
    request.state.api_key_id = "env-bootstrap"
    return api_key


def require_role(min_role: str):
    """FastAPI Depends factory: enforces minimum RBAC role after verify_api_key runs.

    Usage::

        @router.post("/admin/keys", dependencies=[Depends(verify_api_key), Depends(require_role("admin"))])
        async def create_key(...): ...
    """

    async def _check(request: Request) -> None:
        from app.core.api_keys import ROLE_ORDER

        role = getattr(request.state, "api_key_role", "viewer")
        if ROLE_ORDER.get(role, -1) < ROLE_ORDER.get(min_role, 999):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires '{min_role}' role. Your key has role '{role}'.",
            )

    return _check


async def verify_metrics_token(request: Request) -> None:
    """Separate auth for the Prometheus /metrics scrape endpoint.

    Checks METRICS_TOKEN env var. If not set, falls back to verify_api_key logic.
    Standard Prometheus scrapers can be configured with bearer_token or basic_auth;
    this endpoint accepts the token as X-Metrics-Token or Bearer token.
    """
    metrics_token: str = getattr(settings, "metrics_token", "")

    if not metrics_token:
        # Fall back to main API key verification
        await verify_api_key(request, request.headers.get("X-API-Key", ""))
        return

    # Check X-Metrics-Token header
    provided = request.headers.get("X-Metrics-Token", "")
    if not provided:
        # Also accept Authorization: Bearer <token>
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            provided = auth_header[7:]

    if not provided or not hmac.compare_digest(provided, metrics_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing metrics token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
