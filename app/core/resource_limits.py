"""Resource limit configurations for different agent types."""

from app.core.sandbox import ResourceLimits

# Default resource limits
DEFAULT_LIMITS = ResourceLimits(max_cpu_time=30.0, max_memory_mb=512, max_execution_time=60.0)

# Network diagnostics agent limits
NETWORK_DIAGNOSTICS_LIMITS = ResourceLimits(
    max_cpu_time=20.0,
    max_memory_mb=256,
    max_execution_time=45.0,
    allowed_operations=["network_check", "dns_lookup", "connectivity_test"],
)

# Log analysis agent limits (more restrictive for security)
LOG_ANALYSIS_LIMITS = ResourceLimits(
    max_cpu_time=15.0,
    max_memory_mb=128,
    max_execution_time=30.0,
    allowed_operations=["log_parse", "error_detect", "pattern_match"],
)

# System monitoring agent limits
SYSTEM_MONITORING_LIMITS = ResourceLimits(
    max_cpu_time=10.0,
    max_memory_mb=128,
    max_execution_time=20.0,
    allowed_operations=["cpu_check", "memory_check", "disk_check"],
)

# Infrastructure agent limits (most restrictive)
INFRASTRUCTURE_LIMITS = ResourceLimits(
    max_cpu_time=5.0,
    max_memory_mb=64,
    max_execution_time=15.0,
    allowed_operations=["config_read", "config_validate"],  # No write operations by default
)

# Code review agent limits (needs more resources for file operations)
CODE_REVIEW_LIMITS = ResourceLimits(
    max_cpu_time=30.0,
    max_memory_mb=512,
    max_execution_time=120.0,  # Longer timeout for code analysis
    allowed_operations=["file_read", "code_search", "directory_list", "file_metadata"],
)


def get_limits_for_agent(agent_id: str) -> ResourceLimits:
    """
    Get resource limits for a specific agent.

    Args:
        agent_id: Agent identifier

    Returns:
        ResourceLimits instance
    """
    limits_map = {
        "network_diagnostics": NETWORK_DIAGNOSTICS_LIMITS,
        "log_analysis": LOG_ANALYSIS_LIMITS,
        "system_monitoring": SYSTEM_MONITORING_LIMITS,
        "infrastructure": INFRASTRUCTURE_LIMITS,
        "code_review": CODE_REVIEW_LIMITS,
    }

    return limits_map.get(agent_id, DEFAULT_LIMITS)
