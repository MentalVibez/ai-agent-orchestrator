"""Unit tests for app/llm/openai.py — OpenAIProvider."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openai import OpenAIError

from app.llm.openai import OpenAIProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider(model: str = "gpt-4") -> tuple:
    """Build an OpenAIProvider with a mocked AsyncOpenAI client."""
    mock_client = MagicMock()
    with patch("app.llm.openai.AsyncOpenAI", return_value=mock_client):
        provider = OpenAIProvider(api_key="test-key", model=model)
    return provider, mock_client


def _make_response(content: str, model: str = "gpt-4", finish_reason: str = "stop"):
    """Build a mock chat completion response."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.choices[0].finish_reason = finish_reason
    resp.model = model
    resp.usage = MagicMock()
    resp.usage.prompt_tokens = 10
    resp.usage.completion_tokens = 5
    resp.usage.total_tokens = 15
    return resp


class _StreamCtx:
    """Async context manager + async iterator for streaming OpenAI responses."""

    def __init__(self, chunks: list):
        self._iter = iter(chunks)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


def _make_stream_chunk(content):
    """Build a mock stream chunk with choices[0].delta.content."""
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta.content = content
    return chunk


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestOpenAIInit:
    def test_uses_explicit_key_and_model(self):
        mock_client = MagicMock()
        with patch("app.llm.openai.AsyncOpenAI", return_value=mock_client) as MockCls:
            provider = OpenAIProvider(api_key="my-key", model="gpt-3.5-turbo")

        assert provider.api_key == "my-key"
        assert provider.model == "gpt-3.5-turbo"
        MockCls.assert_called_once_with(api_key="my-key")

    def test_falls_back_to_settings(self):
        mock_client = MagicMock()
        with patch("app.llm.openai.AsyncOpenAI", return_value=mock_client), patch(
            "app.llm.openai.settings"
        ) as mock_settings:
            mock_settings.openai_api_key = "settings-key"
            mock_settings.openai_model = "gpt-4-settings"
            provider = OpenAIProvider()

        assert provider.api_key == "settings-key"
        assert provider.model == "gpt-4-settings"


# ---------------------------------------------------------------------------
# _build_messages
# ---------------------------------------------------------------------------


class TestOpenAIBuildMessages:
    def test_without_system_prompt(self):
        provider, _ = _make_provider()
        msgs = provider._build_messages("hello", None)
        assert msgs == [{"role": "user", "content": "hello"}]

    def test_with_system_prompt(self):
        provider, _ = _make_provider()
        msgs = provider._build_messages("hello", "Be helpful.")
        assert msgs[0] == {"role": "system", "content": "Be helpful."}
        assert msgs[1] == {"role": "user", "content": "hello"}


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------


class TestOpenAIGenerate:
    @pytest.mark.asyncio
    async def test_happy_path_returns_content(self):
        provider, mock_client = _make_provider()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_response("Great answer")
        )
        result = await provider.generate("What is AI?")
        assert result == "Great answer"

    @pytest.mark.asyncio
    async def test_with_temperature_and_max_tokens(self):
        provider, mock_client = _make_provider()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_response("ok")
        )
        await provider.generate("q", temperature=0.2, max_tokens=50)
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["temperature"] == 0.2
        assert call_kwargs["max_tokens"] == 50

    @pytest.mark.asyncio
    async def test_openai_error_raises_runtime_error(self):
        provider, mock_client = _make_provider()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=OpenAIError("quota exceeded")
        )
        with pytest.raises(RuntimeError, match="OpenAI API error"):
            await provider.generate("q")

    @pytest.mark.asyncio
    async def test_none_content_returns_empty_string(self):
        provider, mock_client = _make_provider()
        resp = _make_response("placeholder")
        resp.choices[0].message.content = None
        mock_client.chat.completions.create = AsyncMock(return_value=resp)
        result = await provider.generate("q")
        assert result == ""


# ---------------------------------------------------------------------------
# stream  (lines 67–84 — entirely uncovered)
# ---------------------------------------------------------------------------


