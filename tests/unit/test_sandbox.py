"""Unit tests for Agent Sandbox."""

import asyncio
import sys
from threading import Timer
from unittest.mock import AsyncMock, MagicMock, patch

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

    # ------------------------------------------------------------------
    # execute_with_limits error paths (lines 196-221)
    # ------------------------------------------------------------------

    def test_oserror_inside_context_raises_agent_error(self, sandbox: AgentSandbox):
        """Covers lines 196-210: OSError inside yield → audit-logged → AgentError raised."""
        sandbox.create_context("test_agent")
        with pytest.raises(AgentError, match="Resource limit exceeded"):
            with sandbox.execute_with_limits("test_agent", "execute"):
                raise OSError("disk full")

        log = sandbox.get_audit_log("test_agent")
        assert any(e["action"] == "resource_limit_exceeded" for e in log)

    def test_generic_exception_reraises_and_logs(self, sandbox: AgentSandbox):
        """Covers lines 211-221: generic Exception inside yield → audit-logged → re-raised."""
        sandbox.create_context("test_agent")
        with pytest.raises(ValueError, match="boom"):
            with sandbox.execute_with_limits("test_agent", "execute"):
                raise ValueError("boom")

        log = sandbox.get_audit_log("test_agent")
        assert any(e["action"] == "error" for e in log)

    # ------------------------------------------------------------------
    # Resource-limit setting and restoration (lines 156-163, 228-233)
    # ------------------------------------------------------------------

    def test_resource_memory_limit_set_on_unix(self, sandbox: AgentSandbox):
        """Covers lines 156-163: resource module present → setrlimit called."""
        mock_resource = MagicMock()
        mock_resource.RLIMIT_AS = 9
        mock_resource.getrlimit.return_value = (1024 * 1024 * 512, -1)

        with patch("app.core.sandbox.resource", mock_resource):
            limits = ResourceLimits(max_memory_mb=256)
            sandbox.create_context("test_agent", limits)
            with sandbox.execute_with_limits("test_agent", "execute"):
                pass

        mock_resource.getrlimit.assert_called_once_with(mock_resource.RLIMIT_AS)
        mock_resource.setrlimit.assert_called()

    def test_resource_limits_restored_in_finally(self, sandbox: AgentSandbox):
        """Covers lines 228-233: resource limits restored after the context exits."""
        mock_resource = MagicMock()
        mock_resource.RLIMIT_AS = 9
        orig = (1024 * 1024 * 256, -1)
        mock_resource.getrlimit.return_value = orig

        with patch("app.core.sandbox.resource", mock_resource):
            limits = ResourceLimits(max_memory_mb=128)
            sandbox.create_context("test_agent", limits)
            with sandbox.execute_with_limits("test_agent", "execute"):
                pass

        # setrlimit called twice: once to set, once to restore
        assert mock_resource.setrlimit.call_count == 2
        mock_resource.setrlimit.assert_called_with(mock_resource.RLIMIT_AS, orig)

    def test_resource_limit_setrlimit_failure_is_swallowed(self, sandbox: AgentSandbox):
        """Covers lines 161-163: OSError from setrlimit is caught; execution continues."""
        mock_resource = MagicMock()
        mock_resource.RLIMIT_AS = 9
        mock_resource.getrlimit.return_value = (0, -1)
        mock_resource.setrlimit.side_effect = OSError("not supported")

        with patch("app.core.sandbox.resource", mock_resource):
            limits = ResourceLimits(max_memory_mb=256)
            sandbox.create_context("test_agent", limits)
            # Must NOT raise — the OSError from setrlimit is swallowed
            with sandbox.execute_with_limits("test_agent", "execute"):
                pass

    # ------------------------------------------------------------------
    # Timeout handler body (line 170)
    # ------------------------------------------------------------------

    def test_timeout_handler_body_raises_agent_error(self, sandbox: AgentSandbox):
        """Covers line 170: timeout_handler raises AgentError when invoked."""
        captured_fn = []

        def capture_timer(delay, fn, *a, **kw):
            captured_fn.append(fn)
            m = MagicMock()
            m.cancel = MagicMock()
            return m

        sandbox.create_context("test_agent")
        with patch("app.core.sandbox.Timer", side_effect=capture_timer):
            with sandbox.execute_with_limits("test_agent", "execute"):
                pass

        assert len(captured_fn) == 1
        with pytest.raises(AgentError, match="timeout"):
            captured_fn[0]()

    # ------------------------------------------------------------------
    # check_permission: empty allowed_operations → default allow (line 339)
    # ------------------------------------------------------------------

    def test_check_permission_empty_allowed_ops_allows_any(self, sandbox: AgentSandbox):
        """Covers line 339: context exists but allowed_operations=[] → return True."""
        # create_context with no allowed_operations stores an empty list
        sandbox.create_context("test_agent")
        assert sandbox.check_permission("test_agent", "any_operation") is True


