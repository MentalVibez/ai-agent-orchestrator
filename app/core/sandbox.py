"""Agent sandboxing for secure execution isolation."""

import asyncio
import logging
import time
from contextlib import contextmanager
from threading import Timer
from typing import Any, Callable, Dict, List, Optional

from app.core.exceptions import AgentError

# resource is Unix-only; on Windows we skip actual limits
try:
    import resource
except ImportError:
    resource = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class ResourceLimits:
    """Resource limits for agent execution."""

    def __init__(
        self,
        max_cpu_time: float = 30.0,  # seconds
        max_memory_mb: int = 512,  # megabytes
        max_execution_time: float = 60.0,  # seconds
        allowed_operations: Optional[list] = None,
    ):
        """
        Initialize resource limits.

        Args:
            max_cpu_time: Maximum CPU time in seconds
            max_memory_mb: Maximum memory in megabytes
            max_execution_time: Maximum execution time in seconds
            allowed_operations: List of allowed operations (None = all allowed)
        """
        self.max_cpu_time = max_cpu_time
        self.max_memory_mb = max_memory_mb
        self.max_execution_time = max_execution_time
        self.allowed_operations = allowed_operations or []


class ExecutionContext:
    """Execution context for agent operations."""

    def __init__(
        self,
        agent_id: str,
        resource_limits: Optional[ResourceLimits] = None,
        allowed_operations: Optional[list] = None,
    ):
        """
        Initialize execution context.

        Args:
            agent_id: Agent identifier
            resource_limits: Resource limits for execution
            allowed_operations: Allowed operations for this agent
        """
        self.agent_id = agent_id
        self.resource_limits = resource_limits or ResourceLimits()
        self.allowed_operations = allowed_operations or []
        self.start_time = None
        self.audit_log: list = []


