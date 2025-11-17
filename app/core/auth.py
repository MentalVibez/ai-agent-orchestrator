"""Authentication and authorization middleware."""

from fastapi import Security, HTTPException, status
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
    # Check if API key is required
    require_key = getattr(settings, 'require_api_key', True)
    
    # Get API key from environment variable
    expected_api_key = getattr(settings, 'api_key', None)
    
    # If API key is not required or not configured, allow access
    if not require_key or not expected_api_key:
        return api_key or "no-key-required"
    
    # Verify the API key
    if not api_key or api_key != expected_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Please provide a valid X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    
    return api_key

