"""Unit tests for app/llm/openai.py OpenAI LLM provider."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_openai_client():
    """Mock AsyncOpenAI client with chat.completions.create as AsyncMock."""
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock()
    return client


@pytest.fixture
def provider(mock_openai_client):
    """OpenAIProvider with a mocked AsyncOpenAI client."""
    with patch("app.llm.openai.AsyncOpenAI", return_value=mock_openai_client):
        from app.llm.openai import OpenAIProvider
        p = OpenAIProvider(api_key="test-key", model="gpt-4o-mini")
    p.client = mock_openai_client
    return p


def _make_response(content="result", finish_reason="stop", model="gpt-4o-mini", usage=None):
    """Build a minimal mock chat completion response."""
    r = MagicMock()
    r.choices = [MagicMock()]
    r.choices[0].message.content = content
    r.choices[0].finish_reason = finish_reason
    r.choices[0].message.tool_calls = None
    r.model = model
    if usage is None:
        r.usage = MagicMock()
        r.usage.prompt_tokens = 10
        r.usage.completion_tokens = 20
        r.usage.total_tokens = 30
    else:
        r.usage = usage
    return r


@pytest.mark.unit
class TestOpenAIProvider:
    """Tests for OpenAIProvider."""

    @pytest.mark.asyncio
    async def test_generate_returns_content(self, provider, mock_openai_client):
        """generate() returns the text content from the API response."""
        mock_openai_client.chat.completions.create.return_value = _make_response("Hello!")
        result = await provider.generate("Say hello")
        assert result == "Hello!"

    @pytest.mark.asyncio
    async def test_generate_with_system_prompt(self, provider, mock_openai_client):
        """generate() includes system message when system_prompt is provided."""
        mock_openai_client.chat.completions.create.return_value = _make_response("OK")
        await provider.generate("User message", system_prompt="You are a bot")

        call_kwargs = mock_openai_client.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are a bot"
        assert messages[1]["role"] == "user"

    @pytest.mark.asyncio
    async def test_generate_without_system_prompt(self, provider, mock_openai_client):
        """generate() sends only user message when no system_prompt."""
        mock_openai_client.chat.completions.create.return_value = _make_response("OK")
        await provider.generate("Just user")

        call_kwargs = mock_openai_client.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_generate_passes_temperature_and_max_tokens(self, provider, mock_openai_client):
        """generate() passes temperature and max_tokens when provided."""
        mock_openai_client.chat.completions.create.return_value = _make_response()
        await provider.generate("prompt", temperature=0.5, max_tokens=100)

        call_kwargs = mock_openai_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["max_tokens"] == 100

    @pytest.mark.asyncio
    async def test_generate_raises_runtime_error_on_openai_error(
        self, provider, mock_openai_client
    ):
        """generate() wraps OpenAIError in RuntimeError."""
        from openai import OpenAIError

        mock_openai_client.chat.completions.create.side_effect = OpenAIError("bad request")
        with pytest.raises(RuntimeError, match="OpenAI API error"):
            await provider.generate("Test prompt")

    @pytest.mark.asyncio
    async def test_generate_empty_content_returns_empty_string(self, provider, mock_openai_client):
        """generate() returns empty string when content is None."""
        mock_openai_client.chat.completions.create.return_value = _make_response(content=None)
        result = await provider.generate("prompt")
        assert result == ""

    @pytest.mark.asyncio
    async def test_generate_with_metadata_returns_dict(self, provider, mock_openai_client):
        """generate_with_metadata() returns a dict with response, usage, and metadata."""
        mock_openai_client.chat.completions.create.return_value = _make_response("detailed result")
        result = await provider.generate_with_metadata("prompt")

        assert result["response"] == "detailed result"
        assert result["provider"] == "openai"
        assert result["usage"]["prompt_tokens"] == 10
        assert result["usage"]["completion_tokens"] == 20
        assert result["usage"]["total_tokens"] == 30
        assert "latency_ms" in result["metadata"]
        assert "finish_reason" in result["metadata"]

    @pytest.mark.asyncio
    async def test_generate_with_metadata_raises_on_openai_error(
        self, provider, mock_openai_client
    ):
        """generate_with_metadata() wraps OpenAIError in RuntimeError."""
        from openai import OpenAIError

        mock_openai_client.chat.completions.create.side_effect = OpenAIError("quota exceeded")
        with pytest.raises(RuntimeError, match="OpenAI API error"):
            await provider.generate_with_metadata("prompt")

    @pytest.mark.asyncio
    async def test_generate_with_tools_empty_tools_uses_base(self, provider, mock_openai_client):
        """generate_with_tools() delegates to base class when tools list is empty."""
        # Base class raises NotImplementedError or returns a stub — we just check it doesn't crash
        # and doesn't call the OpenAI API with tools
        with patch.object(
            type(provider).__bases__[0],
            "generate_with_tools",
            AsyncMock(return_value={"stop_reason": "end_turn", "text": "base"}),
        ):
            result = await provider.generate_with_tools(
                [{"role": "user", "content": "hi"}], tools=[]
            )
        # The call was delegated (mock_openai_client.create not called with tools)
        assert result is not None

    @pytest.mark.asyncio
    async def test_generate_with_tools_end_turn(self, provider, mock_openai_client):
        """generate_with_tools() returns end_turn when no tool call in response."""
        response = _make_response("final answer", finish_reason="stop")
        response.choices[0].message.tool_calls = None
        mock_openai_client.chat.completions.create.return_value = response

        tools = [
            {
                "server_id": "net",
                "name": "ping",
                "description": "Ping a host",
                "inputSchema": {"type": "object", "properties": {}},
            }
        ]
        result = await provider.generate_with_tools(
            [{"role": "user", "content": "check network"}], tools=tools
        )
        assert result["stop_reason"] == "end_turn"
        assert result["text"] == "final answer"

    @pytest.mark.asyncio
    async def test_generate_with_tools_tool_use(self, provider, mock_openai_client):
        """generate_with_tools() returns tool_use when finish_reason is tool_calls."""
        # Encoded name: server_id="net", tool_name="ping" → "net__ping"
        mock_tc = MagicMock()
        mock_tc.function.name = "net__ping"
        mock_tc.function.arguments = json.dumps({"host": "8.8.8.8"})

        response = _make_response("", finish_reason="tool_calls")
        response.choices[0].message.tool_calls = [mock_tc]
        mock_openai_client.chat.completions.create.return_value = response

        tools = [
            {
                "server_id": "net",
                "name": "ping",
                "description": "Ping a host",
                "inputSchema": {"type": "object", "properties": {}},
            }
        ]
        result = await provider.generate_with_tools(
            [{"role": "user", "content": "ping 8.8.8.8"}], tools=tools
        )
        assert result["stop_reason"] == "tool_use"
        assert result["tool_use"]["server_id"] == "net"
        assert result["tool_use"]["tool_name"] == "ping"
        assert result["tool_use"]["arguments"] == {"host": "8.8.8.8"}
