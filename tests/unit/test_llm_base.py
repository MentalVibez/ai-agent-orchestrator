"""Unit tests for app/llm/base.py — LLMProvider abstract base class."""

from typing import AsyncIterator, Dict, Any, List, Optional
from unittest.mock import AsyncMock

import pytest

from app.llm.base import LLMProvider


# ---------------------------------------------------------------------------
# Minimal concrete subclass that calls super() to cover abstract method bodies
# ---------------------------------------------------------------------------


class _SuperCallingProvider(LLMProvider):
    """Delegates every method to super() to exercise abstract method bodies."""

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        return await super().generate(prompt, system_prompt=system_prompt, **kwargs)

    async def stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        # The base class body raises NotImplementedError — await the coroutine
        return await super().stream(prompt, system_prompt=system_prompt, **kwargs)  # type: ignore[return-value]

    async def generate_with_metadata(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return await super().generate_with_metadata(prompt, system_prompt=system_prompt, **kwargs)


# ---------------------------------------------------------------------------
# Minimal concrete subclass for generate_with_tools default fallback tests
# ---------------------------------------------------------------------------


class _WorkingProvider(LLMProvider):
    """Concrete provider with working generate for generate_with_tools testing."""

    def __init__(self, generate_response: str = "Generated response"):
        self._response = generate_response

    async def generate(self, prompt: str, system_prompt: Optional[str] = None, **kwargs: Any) -> str:
        return self._response

    async def stream(self, prompt: str, **kwargs: Any) -> AsyncIterator[str]:
        yield "chunk"

    async def generate_with_metadata(self, prompt: str, **kwargs: Any) -> Dict[str, Any]:
        return {"response": self._response, "tokens": 10}


# ---------------------------------------------------------------------------
# Abstract method body coverage (lines 32, 56, 80)
# ---------------------------------------------------------------------------


class TestLLMProviderAbstractBodies:
    @pytest.mark.asyncio
    async def test_generate_abstract_body_raises_not_implemented(self):
        p = _SuperCallingProvider()
        with pytest.raises(NotImplementedError, match="generate"):
            await p.generate("hello")

    @pytest.mark.asyncio
    async def test_stream_abstract_body_raises_not_implemented(self):
        p = _SuperCallingProvider()
        with pytest.raises(NotImplementedError, match="stream"):
            await p.stream("hello")

    @pytest.mark.asyncio
    async def test_generate_with_metadata_abstract_body_raises_not_implemented(self):
        p = _SuperCallingProvider()
        with pytest.raises(NotImplementedError, match="generate_with_metadata"):
            await p.generate_with_metadata("hello")


# ---------------------------------------------------------------------------
# generate_with_tools default implementation (lines 107-109)
# ---------------------------------------------------------------------------


class TestGenerateWithToolsDefault:
    @pytest.mark.asyncio
    async def test_falls_back_to_generate_with_last_message_content(self):
        """Default generate_with_tools uses the last message's content."""
        provider = _WorkingProvider("Generated response")
        messages = [
            {"role": "user", "content": "What time is it?"},
        ]
        tools = [{"name": "get_time", "description": "Get current time"}]

        result = await provider.generate_with_tools(messages, tools)

        assert result["stop_reason"] == "text"
        assert result["text"] == "Generated response"

    @pytest.mark.asyncio
    async def test_empty_messages_uses_empty_prompt(self):
        """With no messages, prompt is empty string."""
        provider = _WorkingProvider("No prompt response")
        result = await provider.generate_with_tools([], [])

        assert result["stop_reason"] == "text"
        assert result["text"] == "No prompt response"

    @pytest.mark.asyncio
    async def test_returns_stop_reason_text(self):
        """Default implementation always returns stop_reason='text'."""
        provider = _WorkingProvider("answer")
        result = await provider.generate_with_tools(
            [{"role": "user", "content": "hello"}], []
        )
        assert result["stop_reason"] == "text"

    @pytest.mark.asyncio
    async def test_passes_system_prompt_to_generate(self):
        """system_prompt kwarg is forwarded to generate()."""
        calls = []

        class _TracingProvider(LLMProvider):
            async def generate(self, prompt, system_prompt=None, **kw):
                calls.append({"prompt": prompt, "system_prompt": system_prompt})
                return "response"

            async def stream(self, prompt, **kw):
                yield ""

            async def generate_with_metadata(self, prompt, **kw):
                return {}

        provider = _TracingProvider()
        await provider.generate_with_tools(
            [{"role": "user", "content": "hi"}],
            [],
            system_prompt="You are helpful.",
        )
        assert calls[0]["system_prompt"] == "You are helpful."

    @pytest.mark.asyncio
    async def test_uses_content_of_last_message(self):
        """Only the last message's content is used as the prompt."""
        calls = []

        class _TracingProvider(LLMProvider):
            async def generate(self, prompt, **kw):
                calls.append(prompt)
                return "r"

            async def stream(self, prompt, **kw):
                yield ""

            async def generate_with_metadata(self, prompt, **kw):
                return {}

        provider = _TracingProvider()
        messages = [
            {"role": "user", "content": "first message"},
            {"role": "assistant", "content": "first response"},
            {"role": "user", "content": "actual question"},
        ]
        await provider.generate_with_tools(messages, [])
        assert calls[0] == "actual question"

    @pytest.mark.asyncio
    async def test_empty_content_key_uses_empty_string(self):
        """Message without 'content' key yields empty prompt."""
        calls = []

        class _TracingProvider(LLMProvider):
            async def generate(self, prompt, **kw):
                calls.append(prompt)
                return "r"

            async def stream(self, prompt, **kw):
                yield ""

            async def generate_with_metadata(self, prompt, **kw):
                return {}

        provider = _TracingProvider()
        await provider.generate_with_tools([{"role": "user"}], [])
        assert calls[0] == ""
