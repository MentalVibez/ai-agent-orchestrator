"""Main FastAPI application entry point."""

import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1.routes import agents, metrics, orchestrator, runs
from app.core.config import settings
from app.core.exceptions import (
    AgentError,
    LLMProviderError,
    OrchestratorError,
    ServiceUnavailableError,
    ValidationError,
)
from app.core.rate_limit import RateLimitExceeded, _rate_limit_exceeded_handler, limiter
from app.core.services import get_service_container
from app.models.request import HealthResponse

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
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

        # Initialize service container (this will initialize all services)
        container = get_service_container()
        container.initialize()

        # Log initialized services
        agent_registry = container.get_agent_registry()
        agents_list = agent_registry.get_all()
        logger.info(f"Initialized {len(agents_list)} agent(s): {[a.agent_id for a in agents_list]}")

        # Initialize MCP client manager (connects to enabled MCP servers from config)
        try:
            from app.mcp.client_manager import get_mcp_client_manager

            mcp_manager = get_mcp_client_manager()
            mcp_connected = await mcp_manager.initialize()
            if mcp_connected:
                logger.info(
                    "MCP client manager connected to %d server(s)", len(mcp_manager._sessions)
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

        logger.info("Shutdown complete")
    except Exception as e:
        logger.error(f"Error during shutdown: {str(e)}", exc_info=True)


# Initialize FastAPI application
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Multi-agent AI orchestrator for IT diagnostics and engineering workflows",
    docs_url="/docs",
    redoc_url="/redoc",
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

    # Don't expose internal errors in production
    if settings.debug:
        error_message = str(exc)
    else:
        error_message = "An internal error occurred. Please try again later."

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {"code": "INTERNAL_ERROR", "message": error_message, "request_id": request_id}
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
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'"

        return response


# Add middleware (order matters - logging first, then security)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(orchestrator.router)
app.include_router(agents.router)
app.include_router(metrics.router)
app.include_router(runs.router)


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


@app.get("/api/v1/health", response_model=HealthResponse, tags=["health"])
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def health_check(request: Request) -> HealthResponse:
    """
    Health check endpoint with dependency validation.

    Returns:
        HealthResponse with status information
    """
    try:
        # Check if services are initialized
        container = get_service_container()
        agent_registry = container.get_agent_registry()
        agents = agent_registry.get_all()
        agents_count = len(agents)

        # Check agent registry
        if agents_count == 0:
            logger.warning("Health check: No agents registered")
            return HealthResponse(
                status="degraded",
                version=settings.app_version,
                timestamp=datetime.utcnow().isoformat(),
                mcp_connected=None,
            )

        # Check LLM provider (basic check - try to get provider)
        try:
            llm_manager = container._llm_manager
            if llm_manager:
                # Provider is initialized
                pass
        except Exception as e:
            logger.warning(f"Health check: LLM provider check failed: {str(e)}")
            return HealthResponse(
                status="degraded",
                version=settings.app_version,
                timestamp=datetime.utcnow().isoformat(),
                mcp_connected=None,
            )

        # Optional: MCP connection status
        mcp_connected = None
        try:
            from app.mcp.client_manager import get_mcp_client_manager

            mcp_connected = get_mcp_client_manager().is_connected()
        except Exception:
            pass

        status = "healthy"
        return HealthResponse(
            status=status,
            version=settings.app_version,
            timestamp=datetime.utcnow().isoformat(),
            mcp_connected=mcp_connected,
        )
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}", exc_info=True)
        return HealthResponse(
            status="unhealthy",
            version=settings.app_version,
            timestamp=datetime.utcnow().isoformat(),
            mcp_connected=None,
        )


# Startup and shutdown are now handled by lifespan context manager above


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)
