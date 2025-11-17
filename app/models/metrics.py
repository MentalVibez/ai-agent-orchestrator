"""Metrics models for API responses."""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class CostMetrics(BaseModel):
    """Cost metrics response model."""
    
    total_cost: float = Field(..., description="Total cost in USD")
    period_start: Optional[str] = Field(None, description="Period start timestamp")
    period_end: Optional[str] = Field(None, description="Period end timestamp")
    cost_by_agent: Dict[str, float] = Field(default_factory=dict, description="Cost breakdown by agent")
    cost_by_endpoint: Dict[str, float] = Field(default_factory=dict, description="Cost breakdown by endpoint")
    token_usage: Dict[str, int] = Field(default_factory=dict, description="Token usage statistics")


class CostRecordResponse(BaseModel):
    """Cost record response model."""
    
    timestamp: str = Field(..., description="Record timestamp")
    provider: str = Field(..., description="LLM provider")
    model: str = Field(..., description="Model identifier")
    input_tokens: int = Field(..., description="Input tokens")
    output_tokens: int = Field(..., description="Output tokens")
    total_tokens: int = Field(..., description="Total tokens")
    cost: float = Field(..., description="Cost in USD")
    agent_id: Optional[str] = Field(None, description="Agent ID")
    endpoint: Optional[str] = Field(None, description="Endpoint name")
    request_id: Optional[str] = Field(None, description="Request ID")


class CostMetricsResponse(BaseModel):
    """Response model for cost metrics endpoint."""
    
    success: bool = Field(..., description="Whether request was successful")
    metrics: Optional[CostMetrics] = Field(None, description="Cost metrics")
    recent_records: List[CostRecordResponse] = Field(default_factory=list, description="Recent cost records")
    message: Optional[str] = Field(None, description="Optional message")

