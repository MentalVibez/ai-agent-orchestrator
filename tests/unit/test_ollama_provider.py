"""Unit tests for app/llm/ollama.py Ollama LLM provider."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def provider():
    """OllamaProvider with a mocked httpx.AsyncClient."""
    with patch("app.llm.ollama.httpx.AsyncClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        from app.llm.ollama import OllamaProvider
        p = OllamaProvider(base_url="http://localhost:11434", model="llama3")
    p.client = mock_client
    return p


def _make_httpx_response(data: dict, status_code: int = 200):
    """Build a minimal mock httpx response."""
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = data
    r.raise_for_status = MagicMock()
    return r


@pytest.mark.unit
class TestOllamaProvider:
    """Tests for OllamaProvider."""

    def test_build_payload_basic(self, provider):
        """_build_payload() includes model, prompt, and stream flag."""
        payload = provider._build_payload("hello", None, None, None, stream=False)
        assert payload["model"] == "llama3"
        assert payload["prompt"] == "hello"
        assert payload["stream"] is False
        assert "system" not in payload
        assert "options" not in payload

    def test_build_payload_with_system_prompt(self, provider):
        """_build_payload() includes system key when system_prompt is given."""
        payload = provider._build_payload("hello", "Be concise", None, None, stream=False)
        assert payload["system"] == "Be concise"

    def test_build_payload_with_options(self, provider):
        """_build_payload() includes options dict for temperature and max_tokens."""
        payload = provider._build_payload("hello", None, 0.8, 200, stream=False)
        assert "options" in payload
        assert payload["options"]["temperature"] == 0.8
        assert payload["options"]["num_predict"] == 200

    @pytest.mark.asyncio
    async def test_generate_returns_response_text(self, provider):
        """generate() posts to /api/generate and returns the 'response' field."""
        provider.client.post = AsyncMock(
            return_value=_make_httpx_response({"response": "42 is the answer."})
        )
        result = await provider.generate("What is the answer?")
        assert result == "42 is the answer."
        provider.client.post.assert_called_once()
        call_args = provider.client.post.call_args
        assert call_args[0][0] == "/api/generate"

    @pytest.mark.asyncio
    async def test_generate_returns_empty_on_missing_key(self, provider):
        """generate() returns '' when 'response' key is absent from API response."""
        provider.client.post = AsyncMock(
            return_value=_make_httpx_response({})
        )
        result = await provider.generate("prompt")
        assert result == ""

    @pytest.mark.asyncio
    async def test_generate_with_metadata_returns_dict(self, provider):
        """generate_with_metadata() returns structured dict with usage and metadata."""
        provider.client.post = AsyncMock(
            return_value=_make_httpx_response({
                "response": "answer",
                "model": "llama3",
                "prompt_eval_count": 15,
                "eval_count": 25,
                "total_duration": 1000000,
                "load_duration": 500000,
                "eval_duration": 400000,
            })
        )
        result = await provider.generate_with_metadata("prompt")
        assert result["response"] == "answer"
        assert result["provider"] == "ollama"
        assert result["usage"]["prompt_tokens"] == 15
        assert result["usage"]["completion_tokens"] == 25
        assert result["usage"]["total_tokens"] == 40
        assert result["metadata"]["total_duration"] == 1000000

    @pytest.mark.asyncio
    async def test_generate_with_system_prompt(self, provider):
        """generate() includes system prompt in the payload."""
        provider.client.post = AsyncMock(
            return_value=_make_httpx_response({"response": "OK"})
        )
        await provider.generate("prompt", system_prompt="You are helpful")
        call_kwargs = provider.client.post.call_args.kwargs
        payload = call_kwargs["json"]
        assert payload["system"] == "You are helpful"

    @pytest.mark.asyncio
    async def test_generate_propagates_httpx_error(self, provider):
        """generate() propagates errors from httpx (e.g., raise_for_status)."""
        import httpx
        mock_response = _make_httpx_response({}, status_code=500)
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server error", request=MagicMock(), response=mock_response
        )
        provider.client.post = AsyncMock(return_value=mock_response)
        with pytest.raises(httpx.HTTPStatusError):
            await provider.generate("prompt")
