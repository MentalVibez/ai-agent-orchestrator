"""LLM cost tracking and analytics."""

from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class CostRecord:
    """Record of a single LLM call cost."""
    timestamp: datetime
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost: float
    agent_id: Optional[str] = None
    endpoint: Optional[str] = None
    request_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class CostTracker:
    """Track and analyze LLM costs."""
    
    # Model pricing per 1M tokens (input/output)
    # Prices in USD as of 2024
    MODEL_PRICING = {
        "anthropic.claude-3-haiku-20240307-v1:0": {
            "input": 0.25,  # $0.25 per 1M input tokens
            "output": 1.25  # $1.25 per 1M output tokens
        },
        "anthropic.claude-3-sonnet-20240229-v1:0": {
            "input": 3.00,
            "output": 15.00
        },
        "anthropic.claude-3-opus-20240229-v1:0": {
            "input": 15.00,
            "output": 75.00
        },
        "gpt-3.5-turbo": {
            "input": 0.50,
            "output": 1.50
        },
        "gpt-4": {
            "input": 30.00,
            "output": 60.00
        },
        "gpt-4-turbo": {
            "input": 10.00,
            "output": 30.00
        }
    }
    
    def __init__(self):
        """Initialize cost tracker."""
        self._records: List[CostRecord] = []
        self._lock = Lock()
        self._daily_limits: Dict[str, float] = {}  # Daily cost limits per endpoint/agent
        self._alerts_enabled = True
    
    def calculate_cost(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int
    ) -> float:
        """
        Calculate cost for LLM usage.
        
        Args:
            provider: LLM provider name (bedrock, openai, ollama)
            model: Model identifier
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            
        Returns:
            Cost in USD
        """
        # Ollama is free (local)
        if provider == "ollama":
            return 0.0
        
        # Get pricing for model
        pricing = self.MODEL_PRICING.get(model)
        if not pricing:
            # Default pricing if model not found
            pricing = {"input": 1.0, "output": 2.0}
        
        # Calculate cost
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        
        return input_cost + output_cost
    
    def record_cost(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        agent_id: Optional[str] = None,
        endpoint: Optional[str] = None,
        request_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> CostRecord:
        """
        Record a cost entry.
        
        Args:
            provider: LLM provider name
            model: Model identifier
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            agent_id: Optional agent ID
            endpoint: Optional endpoint name
            request_id: Optional request ID
            metadata: Optional metadata
            
        Returns:
            CostRecord instance
        """
        total_tokens = input_tokens + output_tokens
        cost = self.calculate_cost(provider, model, input_tokens, output_tokens)
        
        record = CostRecord(
            timestamp=datetime.utcnow(),
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost=cost,
            agent_id=agent_id,
            endpoint=endpoint,
            request_id=request_id,
            metadata=metadata or {}
        )
        
        with self._lock:
            self._records.append(record)
            
            # Check daily limits
            if self._alerts_enabled:
                self._check_daily_limits(record)
        
        return record
    
    def _check_daily_limits(self, record: CostRecord):
        """Check if daily cost limits are exceeded."""
        today = datetime.utcnow().date()
        key = f"{record.endpoint or 'default'}_{today}"
        
        daily_cost = self.get_daily_cost(date=today, endpoint=record.endpoint)
        
        if key in self._daily_limits and daily_cost > self._daily_limits[key]:
            # Log alert (in production, send notification)
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Daily cost limit exceeded for {record.endpoint}: "
                f"${daily_cost:.2f} > ${self._daily_limits[key]:.2f}"
            )
    
    def get_total_cost(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> float:
        """
        Get total cost for a time period.
        
        Args:
            start_date: Start date (default: all time)
            end_date: End date (default: now)
            
        Returns:
            Total cost in USD
        """
        with self._lock:
            records = self._filter_records(start_date, end_date)
            return sum(record.cost for record in records)
    
    def get_daily_cost(
        self,
        date: Optional[datetime.date] = None,
        endpoint: Optional[str] = None,
        agent_id: Optional[str] = None
    ) -> float:
        """
        Get cost for a specific day.
        
        Args:
            date: Date to check (default: today)
            endpoint: Optional endpoint filter
            agent_id: Optional agent filter
            
        Returns:
            Daily cost in USD
        """
        if date is None:
            date = datetime.utcnow().date()
        
        start = datetime.combine(date, datetime.min.time())
        end = datetime.combine(date, datetime.max.time())
        
        with self._lock:
            records = self._filter_records(start, end, endpoint, agent_id)
            return sum(record.cost for record in records)
    
    def get_cost_by_agent(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, float]:
        """
        Get cost breakdown by agent.
        
        Args:
            start_date: Start date
            end_date: End date
            
        Returns:
            Dictionary mapping agent_id to cost
        """
        with self._lock:
            records = self._filter_records(start_date, end_date)
            costs = defaultdict(float)
            
            for record in records:
                agent = record.agent_id or "unknown"
                costs[agent] += record.cost
            
            return dict(costs)
    
    def get_cost_by_endpoint(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, float]:
        """
        Get cost breakdown by endpoint.
        
        Args:
            start_date: Start date
            end_date: End date
            
        Returns:
            Dictionary mapping endpoint to cost
        """
        with self._lock:
            records = self._filter_records(start_date, end_date)
            costs = defaultdict(float)
            
            for record in records:
                endpoint = record.endpoint or "unknown"
                costs[endpoint] += record.cost
            
            return dict(costs)
    
    def get_token_usage(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, int]:
        """
        Get token usage statistics.
        
        Args:
            start_date: Start date
            end_date: End date
            
        Returns:
            Dictionary with token statistics
        """
        with self._lock:
            records = self._filter_records(start_date, end_date)
            
            total_input = sum(r.input_tokens for r in records)
            total_output = sum(r.output_tokens for r in records)
            total_tokens = sum(r.total_tokens for r in records)
            
            return {
                "input_tokens": total_input,
                "output_tokens": total_output,
                "total_tokens": total_tokens,
                "request_count": len(records)
            }
    
    def set_daily_limit(self, endpoint: str, limit: float):
        """
        Set daily cost limit for an endpoint.
        
        Args:
            endpoint: Endpoint name
            limit: Daily cost limit in USD
        """
        today = datetime.utcnow().date()
        key = f"{endpoint}_{today}"
        self._daily_limits[key] = limit
    
    def get_recent_records(self, limit: int = 100) -> List[CostRecord]:
        """
        Get recent cost records.
        
        Args:
            limit: Maximum number of records to return
            
        Returns:
            List of recent CostRecord instances
        """
        with self._lock:
            return self._records[-limit:]
    
    def _filter_records(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        endpoint: Optional[str] = None,
        agent_id: Optional[str] = None
    ) -> List[CostRecord]:
        """Filter records by criteria."""
        records = self._records
        
        if start_date:
            records = [r for r in records if r.timestamp >= start_date]
        
        if end_date:
            records = [r for r in records if r.timestamp <= end_date]
        
        if endpoint:
            records = [r for r in records if r.endpoint == endpoint]
        
        if agent_id:
            records = [r for r in records if r.agent_id == agent_id]
        
        return records
    
    def clear_records(self):
        """Clear all cost records (for testing)."""
        with self._lock:
            self._records.clear()


# Global cost tracker instance
_cost_tracker: Optional[CostTracker] = None


def get_cost_tracker() -> CostTracker:
    """Get the global cost tracker instance."""
    global _cost_tracker
    if _cost_tracker is None:
        _cost_tracker = CostTracker()
    return _cost_tracker

