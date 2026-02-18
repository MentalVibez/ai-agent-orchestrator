"""API routes for agent management."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.agent_registry import AgentRegistry
from app.core.auth import verify_api_key
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.services import get_service_container
from app.models.agent import AgentInfo
from app.models.request import AgentDetailResponse, AgentsListResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["agents"])


def get_agent_registry() -> AgentRegistry:
    """
    Dependency to get agent registry instance.

    Returns:
        AgentRegistry instance
    """
    container = get_service_container()
    return container.get_agent_registry()


@router.get("/agents", response_model=AgentsListResponse)
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def list_agents(
    request: Request,
    api_key: str = Depends(verify_api_key),
    registry: AgentRegistry = Depends(get_agent_registry),
) -> AgentsListResponse:
    """
    List all available agents.

    Args:
        request: FastAPI request object
        api_key: Verified API key
        registry: Agent registry instance

    Returns:
        AgentsListResponse with list of agents
    """
    try:
        agents = registry.get_all()
        agent_infos = [
            AgentInfo(
                agent_id=agent.agent_id,
                name=agent.name,
                description=agent.description,
                capabilities=agent.get_capabilities(),
            )
            for agent in agents
        ]
        return AgentsListResponse(agents=agent_infos, count=len(agent_infos))
    except Exception:
        logger.exception("Failed to list agents")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/agents/{agent_id}", response_model=AgentDetailResponse)
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def get_agent(
    request: Request,
    agent_id: str,
    api_key: str = Depends(verify_api_key),
    registry: AgentRegistry = Depends(get_agent_registry),
) -> AgentDetailResponse:
    """
    Get details for a specific agent.

    Args:
        request: FastAPI request object
        agent_id: Agent identifier
        api_key: Verified API key
        registry: Agent registry instance

    Returns:
        AgentDetailResponse with agent information

    Raises:
        HTTPException: If agent is not found
    """
    try:
        agent = registry.get(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

        agent_info = AgentInfo(
            agent_id=agent.agent_id,
            name=agent.name,
            description=agent.description,
            capabilities=agent.get_capabilities(),
        )
        return AgentDetailResponse(agent=agent_info)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to get agent details")
        raise HTTPException(status_code=500, detail="Internal server error")
