"""Unit tests for Resource Limits."""

import pytest

from app.core.resource_limits import (
    CODE_REVIEW_LIMITS,
    DEFAULT_LIMITS,
    INFRASTRUCTURE_LIMITS,
    LOG_ANALYSIS_LIMITS,
    NETWORK_DIAGNOSTICS_LIMITS,
    SYSTEM_MONITORING_LIMITS,
    get_limits_for_agent,
)


@pytest.mark.unit
class TestResourceLimits:
    """Test cases for resource limits."""

    def test_default_limits(self):
        """Test default limits configuration."""
        assert DEFAULT_LIMITS.max_cpu_time == 30.0
        assert DEFAULT_LIMITS.max_memory_mb == 512
        assert DEFAULT_LIMITS.max_execution_time == 60.0
        assert DEFAULT_LIMITS.allowed_operations == []

    def test_network_diagnostics_limits(self):
        """Test network diagnostics agent limits."""
        assert NETWORK_DIAGNOSTICS_LIMITS.max_cpu_time == 20.0
        assert NETWORK_DIAGNOSTICS_LIMITS.max_memory_mb == 256
        assert NETWORK_DIAGNOSTICS_LIMITS.max_execution_time == 45.0
        assert "network_check" in NETWORK_DIAGNOSTICS_LIMITS.allowed_operations
        assert "dns_lookup" in NETWORK_DIAGNOSTICS_LIMITS.allowed_operations

    def test_log_analysis_limits(self):
        """Test log analysis agent limits."""
        assert LOG_ANALYSIS_LIMITS.max_cpu_time == 15.0
        assert LOG_ANALYSIS_LIMITS.max_memory_mb == 128
        assert LOG_ANALYSIS_LIMITS.max_execution_time == 30.0
        assert "log_parse" in LOG_ANALYSIS_LIMITS.allowed_operations

    def test_system_monitoring_limits(self):
        """Test system monitoring agent limits."""
        assert SYSTEM_MONITORING_LIMITS.max_cpu_time == 10.0
        assert SYSTEM_MONITORING_LIMITS.max_memory_mb == 128
        assert SYSTEM_MONITORING_LIMITS.max_execution_time == 20.0
        assert "cpu_check" in SYSTEM_MONITORING_LIMITS.allowed_operations

    def test_infrastructure_limits(self):
        """Test infrastructure agent limits."""
        assert INFRASTRUCTURE_LIMITS.max_cpu_time == 5.0
        assert INFRASTRUCTURE_LIMITS.max_memory_mb == 64
        assert INFRASTRUCTURE_LIMITS.max_execution_time == 15.0
        assert "config_read" in INFRASTRUCTURE_LIMITS.allowed_operations

    def test_code_review_limits(self):
        """Test code review agent limits."""
        assert CODE_REVIEW_LIMITS.max_cpu_time == 30.0
        assert CODE_REVIEW_LIMITS.max_memory_mb == 512
        assert CODE_REVIEW_LIMITS.max_execution_time == 120.0
        assert "file_read" in CODE_REVIEW_LIMITS.allowed_operations
        assert "code_search" in CODE_REVIEW_LIMITS.allowed_operations

    def test_get_limits_for_network_diagnostics(self):
        """Test getting limits for network diagnostics agent."""
        limits = get_limits_for_agent("network_diagnostics")
        assert limits == NETWORK_DIAGNOSTICS_LIMITS

    def test_get_limits_for_log_analysis(self):
        """Test getting limits for log analysis agent."""
        limits = get_limits_for_agent("log_analysis")
        assert limits == LOG_ANALYSIS_LIMITS

    def test_get_limits_for_system_monitoring(self):
        """Test getting limits for system monitoring agent."""
        limits = get_limits_for_agent("system_monitoring")
        assert limits == SYSTEM_MONITORING_LIMITS

    def test_get_limits_for_infrastructure(self):
        """Test getting limits for infrastructure agent."""
        limits = get_limits_for_agent("infrastructure")
        assert limits == INFRASTRUCTURE_LIMITS

    def test_get_limits_for_code_review(self):
        """Test getting limits for code review agent."""
        limits = get_limits_for_agent("code_review")
        assert limits == CODE_REVIEW_LIMITS

    def test_get_limits_for_unknown_agent(self):
        """Test getting limits for unknown agent returns default."""
        limits = get_limits_for_agent("unknown_agent")
        assert limits == DEFAULT_LIMITS

    def test_get_limits_for_empty_string(self):
        """Test getting limits for empty string returns default."""
        limits = get_limits_for_agent("")
        assert limits == DEFAULT_LIMITS
