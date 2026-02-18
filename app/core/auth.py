"""Authentication and authorization middleware."""

import hmac

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.core.config import settings

# API Key header name
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(API_KEY_HEADER)) -> str:
    """
    Verify API key from request header.

    Args:
        api_key: API key from X-API-Key header

    Returns:
        The verified API key

    Raises:
        HTTPException: If API key is missing or invalid
    """
    require_key = getattr(settings, "require_api_key", True)
    expected_api_key = getattr(settings, "api_key", None)

    # If auth is disabled via config, allow all traffic
    if not require_key:
        return api_key or "no-key-required"

    # When auth is required but no key is configured, deny all traffic.
    # This prevents silent open-door deployments where REQUIRE_API_KEY=true
    # but API_KEY was never set.
    if not expected_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API key authentication is enabled but no API_KEY is configured on the server.",
        )

    # Constant-time comparison to prevent timing oracle attacks
    if not api_key or not hmac.compare_digest(api_key, expected_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Please provide a valid X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return api_key
