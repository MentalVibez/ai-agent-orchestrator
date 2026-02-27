"""Main FastAPI application entry point."""

import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1.routes import agents, api_keys, metrics, orchestrator, runs, webhooks
from app.api.v1.routes import rag as rag_routes
from app.core.auth import verify_metrics_token
from app.core.config import settings
from app.core.exceptions import (
    AgentError,
    LLMProviderError,
    OrchestratorError,
    ServiceUnavailableError,
    ValidationError,
)
from app.core.logging_config import configure_logging
from app.core.rate_limit import RateLimitExceeded, _rate_limit_exceeded_handler, limiter
from app.core.services import get_service_container
from app.middleware.graceful_shutdown import GracefulShutdownMiddleware
from app.middleware.request_id import RequestIDMiddleware
from app.models.request import HealthResponse

# Configure structured logging with secrets redaction
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events.

    Args:
        app: FastAPI application instance
    """
    # Startup
    try:
        logger.info("Starting AI Agent Orchestrator...")
        logger.info(f"Version: {settings.app_version}")
        logger.info(f"LLM Provider: {settings.llm_provider}")
        logger.info(f"Debug Mode: {settings.debug}")

        # Warn if running SQLite in a non-debug (production-like) environment
        from app.db.database import DATABASE_URL as _db_url

        if "sqlite" in _db_url.lower() and not settings.debug:
            logger.warning(
                "SQLite is configured as the database but DEBUG=False. "
                "SQLite is not suitable for production (single writer, no horizontal scaling). "
                "Set DATABASE_URL to a PostgreSQL connection string for production deployments."
            )

        # Initialize service container (this will initialize all services)
        container = get_service_container()
        container.initialize()
        # Store on app.state so FastAPI Depends() can inject it without the global
        app.state.container = container

        # Log initialized services
        agent_registry = container.get_agent_registry()
        agents_list = agent_registry.get_all()
        logger.info(f"Initialized {len(agents_list)} agent(s): {[a.agent_id for a in agents_list]}")

        # Initialize MCP client manager (connects to enabled MCP servers from config)
        try:
            from app.mcp.client_manager import get_mcp_client_manager
            from app.mcp.config_loader import get_agent_profile, get_enabled_mcp_servers

            mcp_manager = get_mcp_client_manager()
            mcp_connected = await mcp_manager.initialize()
            if mcp_connected:
                logger.info(
                    "MCP client manager connected to %d server(s)", len(mcp_manager._sessions)
                )
                # Warn if default profile has no MCP servers listed (runs will use legacy orchestrator only)
                default_profile = get_agent_profile("default")
                enabled_servers = get_enabled_mcp_servers()
                if (
                    default_profile is not None
                    and enabled_servers
                    and not default_profile.get("allowed_mcp_servers")
                ):
                    logger.warning(
                        "Default agent profile has no allowed_mcp_servers configured. "
                        "POST /run will fail — runs require MCP tools. Add MCP server IDs to "
                        "config/agent_profiles.yaml (default.allowed_mcp_servers) to use MCP tools."
                    )
        except Exception as e:
            logger.warning("MCP client manager init skipped or failed: %s", e)

        logger.info("Startup complete - API ready to accept requests")
    except Exception as e:
        logger.error(f"Startup failed: {str(e)}", exc_info=True)
        raise

    yield

    # Shutdown
    try:
        logger.info("Shutting down AI Agent Orchestrator...")

        # Shutdown MCP client manager
        try:
            from app.mcp.client_manager import get_mcp_client_manager

            await get_mcp_client_manager().shutdown()
        except Exception as e:
            logger.warning("MCP client manager shutdown failed: %s", e)

        # Shutdown service container
        container = get_service_container()
        container.shutdown()

        # Close run queue Redis pool if used
        try:
            from app.core.run_queue import close_pool

            await close_pool()
        except Exception as e:
            logger.warning("Run queue pool close failed: %s", e)

        logger.info("Shutdown complete")
    except Exception as e:
        logger.error(f"Error during shutdown: {str(e)}", exc_info=True)


# Initialize FastAPI application — disable interactive docs in production
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Multi-agent AI orchestrator for IT diagnostics and engineering workflows",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan,
)

# Add rate limiter to app state
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log all requests and responses."""

    async def dispatch(self, request: Request, call_next):
        # Generate request ID for correlation
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id

        # Log request
        start_time = time.time()
        logger.info(
            f"Request [{request_id}]: {request.method} {request.url.path} - "
            f"Client: {request.client.host if request.client else 'unknown'}"
        )

        try:
            response = await call_next(request)

            # Calculate duration
            duration = time.time() - start_time

            # Log response
            logger.info(
                f"Response [{request_id}]: {request.method} {request.url.path} - "
                f"Status: {response.status_code} - Duration: {duration:.3f}s"
            )

            # Add request ID to response header
            response.headers["X-Request-ID"] = request_id

            # Record metrics
            try:
                from app.core.metrics import record_http_request

                record_http_request(
                    method=request.method,
                    endpoint=request.url.path,
                    status_code=response.status_code,
                    duration=duration,
                )
            except Exception:
                pass  # Don't fail on metrics errors

            return response
        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                f"Error [{request_id}]: {request.method} {request.url.path} - "
                f"Duration: {duration:.3f}s - Error: {str(e)}",
                exc_info=True,
            )
            raise


