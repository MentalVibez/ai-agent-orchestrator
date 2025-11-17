"""API routes for agent management."""

from fastapi import APIRouter, HTTPException, Depends
from typing import List
from app.models.request import AgentsListResponse, AgentDetailResponse
from app.models.agent import AgentInfo
from app.core.agent_registry import AgentRegistry


router = APIRouter(prefix="/api/v1", tags=["agents"])


def get_agent_registry() -> AgentRegistry:
    """
    Dependency to get agent registry instance.

    Returns:
        AgentRegistry instance
    """
    # TODO: Implement dependency injection for agent registry
    # This should retrieve the registry from application state
    raise NotImplementedError("get_agent_registry dependency must be implemented")


@router.get("/agents", response_model=AgentsListResponse)
async def list_agents(
    registry: AgentRegistry = Depends(get_agent_registry)
) -> AgentsListResponse:
    """
    List all available agents.

    Args:
        registry: Agent registry instance

    Returns:
        AgentsListResponse with list of agents
    """
    # TODO: Implement agents listing endpoint
    # 1. Get all agents from registry
    # 2. Convert to AgentInfo models
    # 3. Return formatted response
    raise NotImplementedError("list_agents endpoint must be implemented")


@router.get("/agents/{agent_id}", response_model=AgentDetailResponse)
async def get_agent(
    agent_id: str,
    registry: AgentRegistry = Depends(get_agent_registry)
) -> AgentDetailResponse:
    """
    Get details for a specific agent.

    Args:
        agent_id: Agent identifier
        registry: Agent registry instance

    Returns:
        AgentDetailResponse with agent information

    Raises:
        HTTPException: If agent is not found
    """
    # TODO: Implement agent detail endpoint
    # 1. Get agent from registry by ID
    # 2. If not found, raise HTTPException with 404
    # 3. Convert to AgentInfo model
    # 4. Return formatted response
    raise NotImplementedError("get_agent endpoint must be implemented")