class TestOpenAIStream:
    @pytest.mark.asyncio
    async def test_stream_yields_delta_content(self):
        provider, mock_client = _make_provider()
        chunks = [_make_stream_chunk("Hello"), _make_stream_chunk(" world")]
        stream_ctx = _StreamCtx(chunks)
        mock_client.chat.completions.create = AsyncMock(return_value=stream_ctx)

        result = [c async for c in provider.stream("hi")]

        assert result == ["Hello", " world"]

    @pytest.mark.asyncio
    async def test_stream_skips_none_deltas(self):
        """Chunks with delta.content=None are not yielded."""
        provider, mock_client = _make_provider()
        chunks = [
            _make_stream_chunk("A"),
            _make_stream_chunk(None),
            _make_stream_chunk("B"),
        ]
        stream_ctx = _StreamCtx(chunks)
        mock_client.chat.completions.create = AsyncMock(return_value=stream_ctx)

        result = [c async for c in provider.stream("hi")]

        assert result == ["A", "B"]

    @pytest.mark.asyncio
    async def test_stream_with_system_prompt(self):
        provider, mock_client = _make_provider()
        chunks = [_make_stream_chunk("ok")]
        stream_ctx = _StreamCtx(chunks)
        mock_client.chat.completions.create = AsyncMock(return_value=stream_ctx)

        result = [c async for c in provider.stream("q", system_prompt="Be concise.")]

        assert "ok" in result

    @pytest.mark.asyncio
    async def test_stream_with_temperature_and_max_tokens(self):
        provider, mock_client = _make_provider()
        stream_ctx = _StreamCtx([_make_stream_chunk("x")])
        mock_client.chat.completions.create = AsyncMock(return_value=stream_ctx)

        result = [c async for c in provider.stream("q", temperature=0.7, max_tokens=100)]

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["temperature"] == 0.7
        assert call_kwargs["max_tokens"] == 100
        assert result == ["x"]

    @pytest.mark.asyncio
    async def test_stream_openai_error_raises_runtime_error(self):
        provider, mock_client = _make_provider()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=OpenAIError("stream broken")
        )
        with pytest.raises(RuntimeError, match="OpenAI API error"):
            async for _ in provider.stream("q"):
                pass

    @pytest.mark.asyncio
    async def test_stream_empty_yields_nothing(self):
        """An empty stream produces no output."""
        provider, mock_client = _make_provider()
        stream_ctx = _StreamCtx([])
        mock_client.chat.completions.create = AsyncMock(return_value=stream_ctx)

        result = [c async for c in provider.stream("q")]

        assert result == []


# ---------------------------------------------------------------------------
# generate_with_metadata
# ---------------------------------------------------------------------------


class TestOpenAIGenerateWithMetadata:
    @pytest.mark.asyncio
    async def test_returns_text_and_metadata(self):
        provider, mock_client = _make_provider()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_response("Answer", model="gpt-4", finish_reason="stop")
        )
        result = await provider.generate_with_metadata("prompt")

        assert result["response"] == "Answer"
        assert result["provider"] == "openai"
        assert result["model"] == "gpt-4"
        assert result["usage"]["prompt_tokens"] == 10
        assert result["usage"]["total_tokens"] == 15
        assert "latency_ms" in result["metadata"]
        assert result["metadata"]["finish_reason"] == "stop"

    @pytest.mark.asyncio
    async def test_temperature_and_max_tokens_forwarded(self):
        """Lines 100, 102 — temperature and max_tokens passed in params."""
        provider, mock_client = _make_provider()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_response("ok")
        )
        await provider.generate_with_metadata("q", temperature=0.5, max_tokens=200)

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["max_tokens"] == 200

    @pytest.mark.asyncio
    async def test_none_usage_fields_default_to_zero(self):
        """When usage is None, token counts default to 0."""
        provider, mock_client = _make_provider()
        resp = _make_response("text")
        resp.usage = None
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        result = await provider.generate_with_metadata("q")

        assert result["usage"]["prompt_tokens"] == 0
        assert result["usage"]["total_tokens"] == 0

    @pytest.mark.asyncio
    async def test_openai_error_raises_runtime_error(self):
        provider, mock_client = _make_provider()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=OpenAIError("server error")
        )
        with pytest.raises(RuntimeError, match="OpenAI API error"):
            await provider.generate_with_metadata("q")


