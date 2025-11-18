"""Unit tests for Cost Tracker."""

import pytest
from datetime import datetime, timedelta
from app.core.cost_tracker import CostTracker, CostRecord, get_cost_tracker


@pytest.mark.unit
class TestCostTracker:
    """Test cases for CostTracker."""
    
    @pytest.fixture
    def cost_tracker(self):
        """Create a cost tracker instance."""
        tracker = CostTracker()
        tracker.clear_records()  # Start fresh
        return tracker
    
    def test_initialization(self, cost_tracker: CostTracker):
        """Test cost tracker initialization."""
        assert cost_tracker._records == []
        assert cost_tracker._alerts_enabled is True
    
    def test_calculate_cost_bedrock(self, cost_tracker: CostTracker):
        """Test calculating cost for Bedrock model."""
        cost = cost_tracker.calculate_cost(
            provider="bedrock",
            model="anthropic.claude-3-haiku-20240307-v1:0",
            input_tokens=1_000_000,
            output_tokens=1_000_000
        )
        
        # $0.25 per 1M input + $1.25 per 1M output = $1.50
        assert cost == pytest.approx(1.50, rel=0.01)
    
    def test_calculate_cost_openai(self, cost_tracker: CostTracker):
        """Test calculating cost for OpenAI model."""
        cost = cost_tracker.calculate_cost(
            provider="openai",
            model="gpt-3.5-turbo",
            input_tokens=1_000_000,
            output_tokens=1_000_000
        )
        
        # $0.50 per 1M input + $1.50 per 1M output = $2.00
        assert cost == pytest.approx(2.00, rel=0.01)
    
    def test_calculate_cost_ollama_free(self, cost_tracker: CostTracker):
        """Test that Ollama is free."""
        cost = cost_tracker.calculate_cost(
            provider="ollama",
            model="llama2",
            input_tokens=1_000_000,
            output_tokens=1_000_000
        )
        
        assert cost == 0.0
    
    def test_calculate_cost_unknown_model(self, cost_tracker: CostTracker):
        """Test calculating cost for unknown model uses defaults."""
        cost = cost_tracker.calculate_cost(
            provider="bedrock",
            model="unknown-model",
            input_tokens=1_000_000,
            output_tokens=1_000_000
        )
        
        # Default: $1.0 per 1M input + $2.0 per 1M output = $3.00
        assert cost == pytest.approx(3.00, rel=0.01)
    
    def test_record_cost(self, cost_tracker: CostTracker):
        """Test recording a cost."""
        record = cost_tracker.record_cost(
            provider="bedrock",
            model="anthropic.claude-3-haiku-20240307-v1:0",
            input_tokens=1000,
            output_tokens=500,
            agent_id="test_agent",
            endpoint="/api/v1/orchestrate"
        )
        
        assert isinstance(record, CostRecord)
        assert record.provider == "bedrock"
        assert record.input_tokens == 1000
        assert record.output_tokens == 500
        assert record.total_tokens == 1500
        assert record.agent_id == "test_agent"
        assert record.endpoint == "/api/v1/orchestrate"
        assert record.cost > 0
    
    def test_get_total_cost(self, cost_tracker: CostTracker):
        """Test getting total cost."""
        # Record multiple costs
        cost_tracker.record_cost("bedrock", "model", 1000, 500)
        cost_tracker.record_cost("bedrock", "model", 2000, 1000)
        
        total = cost_tracker.get_total_cost()
        
        assert total > 0
    
    def test_get_total_cost_with_date_range(self, cost_tracker: CostTracker):
        """Test getting total cost with date range."""
        cost_tracker.record_cost("bedrock", "model", 1000, 500)
        
        start = datetime.utcnow() - timedelta(days=1)
        end = datetime.utcnow() + timedelta(days=1)
        
        total = cost_tracker.get_total_cost(start, end)
        
        assert total > 0
    
    def test_get_daily_cost(self, cost_tracker: CostTracker):
        """Test getting daily cost."""
        cost_tracker.record_cost("bedrock", "model", 1000, 500)
        
        daily = cost_tracker.get_daily_cost()
        
        assert daily > 0
    
    def test_get_daily_cost_with_filters(self, cost_tracker: CostTracker):
        """Test getting daily cost with filters."""
        cost_tracker.record_cost(
            "bedrock", "model", 1000, 500,
            endpoint="/api/v1/orchestrate",
            agent_id="test_agent"
        )
        
        daily = cost_tracker.get_daily_cost(
            endpoint="/api/v1/orchestrate",
            agent_id="test_agent"
        )
        
        assert daily > 0
    
    def test_get_cost_by_agent(self, cost_tracker: CostTracker):
        """Test getting cost breakdown by agent."""
        cost_tracker.record_cost("bedrock", "model", 1000, 500, agent_id="agent1")
        cost_tracker.record_cost("bedrock", "model", 2000, 1000, agent_id="agent2")
        
        costs = cost_tracker.get_cost_by_agent()
        
        assert "agent1" in costs
        assert "agent2" in costs
        assert costs["agent1"] > 0
        assert costs["agent2"] > 0
    
    def test_get_cost_by_endpoint(self, cost_tracker: CostTracker):
        """Test getting cost breakdown by endpoint."""
        cost_tracker.record_cost("bedrock", "model", 1000, 500, endpoint="/api/v1/orchestrate")
        cost_tracker.record_cost("bedrock", "model", 2000, 1000, endpoint="/api/v1/agents")
        
        costs = cost_tracker.get_cost_by_endpoint()
        
        assert "/api/v1/orchestrate" in costs
        assert "/api/v1/agents" in costs
    
    def test_get_token_usage(self, cost_tracker: CostTracker):
        """Test getting token usage statistics."""
        cost_tracker.record_cost("bedrock", "model", 1000, 500)
        cost_tracker.record_cost("bedrock", "model", 2000, 1000)
        
        usage = cost_tracker.get_token_usage()
        
        assert usage["input_tokens"] == 3000
        assert usage["output_tokens"] == 1500
        assert usage["total_tokens"] == 4500
        assert usage["request_count"] == 2
    
    def test_set_daily_limit(self, cost_tracker: CostTracker):
        """Test setting daily cost limit."""
        cost_tracker.set_daily_limit("/api/v1/orchestrate", 10.0)
        
        # Should not raise exception
        assert True
    
    def test_get_recent_records(self, cost_tracker: CostTracker):
        """Test getting recent cost records."""
        for i in range(5):
            cost_tracker.record_cost("bedrock", "model", 100, 50)
        
        recent = cost_tracker.get_recent_records(limit=3)
        
        assert len(recent) == 3
    
    def test_get_recent_records_limit_exceeds_total(self, cost_tracker: CostTracker):
        """Test getting recent records when limit exceeds total."""
        cost_tracker.record_cost("bedrock", "model", 100, 50)
        
        recent = cost_tracker.get_recent_records(limit=100)
        
        assert len(recent) == 1
    
    def test_clear_records(self, cost_tracker: CostTracker):
        """Test clearing all records."""
        cost_tracker.record_cost("bedrock", "model", 100, 50)
        assert len(cost_tracker._records) == 1
        
        cost_tracker.clear_records()
        assert len(cost_tracker._records) == 0
    
    def test_get_cost_tracker_singleton(self):
        """Test that get_cost_tracker returns singleton."""
        tracker1 = get_cost_tracker()
        tracker2 = get_cost_tracker()
        
        assert tracker1 is tracker2

