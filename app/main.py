"""Main FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from app.core.config import settings
from app.api.v1.routes import orchestrator, agents
from app.models.request import HealthResponse


# Initialize FastAPI application
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Multi-agent AI orchestrator for IT diagnostics and engineering workflows",
    docs_url="/docs",
    redoc_url="/redoc"
)

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
        "docs": "/docs"
    }


@app.get("/api/v1/health", response_model=HealthResponse, tags=["health"])
async def health_check() -> HealthResponse:
    """
    Health check endpoint.

    Returns:
        HealthResponse with status information
    """
    return HealthResponse(
        status="healthy",
        version=settings.app_version,
        timestamp=datetime.utcnow().isoformat()
    )


@app.on_event("startup")
async def startup_event():
    """
    Startup event handler.

    Initialize services, load agents, etc.
    """
    # TODO: Implement startup logic
    # 1. Initialize LLM manager and provider
    # 2. Initialize agent registry
    # 3. Register all agents
    # 4. Initialize orchestrator and workflow executor
    # 5. Load workflow definitions
    pass


@app.on_event("shutdown")
async def shutdown_event():
    """
    Shutdown event handler.

    Clean up resources, close connections, etc.
    """
    # TODO: Implement shutdown logic
    # 1. Clean up LLM connections
    # 2. Save agent states if needed
    # 3. Close any open connections
    pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )

