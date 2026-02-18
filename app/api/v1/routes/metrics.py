"""API routes for metrics and cost tracking."""

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.auth import verify_api_key
from app.core.config import settings
from app.core.cost_tracker import get_cost_tracker
from app.core.rate_limit import limiter
from app.models.metrics import CostMetrics, CostMetricsResponse, CostRecordResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["metrics"])


@router.get("/metrics/costs", response_model=CostMetricsResponse)
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def get_cost_metrics(
    request: Request,
    days: int = Query(default=7, ge=1, le=90, description="Number of days to analyze"),
    endpoint: Optional[str] = Query(None, description="Filter by endpoint"),
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    api_key: str = Depends(verify_api_key),
) -> CostMetricsResponse:
    """
    Get cost metrics and analytics.

    Args:
        request: FastAPI request object
        days: Number of days to analyze
        endpoint: Optional endpoint filter
        agent_id: Optional agent filter
        api_key: Verified API key

    Returns:
        CostMetricsResponse with cost analytics
    """
    try:
        cost_tracker = get_cost_tracker()

        # Calculate date range
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)

        # Get metrics
        total_cost = cost_tracker.get_total_cost(start_date, end_date)

        # Apply filters if provided
        if endpoint or agent_id:
            # Filter records manually
            cost_by_agent = cost_tracker.get_cost_by_agent(start_date, end_date)
            cost_by_endpoint = cost_tracker.get_cost_by_endpoint(start_date, end_date)

            if agent_id:
                cost_by_agent = {k: v for k, v in cost_by_agent.items() if k == agent_id}
            if endpoint:
                cost_by_endpoint = {k: v for k, v in cost_by_endpoint.items() if k == endpoint}
        else:
            cost_by_agent = cost_tracker.get_cost_by_agent(start_date, end_date)
            cost_by_endpoint = cost_tracker.get_cost_by_endpoint(start_date, end_date)

        token_usage = cost_tracker.get_token_usage(start_date, end_date)

        # Get recent records
        recent_records = cost_tracker.get_recent_records(limit=50)
        recent_records_response = [
            CostRecordResponse(
                timestamp=record.timestamp.isoformat(),
                provider=record.provider,
                model=record.model,
                input_tokens=record.input_tokens,
                output_tokens=record.output_tokens,
                total_tokens=record.total_tokens,
                cost=record.cost,
                agent_id=record.agent_id,
                endpoint=record.endpoint,
                request_id=record.request_id,
            )
            for record in recent_records
        ]

        metrics = CostMetrics(
            total_cost=total_cost,
            period_start=start_date.isoformat(),
            period_end=end_date.isoformat(),
            cost_by_agent=cost_by_agent,
            cost_by_endpoint=cost_by_endpoint,
            token_usage=token_usage,
        )

        return CostMetricsResponse(
            success=True,
            metrics=metrics,
            recent_records=recent_records_response,
            message=f"Cost metrics for last {days} days",
        )

    except Exception:
        logger.exception("Failed to retrieve cost metrics")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/metrics/costs/daily", response_model=CostMetricsResponse)
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def get_daily_cost(
    request: Request,
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format (default: today)"),
    endpoint: Optional[str] = Query(None, description="Filter by endpoint"),
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    api_key: str = Depends(verify_api_key),
) -> CostMetricsResponse:
    """
    Get daily cost metrics.

    Args:
        request: FastAPI request object
        date: Date to analyze (YYYY-MM-DD)
        endpoint: Optional endpoint filter
        agent_id: Optional agent filter
        api_key: Verified API key

    Returns:
        CostMetricsResponse with daily cost metrics
    """
    try:
        cost_tracker = get_cost_tracker()

        # Parse date
        if date:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
        else:
            target_date = datetime.utcnow().date()

        daily_cost = cost_tracker.get_daily_cost(
            date=target_date, endpoint=endpoint, agent_id=agent_id
        )

        # Get breakdowns
        start = datetime.combine(target_date, datetime.min.time())
        end = datetime.combine(target_date, datetime.max.time())

        cost_by_agent = cost_tracker.get_cost_by_agent(start, end)
        if agent_id:
            cost_by_agent = {k: v for k, v in cost_by_agent.items() if k == agent_id}

        cost_by_endpoint = cost_tracker.get_cost_by_endpoint(start, end)
        if endpoint:
            cost_by_endpoint = {k: v for k, v in cost_by_endpoint.items() if k == endpoint}

        token_usage = cost_tracker.get_token_usage(start, end)

        metrics = CostMetrics(
            total_cost=daily_cost,
            period_start=start.isoformat(),
            period_end=end.isoformat(),
            cost_by_agent=cost_by_agent,
            cost_by_endpoint=cost_by_endpoint,
            token_usage=token_usage,
        )

        return CostMetricsResponse(
            success=True,
            metrics=metrics,
            recent_records=[],
            message=f"Daily cost for {target_date}",
        )

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    except Exception:
        logger.exception("Failed to retrieve daily cost")
        raise HTTPException(status_code=500, detail="Internal server error")