# ---------------------------------------------------------------------------
# generate_with_tools
# ---------------------------------------------------------------------------


class TestOpenAIGenerateWithTools:
    @pytest.mark.asyncio
    async def test_no_tools_delegates_to_base_class(self):
        provider, mock_client = _make_provider()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_response("plain answer")
        )
        result = await provider.generate_with_tools(
            [{"role": "user", "content": "hi"}], []
        )
        assert result["stop_reason"] == "text"

    @pytest.mark.asyncio
    async def test_with_system_prompt_prepended(self):
        """Line 141 — system_prompt added to openai_messages."""
        provider, mock_client = _make_provider()
        resp = _make_response("ok")
        resp.choices[0].finish_reason = "stop"
        resp.choices[0].message.tool_calls = None
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        await provider.generate_with_tools(
            [{"role": "user", "content": "hi"}],
            [{"server_id": "s", "name": "t", "description": "d"}],
            system_prompt="You are a helper.",
        )

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["messages"][0] == {
            "role": "system",
            "content": "You are a helper.",
        }

    @pytest.mark.asyncio
    async def test_tool_calls_stop_reason_returns_tool_use(self):
        provider, mock_client = _make_provider()
        tc = MagicMock()
        tc.function.name = "srv__mytool"
        tc.function.arguments = '{"key": "val"}'
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].finish_reason = "tool_calls"
        resp.choices[0].message.tool_calls = [tc]
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        result = await provider.generate_with_tools(
            [{"role": "user", "content": "run it"}],
            [{"server_id": "srv", "name": "mytool", "description": "A tool"}],
        )

        assert result["stop_reason"] == "tool_use"
        assert result["tool_use"]["tool_name"] == "mytool"
        assert result["tool_use"]["arguments"] == {"key": "val"}

    @pytest.mark.asyncio
    async def test_json_decode_error_in_arguments_defaults_to_empty(self):
        """Lines 163-164 — invalid JSON in arguments falls back to {}."""
        provider, mock_client = _make_provider()
        tc = MagicMock()
        tc.function.name = "srv__t"
        tc.function.arguments = "not-valid-json{"
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].finish_reason = "tool_calls"
        resp.choices[0].message.tool_calls = [tc]
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        result = await provider.generate_with_tools(
            [{"role": "user", "content": "q"}],
            [{"server_id": "srv", "name": "t", "description": "d"}],
        )

        assert result["tool_use"]["arguments"] == {}

    @pytest.mark.asyncio
    async def test_end_turn_returns_text(self):
        provider, mock_client = _make_provider()
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].finish_reason = "stop"
        resp.choices[0].message.tool_calls = None
        resp.choices[0].message.content = "Final answer."
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        result = await provider.generate_with_tools(
            [{"role": "user", "content": "q"}],
            [{"server_id": "s", "name": "t", "description": "d"}],
        )

        assert result["stop_reason"] == "end_turn"
        assert result["text"] == "Final answer."

    @pytest.mark.asyncio
    async def test_openai_error_raises_runtime_error(self):
        """Lines 153-154 — OpenAIError in generate_with_tools."""
        provider, mock_client = _make_provider()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=OpenAIError("quota hit")
        )
        with pytest.raises(RuntimeError, match="OpenAI API error in generate_with_tools"):
            await provider.generate_with_tools(
                [{"role": "user", "content": "q"}],
                [{"server_id": "s", "name": "t", "description": "d"}],
            )

    @pytest.mark.asyncio
    async def test_none_content_returns_empty_string(self):
        provider, mock_client = _make_provider()
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].finish_reason = "stop"
        resp.choices[0].message.tool_calls = None
        resp.choices[0].message.content = None
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        result = await provider.generate_with_tools(
            [{"role": "user", "content": "q"}],
            [{"server_id": "s", "name": "t", "description": "d"}],
        )

        assert result["text"] == ""