# Global exception handlers
@app.exception_handler(OrchestratorError)
async def orchestrator_exception_handler(request: Request, exc: OrchestratorError):
    """Handle orchestrator exceptions."""
    logger.error(
        f"OrchestratorError [{getattr(request.state, 'request_id', 'unknown')}]: "
        f"{exc.error_code} - {exc.message}",
        exc_info=True,
        extra={"error_code": exc.error_code, "details": exc.details},
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": exc.error_code,
                "message": exc.message,
                "details": exc.details,
                "recovery_hint": exc.recovery_hint,
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


@app.exception_handler(AgentError)
async def agent_exception_handler(request: Request, exc: AgentError):
    """Handle agent exceptions."""
    logger.error(
        f"AgentError [{getattr(request.state, 'request_id', 'unknown')}]: "
        f"Agent {exc.agent_id} - {exc.message}",
        exc_info=True,
        extra={"agent_id": exc.agent_id, "details": exc.details},
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": exc.error_code,
                "message": exc.message,
                "agent_id": exc.agent_id,
                "details": exc.details,
                "recovery_hint": exc.recovery_hint,
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


@app.exception_handler(LLMProviderError)
async def llm_provider_exception_handler(request: Request, exc: LLMProviderError):
    """Handle LLM provider exceptions."""
    logger.error(
        f"LLMProviderError [{getattr(request.state, 'request_id', 'unknown')}]: "
        f"Provider {exc.provider} - {exc.message}",
        exc_info=True,
        extra={"provider": exc.provider, "details": exc.details},
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "error": {
                "code": exc.error_code,
                "message": exc.message,
                "provider": exc.provider,
                "details": exc.details,
                "recovery_hint": exc.recovery_hint,
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    """Handle validation exceptions."""
    logger.warning(
        f"ValidationError [{getattr(request.state, 'request_id', 'unknown')}]: "
        f"Field {exc.field} - {exc.message}",
        extra={"field": exc.field, "details": exc.details},
    )
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": {
                "code": exc.error_code,
                "message": exc.message,
                "field": exc.field,
                "details": exc.details,
                "recovery_hint": exc.recovery_hint,
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


@app.exception_handler(ServiceUnavailableError)
async def service_unavailable_exception_handler(request: Request, exc: ServiceUnavailableError):
    """Handle service unavailable exceptions."""
    logger.error(
        f"ServiceUnavailableError [{getattr(request.state, 'request_id', 'unknown')}]: "
        f"Service {exc.service} - {exc.message}",
        extra={"service": exc.service, "details": exc.details},
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "error": {
                "code": exc.error_code,
                "message": exc.message,
                "service": exc.service,
                "details": exc.details,
                "recovery_hint": exc.recovery_hint,
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle all other exceptions."""
    request_id = getattr(request.state, "request_id", "unknown")
    logger.error(
        f"UnhandledException [{request_id}]: {type(exc).__name__} - {str(exc)}", exc_info=True
    )

    if settings.debug:
        error_message = str(exc)
    else:
        error_message = "An internal error occurred. Please try again later."

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": error_message,
                "recovery_hint": (
                    "Retry your request. If the problem persists, contact support "
                    "and include the request_id from this response."
                ),
                "request_id": request_id,
            }
        },
    )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to add security headers to responses."""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # Only send HSTS when actually running over HTTPS to avoid breaking HTTP dev setups
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
            "img-src 'self' data:; "
            "font-src 'self' cdn.jsdelivr.net"
        )

        return response


# Deprecation header map: path_prefix → (Sunset RFC 1123 date, migration URL)
# Populate when a route family enters the Deprecated lifecycle phase.
# Example:  "/api/v1/legacy": ("Sat, 01 Jan 2028 00:00:00 GMT", "https://docs.example.com/migration")
_DEPRECATED_PREFIXES: dict[str, tuple[str, str]] = {}


class ApiVersionHeadersMiddleware(BaseHTTPMiddleware):
    """Adds API-Version, Deprecation, and Sunset headers per route.

    Per the versioning policy (docs/API_VERSIONING.md):
      - All responses carry X-API-Version so clients can detect version mismatches.
      - Deprecated route families also carry Deprecation and Sunset headers.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-API-Version"] = settings.app_version
        for prefix, (sunset, link) in _DEPRECATED_PREFIXES.items():
            if request.url.path.startswith(prefix):
                response.headers["Deprecation"] = "true"
                response.headers["Sunset"] = sunset
                response.headers["Link"] = f'<{link}>; rel="deprecation"'
                break
        return response


# Add middleware (order matters — outermost first, innermost last)
# GracefulShutdown is outermost so it can reject new requests during drain
app.add_middleware(GracefulShutdownMiddleware)
app.add_middleware(ApiVersionHeadersMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# Configure CORS — narrow methods/headers to reduce attack surface
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["X-API-Key", "Content-Type", "Accept"],
)

# Include API routers
app.include_router(orchestrator.router)
app.include_router(agents.router)
app.include_router(metrics.router)
app.include_router(runs.router)
app.include_router(webhooks.router)
app.include_router(api_keys.router)
# RAG routes are always registered; individual endpoints return 503 if chromadb is not installed
app.include_router(rag_routes.router)


@app.get("/", tags=["root"])
async def root():
    """
    Root endpoint.

    Returns:
        Welcome message
    """
    return {
        "message": "AI Agent Orchestrator API",
        "version": settings.app_version,
        "docs": "/docs",
        "console": "/console",
    }


@app.get("/console", tags=["ui"])
async def console():
    """Serve the Personal Multi-Agent Console (goal + profile, run status, steps, answer)."""
    path = Path(__file__).resolve().parent.parent / "examples" / "console.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Console not found")
    return FileResponse(path, media_type="text/html")


@app.get("/metrics", tags=["monitoring"])
@limiter.limit("30/minute")
async def prometheus_metrics(
    request: Request,
    _auth: None = Depends(verify_metrics_token),
):
    """
    Prometheus scrape endpoint.
    Auth: set METRICS_TOKEN and configure Prometheus with bearer_token = <value>.
    If METRICS_TOKEN is not set, falls back to X-API-Key verification.
    """
    from app.core.metrics import get_metrics

    return Response(
        content=get_metrics(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


def _check_database_liveness() -> bool:
    """Verify the database is reachable with a lightweight query."""
    try:
        from sqlalchemy import text

        from app.db.database import SessionLocal

        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            return True
        finally:
            db.close()
    except Exception as e:
        logger.warning("Health check: database liveness check failed: %s", e)
        return False


@app.get("/api/v1/health", response_model=HealthResponse, tags=["health"])
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def health_check(request: Request) -> HealthResponse:
    """
    Health check endpoint that verifies actual system functionality.

    Checks:
    - Agent registry (agents registered)
    - Database liveness (SELECT 1)
    - LLM provider initialization
    - MCP connection status (optional)

    Returns:
        HealthResponse with status: healthy | degraded | unhealthy
    """
    try:
        container = request.app.state.container
        agent_registry = container.get_agent_registry()
        agents_list = agent_registry.get_all()
        agents_count = len(agents_list)

        issues = []

        # Check agent registry
        if agents_count == 0:
            issues.append("No agents registered")

        # Check database liveness
        db_ok = _check_database_liveness()
        if not db_ok:
            issues.append("Database not reachable")

        # Check LLM provider is initialized
        llm_ok = False
        try:
            llm_manager = container.get_llm_manager()
            provider = llm_manager.get_provider() if llm_manager else None
            llm_ok = provider is not None
        except Exception as e:
            logger.warning("Health check: LLM provider unavailable: %s", e)
        if not llm_ok:
            issues.append("LLM provider not initialized")

        # Optional: MCP connection status
        mcp_connected = None
        try:
            from app.mcp.client_manager import get_mcp_client_manager

            mcp_connected = get_mcp_client_manager().is_connected()
        except Exception:
            pass

        # Circuit breaker states — open breaker means LLM is unreachable
        try:
            from app.core.circuit_breaker import is_llm_breaker_open

            if is_llm_breaker_open():
                issues.append("LLM circuit breaker is OPEN (downstream failing)")
        except Exception:
            pass

        # Determine overall status
        if "Database not reachable" in issues or "No agents registered" in issues:
            overall_status = "unhealthy"
        elif issues:
            overall_status = "degraded"
        else:
            overall_status = "healthy"

        if issues:
            logger.warning("Health check issues: %s", issues)

        return HealthResponse(
            status=overall_status,
            version=settings.app_version,
            timestamp=datetime.now(timezone.utc).isoformat(),
            mcp_connected=mcp_connected,
        )
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}", exc_info=True)
        return HealthResponse(
            status="unhealthy",
            version=settings.app_version,
            timestamp=datetime.now(timezone.utc).isoformat(),
            mcp_connected=None,
        )


# Startup and shutdown are now handled by lifespan context manager above


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)
