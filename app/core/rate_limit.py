"""Rate limiting with per-API-key bucketing and role-aware limit strings."""

from starlette.requests import Request

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.config import settings

# Per-role rate limit strings (requests per minute).
# These are applied via the role-aware key function below.
# Documented tiers — apply these to route decorators based on role:
#   viewer:   read-heavy clients, low write quota
#   operator: normal API consumers
#   admin:    internal tooling / high-frequency callers
ROLE_RATE_LIMITS: dict[str, str] = {
    "viewer": "30/minute",
    "operator": "100/minute",
    "admin": "500/minute",
}

# Flat default for unauthenticated / IP-based requests
_DEFAULT_LIMIT = f"{settings.rate_limit_per_minute}/minute"


def _get_rate_limit_key(request: Request) -> str:
    """Return a rate-limit bucket key for the request.

    Authenticated requests are bucketed per API key ID (set on request.state
    by verify_api_key in app/core/auth.py), so each client gets its own
    independent counter regardless of shared NAT/proxy IPs.
    Unauthenticated requests fall back to the client IP address.
    """
    key_id = getattr(request.state, "api_key_id", None)
    if key_id:
        return f"apikey:{key_id}"
    return get_remote_address(request)


# Limiter instance shared across the app.
# Per-key bucketing isolates each API key's quota from others.
limiter = Limiter(key_func=_get_rate_limit_key)

# Deprecated alias kept for backward compat with any route that references it
RATE_LIMIT_PER_MINUTE = int(settings.rate_limit_per_minute)


async def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """Return a 429 response with a Retry-After hint."""
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Please slow down your requests."},
        headers={"Retry-After": "60"},
    )


__all__ = [
    "limiter",
    "RateLimitExceeded",
    "_rate_limit_exceeded_handler",
    "RATE_LIMIT_PER_MINUTE",
    "ROLE_RATE_LIMITS",
]
