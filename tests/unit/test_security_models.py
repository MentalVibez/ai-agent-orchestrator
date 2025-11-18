"""Unit tests for Security Models."""

import pytest
from app.models.security import (
    ResourceLimitsConfig,
    AuditLogEntry,
    SecurityConfig
)


@pytest.mark.unit
class TestResourceLimitsConfig:
    """Test cases for ResourceLimitsConfig."""
    
    def test_initialization_defaults(self):
        """Test ResourceLimitsConfig with default values."""
        config = ResourceLimitsConfig()
        
        assert config.max_cpu_time == 30.0
        assert config.max_memory_mb == 512
        assert config.max_execution_time == 60.0
        assert config.allowed_operations == []
    
    def test_initialization_custom(self):
        """Test ResourceLimitsConfig with custom values."""
        config = ResourceLimitsConfig(
            max_cpu_time=10.0,
            max_memory_mb=256,
            max_execution_time=30.0,
            allowed_operations=["read", "write"]
        )
        
        assert config.max_cpu_time == 10.0
        assert config.max_memory_mb == 256
        assert config.max_execution_time == 30.0
        assert config.allowed_operations == ["read", "write"]


@pytest.mark.unit
class TestAuditLogEntry:
    """Test cases for AuditLogEntry."""
    
    def test_initialization_required_fields(self):
        """Test AuditLogEntry with required fields."""
        entry = AuditLogEntry(
            timestamp="2024-01-01T00:00:00",
            operation="execute",
            action="start"
        )
        
        assert entry.timestamp == "2024-01-01T00:00:00"
        assert entry.operation == "execute"
        assert entry.action == "start"
        assert entry.duration is None
        assert entry.error is None
        assert entry.metadata == {}
    
    def test_initialization_all_fields(self):
        """Test AuditLogEntry with all fields."""
        entry = AuditLogEntry(
            timestamp="2024-01-01T00:00:00",
            operation="execute",
            action="success",
            duration=1.5,
            error=None,
            metadata={"key": "value"}
        )
        
        assert entry.duration == 1.5
        assert entry.metadata == {"key": "value"}


@pytest.mark.unit
class TestSecurityConfig:
    """Test cases for SecurityConfig."""
    
    def test_initialization(self):
        """Test SecurityConfig initialization."""
        limits = ResourceLimitsConfig()
        config = SecurityConfig(
            agent_id="test_agent",
            resource_limits=limits,
            allowed_operations=["read"],
            audit_log=[]
        )
        
        assert config.agent_id == "test_agent"
        assert config.resource_limits == limits
        assert config.allowed_operations == ["read"]
        assert config.audit_log == []
    
    def test_initialization_with_audit_log(self):
        """Test SecurityConfig with audit log entries."""
        limits = ResourceLimitsConfig()
        audit_entry = AuditLogEntry(
            timestamp="2024-01-01T00:00:00",
            operation="execute",
            action="start"
        )
        
        config = SecurityConfig(
            agent_id="test_agent",
            resource_limits=limits,
            audit_log=[audit_entry]
        )
        
        assert len(config.audit_log) == 1
        assert config.audit_log[0] == audit_entry

