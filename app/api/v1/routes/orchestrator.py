"""API routes for orchestrator operations."""

from fastapi import APIRouter, HTTPException, Depends, Request
from typing import Any
from app.models.request import (
    OrchestrateRequest,
    OrchestrateResponse,
    WorkflowExecuteRequest,
    WorkflowExecuteResponse
)
from app.core.orchestrator import Orchestrator
from app.core.workflow_executor import WorkflowExecutor
from app.core.auth import verify_api_key
from app.core.rate_limit import limiter
from app.core.config import settings
from app.core.services import get_service_container
from app.core.validation import validate_task, validate_context, validate_agent_ids


router = APIRouter(prefix="/api/v1", tags=["orchestrator"])


def get_orchestrator() -> Orchestrator:
    """
    Dependency to get orchestrator instance.

    Returns:
        Orchestrator instance
    """
    container = get_service_container()
    return container.get_orchestrator()


def get_workflow_executor() -> WorkflowExecutor:
    """
    Dependency to get workflow executor instance.

    Returns:
        WorkflowExecutor instance
    """
    container = get_service_container()
    return container.get_workflow_executor()


@router.post("/orchestrate", response_model=OrchestrateResponse)
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def orchestrate_task(
    request: Request,
    orchestrate_request: OrchestrateRequest,
    api_key: str = Depends(verify_api_key),
    orchestrator: Orchestrator = Depends(get_orchestrator)
) -> OrchestrateResponse:
    """
    Submit a task to the orchestrator for execution.

    Args:
        request: Orchestration request with task and context
        orchestrate_request: Request body with task and context
        api_key: Verified API key
        orchestrator: Orchestrator instance

    Returns:
        OrchestrateResponse with execution results
    """
    try:
        # Validate and sanitize input
        task = validate_task(orchestrate_request.task)
        context = validate_context(orchestrate_request.context)
        agent_ids = validate_agent_ids(orchestrate_request.agent_ids)
        
        # Route task to appropriate agent(s)
        if agent_ids:
            # Use specific agents if provided
            results = await orchestrator.coordinate_agents(
                agent_ids=agent_ids,
                task=task,
                context=context
            )
            return OrchestrateResponse(
                success=all(r.success for r in results),
                results=results,
                message=f"Task executed by {len(results)} agent(s)"
            )
        else:
            # Auto-route to appropriate agent
            result = await orchestrator.route_task(
                task=task,
                context=context
            )
            return OrchestrateResponse(
                success=result.success,
                results=[result],
                message="Task executed successfully" if result.success else "Task execution failed"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@router.post("/workflows", response_model=WorkflowExecuteResponse)
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def execute_workflow(
    request: Request,
    workflow_request: WorkflowExecuteRequest,
    api_key: str = Depends(verify_api_key),
    executor: WorkflowExecutor = Depends(get_workflow_executor)
) -> WorkflowExecuteResponse:
    """
    Execute a predefined workflow.

    Args:
        request: Workflow execution request
        executor: Workflow executor instance

    Returns:
        WorkflowExecuteResponse with workflow execution results
    """
    # TODO: Implement workflow execution endpoint
    # 1. Validate request
    # 2. Load workflow definition
    # 3. Call executor.execute
    # 4. Handle errors appropriately
    # 5. Return formatted response
    raise NotImplementedError("execute_workflow endpoint must be implemented")

