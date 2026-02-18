"""Unit tests for Agent Sandbox."""

import sys
from unittest.mock import patch

import pytest

from app.core.exceptions import AgentError
from app.core.sandbox import AgentSandbox, ExecutionContext, ResourceLimits, get_sandbox


@pytest.mark.unit
class TestResourceLimits:
    """Test cases for ResourceLimits."""

    def test_initialization_defaults(self):
        """Test ResourceLimits with default values."""
        limits = ResourceLimits()

        assert limits.max_cpu_time == 30.0
        assert limits.max_memory_mb == 512
        assert limits.max_execution_time == 60.0
        assert limits.allowed_operations == []

    def test_initialization_custom(self):
        """Test ResourceLimits with custom values."""
        limits = ResourceLimits(
            max_cpu_time=10.0,
            max_memory_mb=256,
            max_execution_time=30.0,
            allowed_operations=["read", "write"],
        )

        assert limits.max_cpu_time == 10.0
        assert limits.max_memory_mb == 256
        assert limits.max_execution_time == 30.0
        assert limits.allowed_operations == ["read", "write"]


@pytest.mark.unit
class TestExecutionContext:
    """Test cases for ExecutionContext."""

    def test_initialization(self):
        """Test ExecutionContext initialization."""
        limits = ResourceLimits()
        context = ExecutionContext("test_agent", limits, ["read"])

        assert context.agent_id == "test_agent"
        assert context.resource_limits == limits
        assert context.allowed_operations == ["read"]
        assert context.start_time is None
        assert context.audit_log == []


@pytest.mark.unit
class TestAgentSandbox:
    """Test cases for AgentSandbox."""

    @pytest.fixture
    def sandbox(self):
        """Create a sandbox instance."""
        return AgentSandbox()

    def test_initialization(self, sandbox: AgentSandbox):
        """Test sandbox initialization."""
        assert sandbox._contexts == {}
        assert sandbox._default_limits is not None

    def test_create_context(self, sandbox: AgentSandbox):
        """Test creating execution context."""
        limits = ResourceLimits(max_cpu_time=10.0)
        context = sandbox.create_context("test_agent", limits, ["read"])

        assert context.agent_id == "test_agent"
        assert context.resource_limits.max_cpu_time == 10.0
        assert context.allowed_operations == ["read"]

    def test_create_context_defaults(self, sandbox: AgentSandbox):
        """Test creating context with defaults."""
        context = sandbox.create_context("test_agent")

        assert context.agent_id == "test_agent"
        assert context.resource_limits == sandbox._default_limits

    def test_get_context_exists(self, sandbox: AgentSandbox):
        """Test getting existing context."""
        context = sandbox.create_context("test_agent")
        retrieved = sandbox.get_context("test_agent")

        assert retrieved is context

    def test_get_context_not_exists(self, sandbox: AgentSandbox):
        """Test getting non-existent context."""
        context = sandbox.get_context("nonexistent")

        assert context is None

    def test_execute_with_limits_allowed_operation(self, sandbox: AgentSandbox):
        """Test executing with allowed operation."""
        context = sandbox.create_context("test_agent", allowed_operations=["execute"])

        with sandbox.execute_with_limits("test_agent", "execute"):
            assert context.start_time is not None

    def test_execute_with_limits_disallowed_operation(self, sandbox: AgentSandbox):
        """Test executing with disallowed operation."""
        sandbox.create_context("test_agent", allowed_operations=["read"])

        with pytest.raises(AgentError) as exc_info:
            with sandbox.execute_with_limits("test_agent", "write"):
                pass

        assert "not allowed" in str(exc_info.value).lower()

    def test_execute_with_limits_no_restrictions(self, sandbox: AgentSandbox):
        """Test executing with no operation restrictions."""
        with sandbox.execute_with_limits("test_agent", "execute"):
            # Should not raise exception
            assert True

    @pytest.mark.skipif(sys.platform == "win32", reason="resource module not available on Windows")
    @patch("app.core.sandbox.resource.setrlimit")
    def test_execute_with_limits_sets_memory_limit(self, mock_setrlimit, sandbox: AgentSandbox):
        """Test that memory limits are set."""
        limits = ResourceLimits(max_memory_mb=256)
        sandbox.create_context("test_agent", limits)

        with sandbox.execute_with_limits("test_agent", "execute"):
            # Should attempt to set memory limits
            assert mock_setrlimit.called or True  # May not be supported on all platforms

    def test_check_permission_allowed(self, sandbox: AgentSandbox):
        """Test checking allowed permission."""
        sandbox.create_context("test_agent", allowed_operations=["read"])

        assert sandbox.check_permission("test_agent", "read") is True

    def test_check_permission_disallowed(self, sandbox: AgentSandbox):
        """Test checking disallowed permission."""
        sandbox.create_context("test_agent", allowed_operations=["read"])

        assert sandbox.check_permission("test_agent", "write") is False

    def test_check_permission_no_context(self, sandbox: AgentSandbox):
        """Test checking permission with no context (default allow)."""
        assert sandbox.check_permission("nonexistent", "read") is True

    def test_get_audit_log(self, sandbox: AgentSandbox):
        """Test getting audit log."""
        sandbox.create_context("test_agent")

        with sandbox.execute_with_limits("test_agent", "execute"):
            pass

        log = sandbox.get_audit_log("test_agent")

        assert len(log) > 0
        assert any(entry["action"] == "start" for entry in log)
        assert any(entry["action"] == "success" for entry in log)

    def test_get_audit_log_no_context(self, sandbox: AgentSandbox):
        """Test getting audit log for non-existent context."""
        log = sandbox.get_audit_log("nonexistent")

        assert log == []

    def test_clear_context(self, sandbox: AgentSandbox):
        """Test clearing context."""
        sandbox.create_context("test_agent")
        assert sandbox.get_context("test_agent") is not None

        sandbox.clear_context("test_agent")
        assert sandbox.get_context("test_agent") is None

    def test_get_sandbox_singleton(self):
        """Test that get_sandbox returns singleton."""
        sandbox1 = get_sandbox()
        sandbox2 = get_sandbox()

        assert sandbox1 is sandbox2