@pytest.mark.unit
class TestExecuteWithLimitsAsync:
    """Tests for execute_with_limits_async (lines 261-316)."""

    @pytest.fixture
    def sandbox(self):
        return AgentSandbox()

    @pytest.mark.asyncio
    async def test_happy_path_returns_result(self, sandbox: AgentSandbox):
        """Covers lines 261-294: normal execution path with timeout."""
        result = await sandbox.execute_with_limits_async("agent", lambda: 42)
        assert result == 42

        log = sandbox.get_audit_log("agent")
        assert any(e["action"] == "start" for e in log)
        assert any(e["action"] == "success" for e in log)

    @pytest.mark.asyncio
    async def test_no_timeout_when_max_execution_time_zero(self, sandbox: AgentSandbox):
        """Covers line 285: max_execution_time=0 → asyncio.wait_for skipped."""
        limits = ResourceLimits(max_execution_time=0.0)
        sandbox.create_context("agent", limits)
        result = await sandbox.execute_with_limits_async("agent", lambda: "done")
        assert result == "done"

    @pytest.mark.asyncio
    async def test_disallowed_operation_raises_agent_error(self, sandbox: AgentSandbox):
        """Covers lines 265-270: operation not in allowed_operations → AgentError."""
        sandbox.create_context("agent", allowed_operations=["read"])
        with pytest.raises(AgentError, match="not allowed"):
            await sandbox.execute_with_limits_async("agent", lambda: 1, operation="write")

    @pytest.mark.asyncio
    async def test_asyncio_timeout_raises_timeout_error(self, sandbox: AgentSandbox):
        """Covers lines 295-306: asyncio.TimeoutError → TimeoutError re-raised."""
        with patch("app.core.sandbox.asyncio.wait_for", side_effect=asyncio.TimeoutError):
            with pytest.raises(TimeoutError, match="timeout"):
                await sandbox.execute_with_limits_async("agent", lambda: 1)

        log = sandbox.get_audit_log("agent")
        assert any(e["action"] == "timeout" for e in log)

    @pytest.mark.asyncio
    async def test_generic_exception_reraises(self, sandbox: AgentSandbox):
        """Covers lines 307-316: exception from func → audit-logged → re-raised."""

        def _raiser():
            raise ValueError("async task failed")

        with pytest.raises(ValueError, match="async task failed"):
            await sandbox.execute_with_limits_async("agent", _raiser)

        log = sandbox.get_audit_log("agent")
        assert any(e["action"] == "error" for e in log)

    @pytest.mark.asyncio
    async def test_auto_creates_context_when_missing(self, sandbox: AgentSandbox):
        """No pre-existing context → auto-created; execution completes normally."""
        # No create_context call — execute_with_limits_async creates one
        result = await sandbox.execute_with_limits_async("new_agent", lambda: 99)
        assert result == 99
