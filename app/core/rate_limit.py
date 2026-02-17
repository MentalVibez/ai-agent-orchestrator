"""Rate limiting middleware."""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

# Rate limit configuration (requests per minute)
# Can be overridden via environment variable
RATE_LIMIT_PER_MINUTE = int(getattr(settings, "rate_limit_per_minute", 60))


def get_rate_limit():
    """Get rate limit from settings or default."""
    return getattr(settings, "rate_limit_per_minute", 60)