class AgentSandbox:
    """Sandbox for secure agent execution."""

    def __init__(self):
        """Initialize agent sandbox."""
        self._contexts: Dict[str, ExecutionContext] = {}
        self._default_limits = ResourceLimits()

    def create_context(
        self,
        agent_id: str,
        resource_limits: Optional[ResourceLimits] = None,
        allowed_operations: Optional[list] = None,
    ) -> ExecutionContext:
        """
        Create an execution context for an agent.

        Args:
            agent_id: Agent identifier
            resource_limits: Resource limits
            allowed_operations: Allowed operations

        Returns:
            ExecutionContext instance
        """
        context = ExecutionContext(
            agent_id=agent_id,
            resource_limits=resource_limits or self._default_limits,
            allowed_operations=allowed_operations,
        )
        self._contexts[agent_id] = context
        return context

    def get_context(self, agent_id: str) -> Optional[ExecutionContext]:
        """
        Get execution context for an agent.

        Args:
            agent_id: Agent identifier

        Returns:
            ExecutionContext if found, None otherwise
        """
        return self._contexts.get(agent_id)

    @contextmanager
    def execute_with_limits(self, agent_id: str, operation: str = "execute"):
        """
        Execute agent operation with resource limits.

        Args:
            agent_id: Agent identifier
            operation: Operation name

        Yields:
            Execution context

        Raises:
            AgentError: If limits are exceeded
        """
        context = self.get_context(agent_id)
        if not context:
            context = self.create_context(agent_id)

        # Check if operation is allowed
        if context.allowed_operations and operation not in context.allowed_operations:
            raise AgentError(
                f"Operation '{operation}' not allowed for agent '{agent_id}'",
                agent_id=agent_id,
                details={"operation": operation, "allowed": context.allowed_operations},
            )

        # Set resource limits
        limits = context.resource_limits
        context.start_time = time.time()

        # Snapshot originals so the finally block can restore them exactly.
        # Only the soft limit is changed; the hard limit is left alone so that
        # a non-root process can always restore the previous soft limit.
        _orig_as: Optional[tuple] = None
        _orig_cpu: Optional[tuple] = None
        if resource is not None:
            try:
                if limits.max_memory_mb > 0:
                    _orig_as = resource.getrlimit(resource.RLIMIT_AS)
                    max_memory_bytes = limits.max_memory_mb * 1024 * 1024
                    resource.setrlimit(resource.RLIMIT_AS, (max_memory_bytes, _orig_as[1]))
            except (ValueError, OSError) as e:
                logger.warning("Could not set memory limit: %s", e)
                _orig_as = None
            try:
                if limits.max_cpu_time > 0:
                    _orig_cpu = resource.getrlimit(resource.RLIMIT_CPU)
                    resource.setrlimit(
                        resource.RLIMIT_CPU, (int(limits.max_cpu_time), _orig_cpu[1])
                    )
            except (ValueError, OSError) as e:
                logger.warning("Could not set CPU limit: %s", e)
                _orig_cpu = None

        # Set execution timeout
        timeout_timer = None
        if limits.max_execution_time > 0:

            def timeout_handler():
                raise AgentError(
                    f"Execution timeout exceeded ({limits.max_execution_time}s) for agent '{agent_id}'",
                    agent_id=agent_id,
                )

            timeout_timer = Timer(limits.max_execution_time, timeout_handler)
            timeout_timer.start()

        try:
            # Log operation start
            context.audit_log.append(
                {"timestamp": time.time(), "operation": operation, "action": "start"}
            )

            yield context

            # Log operation success
            context.audit_log.append(
                {
                    "timestamp": time.time(),
                    "operation": operation,
                    "action": "success",
                    "duration": time.time() - context.start_time,
                }
            )

        except OSError as e:
            # Resource limit exceeded
            context.audit_log.append(
                {
                    "timestamp": time.time(),
                    "operation": operation,
                    "action": "resource_limit_exceeded",
                    "error": str(e),
                }
            )
            raise AgentError(
                f"Resource limit exceeded for agent '{agent_id}': {str(e)}",
                agent_id=agent_id,
                details={"operation": operation, "error": str(e)},
            )
        except Exception as e:
            # Log operation failure
            context.audit_log.append(
                {
                    "timestamp": time.time(),
                    "operation": operation,
                    "action": "error",
                    "error": str(e),
                }
            )
            raise
        finally:
            # Cancel timeout timer
            if timeout_timer:
                timeout_timer.cancel()

            # Restore resource limits (Unix only)
            if resource is not None:
                if _orig_as is not None:
                    try:
                        resource.setrlimit(resource.RLIMIT_AS, _orig_as)
                    except (ValueError, OSError):
                        pass
                if _orig_cpu is not None:
                    try:
                        resource.setrlimit(resource.RLIMIT_CPU, _orig_cpu)
                    except (ValueError, OSError):
                        pass

    async def execute_with_limits_async(
        self,
        agent_id: str,
        func: Callable,
        args: Optional[List[Any]] = None,
        kwargs: Optional[Dict[str, Any]] = None,
        operation: str = "execute",
    ) -> Any:
        """
        Execute a sync function asynchronously with timeout using asyncio.wait_for.
        Logs to the audit trail. Raises TimeoutError on timeout.

        Args:
            agent_id: Agent identifier
            func: Synchronous callable to execute
            args: Positional arguments for func
            kwargs: Keyword arguments for func
            operation: Operation name for audit log

        Returns:
            Result of func(*args, **kwargs)

        Raises:
            TimeoutError: If execution exceeds the agent's max_execution_time limit
            AgentError: If operation not allowed
        """
        context = self.get_context(agent_id)
        if not context:
            context = self.create_context(agent_id)

        if context.allowed_operations and operation not in context.allowed_operations:
            raise AgentError(
                f"Operation '{operation}' not allowed for agent '{agent_id}'",
                agent_id=agent_id,
                details={"operation": operation, "allowed": context.allowed_operations},
            )

        timeout = context.resource_limits.max_execution_time
        context.start_time = time.time()
        context.audit_log.append(
            {"timestamp": time.time(), "operation": operation, "action": "start"}
        )

        async def _run():
            return await asyncio.to_thread(func, *(args or []), **(kwargs or {}))

        try:
            if timeout > 0:
                result = await asyncio.wait_for(_run(), timeout=timeout)
            else:
                result = await _run()
            context.audit_log.append(
                {
                    "timestamp": time.time(),
                    "operation": operation,
                    "action": "success",
                    "duration": time.time() - context.start_time,
                }
            )
            return result
        except asyncio.TimeoutError:
            context.audit_log.append(
                {
                    "timestamp": time.time(),
                    "operation": operation,
                    "action": "timeout",
                    "timeout": timeout,
                }
            )
            raise TimeoutError(
                f"Execution timeout exceeded ({timeout}s) for agent '{agent_id}'"
            )
        except Exception as e:
            context.audit_log.append(
                {
                    "timestamp": time.time(),
                    "operation": operation,
                    "action": "error",
                    "error": str(e),
                }
            )
            raise

    def check_permission(
        self, agent_id: str, operation: str, resource: Optional[str] = None
    ) -> bool:
        """
        Check if agent has permission for an operation.

        Args:
            agent_id: Agent identifier
            operation: Operation to check
            resource: Optional resource identifier

        Returns:
            True if allowed, False otherwise
        """
        context = self.get_context(agent_id)
        if not context:
            return True  # Default: allow if no context

        if context.allowed_operations:
            return operation in context.allowed_operations

        return True  # Default: allow

    def get_audit_log(self, agent_id: str) -> list:
        """
        Get audit log for an agent.

        Args:
            agent_id: Agent identifier

        Returns:
            List of audit log entries
        """
        context = self.get_context(agent_id)
        if context:
            return context.audit_log.copy()
        return []

    def clear_context(self, agent_id: str):
        """
        Clear execution context for an agent.

        Args:
            agent_id: Agent identifier
        """
        if agent_id in self._contexts:
            del self._contexts[agent_id]


# Global sandbox instance
_sandbox: Optional[AgentSandbox] = None


def get_sandbox() -> AgentSandbox:
    """Get the global sandbox instance."""
    global _sandbox
    if _sandbox is None:
        _sandbox = AgentSandbox()
    return _sandbox
