"""API routes for orchestrator operations."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.auth import verify_api_key
from app.core.config import settings
from app.core.orchestrator import Orchestrator
from app.core.rate_limit import limiter
from app.core.services import get_service_container
from app.core.validation import validate_agent_ids, validate_context, validate_task
from app.core.workflow_executor import WorkflowExecutor
from app.models.request import (
    OrchestrateRequest,
    OrchestrateResponse,
    WorkflowExecuteRequest,
    WorkflowExecuteResponse,
)

logger = logging.getLogger(__name__)

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
    orchestrator: Orchestrator = Depends(get_orchestrator),
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

        # Get request ID for cost tracking
        request_id = getattr(request.state, "request_id", None)

        # Route task to appropriate agent(s)
        if agent_ids:
            # Use specific agents if provided
            results = await orchestrator.coordinate_agents(
                agent_ids=agent_ids, task=task, context=context
            )

            # Track costs with endpoint context
            from app.core.cost_tracker import get_cost_tracker

            cost_tracker = get_cost_tracker()
            for result in results:
                # Update cost records with endpoint and request_id
                recent_records = cost_tracker.get_recent_records(limit=len(results))
                for record in recent_records:
                    if not record.endpoint:
                        record.endpoint = "/api/v1/orchestrate"
                    if not record.request_id and request_id:
                        record.request_id = request_id

            return OrchestrateResponse(
                success=all(r.success for r in results),
                results=results,
                message=f"Task executed by {len(results)} agent(s)",
            )
        else:
            # Auto-route to appropriate agent
            result = await orchestrator.route_task(task=task, context=context)

            # Track cost with endpoint context
            from app.core.cost_tracker import get_cost_tracker

            cost_tracker = get_cost_tracker()
            recent_records = cost_tracker.get_recent_records(limit=1)
            if recent_records:
                record = recent_records[0]
                record.endpoint = "/api/v1/orchestrate"
                if request_id:
                    record.request_id = request_id

            return OrchestrateResponse(
                success=result.success,
                results=[result],
                message="Task executed successfully" if result.success else "Task execution failed",
            )

    except HTTPException:
        raise
    except Exception:
        logger.exception("Orchestrate task failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/workflows", response_model=WorkflowExecuteResponse)
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def execute_workflow(
    request: Request,
    workflow_request: WorkflowExecuteRequest,
    api_key: str = Depends(verify_api_key),
    executor: WorkflowExecutor = Depends(get_workflow_executor),
) -> WorkflowExecuteResponse:
    """
    Execute a predefined workflow.

    Args:
        request: Workflow execution request
        workflow_request: Workflow execution request with workflow_id and input_data
        api_key: Verified API key
        executor: Workflow executor instance

    Returns:
        WorkflowExecuteResponse with workflow execution results
    """
    try:
        # Load workflow definition
        from app.core.workflow_loader import get_workflow_loader

        workflow_loader = get_workflow_loader()
        workflow = workflow_loader.get_workflow(workflow_request.workflow_id)

        if not workflow:
            raise HTTPException(
                status_code=404, detail=f"Workflow '{workflow_request.workflow_id}' not found"
            )

        if not workflow.enabled:
            raise HTTPException(
                status_code=400, detail=f"Workflow '{workflow_request.workflow_id}' is disabled"
            )

        # Execute workflow
        result = await executor.execute(workflow=workflow, input_data=workflow_request.input_data)

        return WorkflowExecuteResponse(
            success=result.success,
            result=result,
            message="Workflow executed successfully"
            if result.success
            else "Workflow execution failed",
        )

    except HTTPException:
        raise
    except Exception:
        logger.exception("Workflow execution failed")
        raise HTTPException(status_code=500, detail="Internal server error")
