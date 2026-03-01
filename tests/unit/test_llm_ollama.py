"""Unit tests for app/llm/ollama.py — OllamaProvider stream() coverage."""

import json
from unittest.mock import MagicMock

import pytest

from app.llm.ollama import OllamaProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MockResponse:
    """Fake httpx Response that streams lines."""

    def __init__(self, lines: list[str]):
        self._lines = lines

    def raise_for_status(self):
        pass

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _MockResponseRaises:
    """Fake httpx Response that raises on raise_for_status."""

    def raise_for_status(self):
        import httpx
        raise httpx.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock()
        )

    async def aiter_lines(self):
        return
        yield  # make it an async generator


class _MockStreamCtx:
    """Async context manager wrapping a mock response."""

    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *args):
        pass


def _make_provider():
    """Build an OllamaProvider — httpx.AsyncClient creation is harmless."""
    return OllamaProvider(base_url="http://localhost:11434", model="llama2")


# ---------------------------------------------------------------------------
# stream  (lines 73-87 — entirely uncovered)
# ---------------------------------------------------------------------------


class TestOllamaStream:
    @pytest.mark.asyncio
    async def test_stream_yields_response_text(self):
        """Happy path: lines with 'response' key are yielded."""
        provider = _make_provider()
        lines = [
            json.dumps({"response": "Hello", "done": False}),
            json.dumps({"response": " world", "done": False}),
            json.dumps({"response": "", "done": True}),
        ]
        provider.client = MagicMock()
        provider.client.stream.return_value = _MockStreamCtx(_MockResponse(lines))

        result = [chunk async for chunk in provider.stream("hi")]

        assert result == ["Hello", " world"]

    @pytest.mark.asyncio
    async def test_stream_stops_on_done_true(self):
        """When done=True is encountered, streaming stops immediately."""
        provider = _make_provider()
        lines = [
            json.dumps({"response": "first", "done": True}),
            json.dumps({"response": "should not appear", "done": False}),
        ]
        provider.client = MagicMock()
        provider.client.stream.return_value = _MockStreamCtx(_MockResponse(lines))

        result = [chunk async for chunk in provider.stream("q")]

        # "should not appear" must be absent — loop breaks on done=True
        assert result == ["first"]

    @pytest.mark.asyncio
    async def test_stream_skips_empty_lines(self):
        """Empty lines are skipped (line 78: if not line: continue)."""
        provider = _make_provider()
        lines = [
            "",
            json.dumps({"response": "A", "done": False}),
            "",
            json.dumps({"response": "B", "done": True}),
        ]
        provider.client = MagicMock()
        provider.client.stream.return_value = _MockStreamCtx(_MockResponse(lines))

        result = [chunk async for chunk in provider.stream("q")]

        assert result == ["A", "B"]

    @pytest.mark.asyncio
    async def test_stream_skips_json_decode_errors(self):
        """Lines that are not valid JSON are silently skipped (line 86: continue)."""
        provider = _make_provider()
        lines = [
            "not-valid-json{",
            json.dumps({"response": "valid", "done": True}),
        ]
        provider.client = MagicMock()
        provider.client.stream.return_value = _MockStreamCtx(_MockResponse(lines))

        result = [chunk async for chunk in provider.stream("q")]

        assert result == ["valid"]

    @pytest.mark.asyncio
    async def test_stream_skips_chunks_with_empty_response(self):
        """Chunks where response='' are not yielded (line 82: if text)."""
        provider = _make_provider()
        lines = [
            json.dumps({"response": "", "done": False}),
            json.dumps({"response": "content", "done": True}),
        ]
        provider.client = MagicMock()
        provider.client.stream.return_value = _MockStreamCtx(_MockResponse(lines))

        result = [chunk async for chunk in provider.stream("q")]

        assert result == ["content"]

    @pytest.mark.asyncio
    async def test_stream_with_system_prompt(self):
        """system_prompt is included in the request payload."""
        provider = _make_provider()
        lines = [json.dumps({"response": "ok", "done": True})]
        provider.client = MagicMock()
        provider.client.stream.return_value = _MockStreamCtx(_MockResponse(lines))

        result = [chunk async for chunk in provider.stream("q", system_prompt="sys")]

        assert "ok" in result
        # Verify system_prompt was in the posted payload
        call_kwargs = provider.client.stream.call_args[1]
        assert call_kwargs["json"]["system"] == "sys"

    @pytest.mark.asyncio
    async def test_stream_with_temperature_and_max_tokens(self):
        """temperature and max_tokens appear in payload options."""
        provider = _make_provider()
        lines = [json.dumps({"response": "x", "done": True})]
        provider.client = MagicMock()
        provider.client.stream.return_value = _MockStreamCtx(_MockResponse(lines))

        [chunk async for chunk in provider.stream("q", temperature=0.8, max_tokens=50)]

        payload = provider.client.stream.call_args[1]["json"]
        assert payload["options"]["temperature"] == 0.8
        assert payload["options"]["num_predict"] == 50

    @pytest.mark.asyncio
    async def test_stream_empty_response_yields_nothing(self):
        """A response stream with no data yields no chunks."""
        provider = _make_provider()
        provider.client = MagicMock()
        provider.client.stream.return_value = _MockStreamCtx(_MockResponse([]))

        result = [chunk async for chunk in provider.stream("q")]

        assert result == []
