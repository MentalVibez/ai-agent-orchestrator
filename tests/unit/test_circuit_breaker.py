"""Unit tests for app/core/circuit_breaker.py."""

import pytest


@pytest.mark.unit
class TestGetBreakerStates:
    def test_returns_dict(self):
        from app.core.circuit_breaker import get_breaker_states
        states = get_breaker_states()
        assert isinstance(states, dict)

    def test_contains_expected_breaker_names(self):
        from app.core.circuit_breaker import get_breaker_states
        states = get_breaker_states()
        assert "llm_provider" in states
        assert "mcp_tools" in states

    def test_values_are_strings(self):
        from app.core.circuit_breaker import get_breaker_states
        states = get_breaker_states()
        for key, value in states.items():
            assert isinstance(value, str), f"Expected str for {key}, got {type(value)}"


@pytest.mark.unit
class TestIsLlmBreakerOpen:
    def test_returns_bool(self):
        from app.core.circuit_breaker import is_llm_breaker_open
        result = is_llm_breaker_open()
        assert isinstance(result, bool)

    def test_returns_false_when_closed(self):
        """A freshly created breaker should be in CLOSED state (not open)."""
        from app.core.circuit_breaker import is_llm_breaker_open
        assert is_llm_breaker_open() is False


@pytest.mark.unit
class TestCallWithLlmBreaker:
    @pytest.mark.asyncio
    async def test_passes_through_coroutine_result(self):
        from app.core.circuit_breaker import call_with_llm_breaker

        async def _mock_llm():
            return "llm-response"

        result = await call_with_llm_breaker(_mock_llm())
        assert result == "llm-response"

    @pytest.mark.asyncio
    async def test_propagates_exception(self):
        from app.core.circuit_breaker import call_with_llm_breaker

        async def _failing_llm():
            raise ValueError("LLM unavailable")

        with pytest.raises(ValueError, match="LLM unavailable"):
            await call_with_llm_breaker(_failing_llm())


@pytest.mark.unit
class TestCallWithMcpBreaker:
    @pytest.mark.asyncio
    async def test_passes_through_coroutine_result(self):
        from app.core.circuit_breaker import call_with_mcp_breaker

        async def _mock_tool():
            return {"output": "tool-result"}

        result = await call_with_mcp_breaker(_mock_tool())
        assert result == {"output": "tool-result"}

    @pytest.mark.asyncio
    async def test_propagates_exception(self):
        from app.core.circuit_breaker import call_with_mcp_breaker

        async def _failing_tool():
            raise RuntimeError("MCP server down")

        with pytest.raises(RuntimeError, match="MCP server down"):
            await call_with_mcp_breaker(_failing_tool())


@pytest.mark.unit
class TestCircuitBreakerGracefulDegradation:
    def test_module_imports_without_pybreaker(self):
        """Module must load even if pybreaker is not installed (graceful no-op)."""
        import importlib
        import sys

        # Temporarily hide pybreaker to test the fallback path
        original = sys.modules.get("pybreaker")
        sys.modules["pybreaker"] = None  # type: ignore[assignment]
        try:
            import app.core.circuit_breaker as cb_module
            importlib.reload(cb_module)
            # After reload without pybreaker, breakers should be None (disabled)
            states = cb_module.get_breaker_states()
            assert isinstance(states, dict)
        finally:
            if original is not None:
                sys.modules["pybreaker"] = original
            else:
                sys.modules.pop("pybreaker", None)
            importlib.reload(cb_module)
