"""Circuit breaker wrappers for LLM and MCP external calls.

Uses pybreaker to prevent thundering-herd cascades when a downstream service
(AWS Bedrock, OpenAI, Ollama, MCP server) is degraded or down.

States
------
CLOSED  — normal; calls pass through.
OPEN    — downstream is failing; all calls fail-fast with CircuitBreakerError.
HALF_OPEN — after reset_timeout, one probe call is allowed through; success → CLOSED,
            failure → OPEN again.

Default thresholds (tunable via env vars):
  CIRCUIT_BREAKER_FAIL_MAX         = 5   consecutive failures to open
  CIRCUIT_BREAKER_RESET_TIMEOUT    = 60  seconds before probing again

Health check exposes breaker states via ``get_breaker_states()``.
"""

import logging
import os

logger = logging.getLogger(__name__)

_FAIL_MAX = int(os.getenv("CIRCUIT_BREAKER_FAIL_MAX", "5"))
_RESET_TIMEOUT = int(os.getenv("CIRCUIT_BREAKER_RESET_TIMEOUT", "60"))


def _make_breaker(name: str):
    """Build a named CircuitBreaker, falling back gracefully if pybreaker is absent."""
    try:
        import pybreaker

        class _LogListener(pybreaker.CircuitBreakerListener):
            def state_change(self, cb, old_state, new_state):
                logger.warning(
                    "circuit_breaker: '%s' changed from %s → %s",
                    cb.name,
                    old_state.name,
                    new_state.name,
                )

        return pybreaker.CircuitBreaker(
            fail_max=_FAIL_MAX,
            reset_timeout=_RESET_TIMEOUT,
            name=name,
            listeners=[_LogListener()],
        )
    except ImportError:
        logger.warning(
            "circuit_breaker: pybreaker not installed — '%s' breaker is a no-op. "
            "Add pybreaker to requirements.txt to enable circuit breaking.",
            name,
        )
        return None


# One breaker per logical downstream service
_llm_breaker = _make_breaker("llm_provider")
_mcp_breaker = _make_breaker("mcp_tools")


def get_breaker_states() -> dict:
    """Return current state of all circuit breakers (for health check integration)."""
    states = {}
    for name, breaker in [("llm_provider", _llm_breaker), ("mcp_tools", _mcp_breaker)]:
        if breaker is None:
            states[name] = "disabled"
        else:
            states[name] = breaker.current_state
    return states


def is_llm_breaker_open() -> bool:
    """True when the LLM circuit is open (fast-fail mode)."""
    if _llm_breaker is None:
        return False
    try:
        import pybreaker
        return _llm_breaker.current_state == "open"
    except ImportError:
        return False


async def call_with_llm_breaker(coro):
    """Wrap an LLM coroutine with the LLM circuit breaker.

    Usage::

        result = await call_with_llm_breaker(provider.call_llm(...))
    """
    if _llm_breaker is None:
        return await coro

    import asyncio
    try:
        import pybreaker

        # pybreaker is sync; wrap async call via call()
        loop = asyncio.get_event_loop()
        future = asyncio.ensure_future(coro)

        def _sync_call():
            return loop.run_until_complete(future) if not loop.is_running() else None

        try:
            _llm_breaker.call(_sync_call)
        except pybreaker.CircuitBreakerError:
            future.cancel()
            raise
        return await future
    except ImportError:
        return await coro


async def call_with_mcp_breaker(coro):
    """Wrap an MCP tool coroutine with the MCP circuit breaker."""
    if _mcp_breaker is None:
        return await coro

    try:
        import pybreaker
        # Track failure/success manually for async calls
        try:
            result = await coro
            _mcp_breaker.call(lambda: None)  # record success
            return result
        except Exception as exc:
            try:
                _mcp_breaker.call(_raise(exc))
            except pybreaker.CircuitBreakerError:
                raise
            except Exception:
                pass
            raise
    except ImportError:
        return await coro


def _raise(exc):
    def _fn():
        raise exc
    return _fn
