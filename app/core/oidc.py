"""OIDC JWT resource-server validation.

When OIDC_ENABLED=True, Bearer tokens issued by an external IdP (Okta,
Azure AD, Google Workspace, etc.) are validated here before the X-API-Key
path in auth.py is attempted.

JWKS keys are cached in-process for OIDC_JWKS_CACHE_TTL seconds (default
86400 = 24 h). The cache is refreshed lazily on the next request after TTL
expires. On fetch failure, stale keys are served if available so that a
temporary IdP outage does not take down the API. A HTTP 503 is only raised
when there are no cached keys at all.
"""

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JWKS cache (module-level, thread-safe)
# ---------------------------------------------------------------------------

_cache_lock = threading.Lock()
_jwks_keys: list[dict] = []
_jwks_fetched_at: datetime | None = None


def _is_cache_fresh() -> bool:
    from app.core.config import settings

    if _jwks_fetched_at is None:
        return False
    age = (datetime.now(timezone.utc) - _jwks_fetched_at).total_seconds()
    return age < settings.oidc_jwks_cache_ttl


async def _fetch_jwks() -> list[dict]:
    """Fetch the JWKS from the configured IdP endpoint."""
    from app.core.config import settings

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(settings.oidc_jwks_uri)
        resp.raise_for_status()
        data = resp.json()
        return data.get("keys", [])


async def _get_jwks() -> list[dict]:
    """Return cached JWKS keys, refreshing if stale."""
    global _jwks_keys, _jwks_fetched_at

    with _cache_lock:
        if _is_cache_fresh():
            return list(_jwks_keys)

    # Fetch outside the lock so other threads are not blocked waiting for HTTP
    try:
        new_keys = await _fetch_jwks()
        with _cache_lock:
            _jwks_keys = new_keys
            _jwks_fetched_at = datetime.now(timezone.utc)
        return list(new_keys)
    except Exception as exc:
        logger.warning("oidc: JWKS refresh failed — %s", exc)
        with _cache_lock:
            if _jwks_keys:
                logger.warning("oidc: serving stale JWKS cache (%d keys)", len(_jwks_keys))
                return list(_jwks_keys)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC JWKS fetch failed and no cached keys are available.",
        )


# ---------------------------------------------------------------------------
# Role mapping
# ---------------------------------------------------------------------------


def _map_role(claims: dict[str, Any]) -> str:
    """Map OIDC role claim values to viewer/operator/admin.

    Returns the highest-privilege role found, or 'viewer' if no match.
    """
    from app.core.api_keys import ROLE_ORDER
    from app.core.config import settings

    try:
        role_map: dict = json.loads(settings.oidc_role_map) if settings.oidc_role_map else {}
    except json.JSONDecodeError:
        logger.warning("oidc: OIDC_ROLE_MAP is not valid JSON — defaulting to viewer for all tokens")
        role_map = {}

    raw = claims.get(settings.oidc_role_claim, [])
    if isinstance(raw, str):
        raw = [raw]

    best_role = "viewer"
    for claim_val in raw:
        mapped = role_map.get(str(claim_val))
        if mapped and ROLE_ORDER.get(mapped, -1) > ROLE_ORDER.get(best_role, -1):
            best_role = mapped

    return best_role


# ---------------------------------------------------------------------------
# Token validation
# ---------------------------------------------------------------------------


async def verify_oidc_token(request: Request, raw_token: str) -> str:
    """Validate a Bearer JWT and populate request.state.

    Raises HTTPException on any validation failure.
    Returns the raw token string on success (parallel to verify_api_key).
    """
    import jwt
    from jwt.exceptions import InvalidTokenError

    from app.core.config import settings

    keys = await _get_jwks()

    # Decode the header to find the signing key by kid
    try:
        header = jwt.get_unverified_header(raw_token)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid JWT header: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    kid = header.get("kid")
    matching_key = None
    for k in keys:
        if kid and k.get("kid") == kid:
            try:
                matching_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(k))
            except Exception:
                continue
            break

    if matching_key is None and keys:
        # Fallback: try the first key for IdPs that omit kid
        try:
            matching_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(keys[0]))
        except Exception:
            pass

    if matching_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No matching JWKS key found for this token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    decode_options: dict[str, Any] = {}
    if not settings.oidc_audience:
        decode_options["verify_aud"] = False

    try:
        claims: dict[str, Any] = jwt.decode(
            raw_token,
            matching_key,
            algorithms=["RS256", "RS384", "RS512"],
            audience=settings.oidc_audience or None,
            issuer=settings.oidc_issuer or None,
            options=decode_options,
        )
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"JWT validation failed: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    sub = claims.get("sub", "oidc-unknown")
    role = _map_role(claims)

    request.state.api_key_id = f"oidc:{sub}"
    request.state.api_key_role = role
    logger.debug("oidc: token validated for sub=%s mapped_role=%s", sub, role)
    return raw_token
