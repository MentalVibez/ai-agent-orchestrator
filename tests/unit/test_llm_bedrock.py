"""Unit tests for app/llm/bedrock.py — BedrockProvider."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from app.core.exceptions import LLMProviderError
from app.llm.bedrock import BedrockProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client_error(code: str, message: str = "Error") -> ClientError:
    """Build a botocore ClientError with the given error code."""
    return ClientError(
        {"Error": {"Code": code, "Message": message}},
        "InvokeModel",
    )


def _make_invoke_response(text: str, input_tokens: int = 10, output_tokens: int = 5) -> dict:
    """Return a mock invoke_model response dict with a readable body."""
    mock_body = MagicMock()
    mock_body.read.return_value = json.dumps(
        {
            "content": [{"text": text}],
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        }
    )
    return {"body": mock_body}


def _make_provider(region: str = "us-east-1", model: str = "claude-3") -> tuple:
    """Build a BedrockProvider with a mocked boto3 client."""
    mock_client = MagicMock()
    with patch("boto3.client", return_value=mock_client):
        provider = BedrockProvider(region=region, model=model)
    return provider, mock_client


async def _passthrough_retry(func, config=None):
    """Passthrough for retry_async — executes func exactly once with no retries."""
    return await func()


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestBedrockInit:
    def test_uses_explicit_region_and_model(self):
        mock_client = MagicMock()
        with patch("boto3.client", return_value=mock_client) as mock_boto:
            provider = BedrockProvider(region="eu-west-1", model="my-model")

        assert provider.region == "eu-west-1"
        assert provider.model == "my-model"
        assert provider.bedrock_runtime is mock_client
        mock_boto.assert_called_once()

    def test_falls_back_to_settings_for_region_and_model(self):
        mock_client = MagicMock()
        with patch("boto3.client", return_value=mock_client), patch(
            "app.llm.bedrock.settings"
        ) as mock_settings:
            mock_settings.aws_region = "ap-southeast-1"
            mock_settings.llm_model = "claude-settings-model"
            mock_settings.aws_access_key_id = "AK"
            mock_settings.aws_secret_access_key = "SK"
            provider = BedrockProvider()

        assert provider.region == "ap-southeast-1"
        assert provider.model == "claude-settings-model"

    def test_explicit_credentials_passed_to_boto3(self):
        mock_client = MagicMock()
        with patch("boto3.client", return_value=mock_client) as mock_boto:
            BedrockProvider(
                region="us-west-2",
                model="m",
                access_key_id="AKID123",
                secret_access_key="secret456",
            )

        call_kwargs = mock_boto.call_args[1]
        assert call_kwargs["aws_access_key_id"] == "AKID123"
        assert call_kwargs["aws_secret_access_key"] == "secret456"


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------


class TestBedrockGenerate:
    @pytest.mark.asyncio
    async def test_happy_path_returns_text(self):
        provider, _ = _make_provider()
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(
            return_value=_make_invoke_response("Result text")
        )

        with patch("app.llm.bedrock.asyncio.get_running_loop", return_value=mock_loop), patch(
            "app.llm.bedrock.retry_async", side_effect=_passthrough_retry
        ), patch("app.llm.bedrock.get_cost_tracker"):
            result = await provider.generate("test prompt")

        assert result == "Result text"

    @pytest.mark.asyncio
    async def test_records_cost_with_token_counts(self):
        provider, _ = _make_provider()
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(
            return_value=_make_invoke_response("text", input_tokens=20, output_tokens=10)
        )

        with patch("app.llm.bedrock.asyncio.get_running_loop", return_value=mock_loop), patch(
            "app.llm.bedrock.retry_async", side_effect=_passthrough_retry
        ), patch("app.llm.bedrock.get_cost_tracker") as mock_ct:
            mock_record = MagicMock()
            mock_ct.return_value.record_cost = mock_record
            await provider.generate("hi")

        mock_record.assert_called_once()
        kw = mock_record.call_args[1]
        assert kw["input_tokens"] == 20
        assert kw["output_tokens"] == 10
        assert kw["provider"] == "bedrock"

    @pytest.mark.asyncio
    async def test_with_system_prompt(self):
        provider, _ = _make_provider()
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(
            return_value=_make_invoke_response("ok")
        )

        with patch("app.llm.bedrock.asyncio.get_running_loop", return_value=mock_loop), patch(
            "app.llm.bedrock.retry_async", side_effect=_passthrough_retry
        ), patch("app.llm.bedrock.get_cost_tracker"):
            result = await provider.generate("user prompt", system_prompt="Be helpful.")

        assert result == "ok"
        mock_loop.run_in_executor.assert_called_once()

    @pytest.mark.asyncio
    async def test_instance_attributes_forwarded_to_cost_tracker(self):
        """_current_agent_id, _current_endpoint, _current_request_id forwarded."""
        provider, _ = _make_provider()
        provider._current_agent_id = "agent-42"
        provider._current_endpoint = "/run"
        provider._current_request_id = "req-1"
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(
            return_value=_make_invoke_response("hi")
        )

        with patch("app.llm.bedrock.asyncio.get_running_loop", return_value=mock_loop), patch(
            "app.llm.bedrock.retry_async", side_effect=_passthrough_retry
        ), patch("app.llm.bedrock.get_cost_tracker") as mock_ct:
            mock_record = MagicMock()
            mock_ct.return_value.record_cost = mock_record
            await provider.generate("prompt")

        kw = mock_record.call_args[1]
        assert kw["agent_id"] == "agent-42"
        assert kw["endpoint"] == "/run"
        assert kw["request_id"] == "req-1"

    @pytest.mark.asyncio
    async def test_empty_content_list_raises_llm_provider_error(self):
        provider, _ = _make_provider()
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps({"content": [], "usage": {}})
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(return_value={"body": mock_body})

        with patch("app.llm.bedrock.asyncio.get_running_loop", return_value=mock_loop), patch(
            "app.llm.bedrock.retry_async", side_effect=_passthrough_retry
        ):
            with pytest.raises(LLMProviderError):
                await provider.generate("hello")

    @pytest.mark.asyncio
    async def test_no_content_key_raises_llm_provider_error(self):
        provider, _ = _make_provider()
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps({"result": "unexpected"})
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(return_value={"body": mock_body})

        with patch("app.llm.bedrock.asyncio.get_running_loop", return_value=mock_loop), patch(
            "app.llm.bedrock.retry_async", side_effect=_passthrough_retry
        ):
            with pytest.raises(LLMProviderError):
                await provider.generate("hello")

    @pytest.mark.asyncio
    async def test_validation_exception_raises_llm_provider_error(self):
        provider, _ = _make_provider()
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(
            side_effect=_client_error("ValidationException", "Bad request")
        )

        with patch("app.llm.bedrock.asyncio.get_running_loop", return_value=mock_loop), patch(
            "app.llm.bedrock.retry_async", side_effect=_passthrough_retry
        ):
            with pytest.raises(LLMProviderError, match="ValidationException"):
                await provider.generate("hello")

    @pytest.mark.asyncio
    async def test_access_denied_exception_raises_llm_provider_error(self):
        provider, _ = _make_provider()
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(
            side_effect=_client_error("AccessDeniedException")
        )

        with patch("app.llm.bedrock.asyncio.get_running_loop", return_value=mock_loop), patch(
            "app.llm.bedrock.retry_async", side_effect=_passthrough_retry
        ):
            with pytest.raises(LLMProviderError, match="AccessDeniedException"):
                await provider.generate("hello")

    @pytest.mark.asyncio
    async def test_resource_not_found_raises_llm_provider_error(self):
        provider, _ = _make_provider()
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(
            side_effect=_client_error("ResourceNotFoundException")
        )

        with patch("app.llm.bedrock.asyncio.get_running_loop", return_value=mock_loop), patch(
            "app.llm.bedrock.retry_async", side_effect=_passthrough_retry
        ):
            with pytest.raises(LLMProviderError, match="ResourceNotFoundException"):
                await provider.generate("hello")

    @pytest.mark.asyncio
    async def test_throttling_exception_reraises_for_retry_layer(self):
        """ThrottlingException is not in the non-retryable list — it propagates."""
        provider, _ = _make_provider()
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(
            side_effect=_client_error("ThrottlingException")
        )

        with patch("app.llm.bedrock.asyncio.get_running_loop", return_value=mock_loop), patch(
            "app.llm.bedrock.retry_async", side_effect=_passthrough_retry
        ):
            with pytest.raises(ClientError):
                await provider.generate("hello")

    @pytest.mark.asyncio
    async def test_json_decode_error_raises_llm_provider_error(self):
        provider, _ = _make_provider()
        mock_body = MagicMock()
        mock_body.read.return_value = "not-valid-json{"
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(return_value={"body": mock_body})

        with patch("app.llm.bedrock.asyncio.get_running_loop", return_value=mock_loop), patch(
            "app.llm.bedrock.retry_async", side_effect=_passthrough_retry
        ):
            with pytest.raises(LLMProviderError, match="Failed to parse"):
                await provider.generate("hello")


# ---------------------------------------------------------------------------
# stream
# ---------------------------------------------------------------------------


class TestBedrockStream:
    @pytest.mark.asyncio
    async def test_stream_delta_text_chunks(self):
        provider, _ = _make_provider()
        events = [
            {"chunk": {"bytes": json.dumps({"delta": {"text": "Hello"}})}},
            {"chunk": {"bytes": json.dumps({"delta": {"text": " world"}})}},
        ]
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(return_value={"body": events})

        with patch("app.llm.bedrock.asyncio.get_running_loop", return_value=mock_loop):
            chunks = [chunk async for chunk in provider.stream("hi")]

        assert chunks == ["Hello", " world"]

    @pytest.mark.asyncio
    async def test_stream_content_block_delta_chunks(self):
        provider, _ = _make_provider()
        events = [
            {
                "chunk": {
                    "bytes": json.dumps(
                        {"content_block_delta": {"delta": {"text": "block chunk"}}}
                    )
                }
            },
        ]
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(return_value={"body": events})

        with patch("app.llm.bedrock.asyncio.get_running_loop", return_value=mock_loop):
            chunks = [chunk async for chunk in provider.stream("hi")]

        assert chunks == ["block chunk"]

    @pytest.mark.asyncio
    async def test_stream_mixed_event_types_skips_unknown(self):
        """Events without recognized delta keys are skipped."""
        provider, _ = _make_provider()
        events = [
            {"chunk": {"bytes": json.dumps({"delta": {"text": "A"}})}},
            {"chunk": {"bytes": json.dumps({"other_key": "ignored"})}},
            {"chunk": {"bytes": json.dumps({"delta": {"text": "B"}})}},
            {"other_event": "no chunk key"},
        ]
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(return_value={"body": events})

        with patch("app.llm.bedrock.asyncio.get_running_loop", return_value=mock_loop):
            chunks = [chunk async for chunk in provider.stream("hi")]

        assert chunks == ["A", "B"]

    @pytest.mark.asyncio
    async def test_stream_with_system_prompt(self):
        provider, _ = _make_provider()
        events = [{"chunk": {"bytes": json.dumps({"delta": {"text": "ok"}})}}]
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(return_value={"body": events})

        with patch("app.llm.bedrock.asyncio.get_running_loop", return_value=mock_loop):
            chunks = [chunk async for chunk in provider.stream("prompt", system_prompt="sys")]

        assert "ok" in chunks

    @pytest.mark.asyncio
    async def test_stream_falsy_body_yields_nothing(self):
        """If body is None/falsy, stream yields nothing."""
        provider, _ = _make_provider()
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(return_value={"body": None})

        with patch("app.llm.bedrock.asyncio.get_running_loop", return_value=mock_loop):
            chunks = [chunk async for chunk in provider.stream("hi")]

        assert chunks == []

    @pytest.mark.asyncio
    async def test_stream_client_error_raises_runtime_error(self):
        provider, _ = _make_provider()
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(
            side_effect=_client_error("ThrottlingException", "Rate exceeded")
        )

        with patch("app.llm.bedrock.asyncio.get_running_loop", return_value=mock_loop):
            with pytest.raises(RuntimeError, match="Bedrock API error"):
                async for _ in provider.stream("hi"):
                    pass

    @pytest.mark.asyncio
    async def test_stream_generic_exception_raises_runtime_error(self):
        provider, _ = _make_provider()
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(side_effect=OSError("connection failed"))

        with patch("app.llm.bedrock.asyncio.get_running_loop", return_value=mock_loop):
            with pytest.raises(RuntimeError, match="Unexpected error"):
                async for _ in provider.stream("hi"):
                    pass


# ---------------------------------------------------------------------------
# generate_with_metadata
# ---------------------------------------------------------------------------


class TestBedrockGenerateWithMetadata:
    @pytest.mark.asyncio
    async def test_returns_text_and_metadata(self):
        provider, _ = _make_provider()
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps(
            {
                "content": [{"text": "Meta response"}],
                "usage": {"input_tokens": 15, "output_tokens": 8},
            }
        )
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(return_value={"body": mock_body})

        with patch("app.llm.bedrock.asyncio.get_running_loop", return_value=mock_loop):
            result = await provider.generate_with_metadata("prompt")

        assert result["text"] == "Meta response"
        assert result["metadata"]["input_tokens"] == 15
        assert result["metadata"]["output_tokens"] == 8
        assert result["metadata"]["total_tokens"] == 23
        assert "latency_seconds" in result["metadata"]
        assert result["metadata"]["model"] == provider.model
        assert result["metadata"]["region"] == provider.region

    @pytest.mark.asyncio
    async def test_with_system_prompt(self):
        provider, _ = _make_provider()
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps({"content": [{"text": "ok"}], "usage": {}})
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(return_value={"body": mock_body})

        with patch("app.llm.bedrock.asyncio.get_running_loop", return_value=mock_loop):
            result = await provider.generate_with_metadata("q", system_prompt="sys")

        assert result["text"] == "ok"

    @pytest.mark.asyncio
    async def test_empty_content_list_returns_empty_text(self):
        provider, _ = _make_provider()
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps({"content": [], "usage": {}})
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(return_value={"body": mock_body})

        with patch("app.llm.bedrock.asyncio.get_running_loop", return_value=mock_loop):
            result = await provider.generate_with_metadata("q")

        assert result["text"] == ""

    @pytest.mark.asyncio
    async def test_no_content_key_returns_empty_text(self):
        provider, _ = _make_provider()
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps({"usage": {}})
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(return_value={"body": mock_body})

        with patch("app.llm.bedrock.asyncio.get_running_loop", return_value=mock_loop):
            result = await provider.generate_with_metadata("q")

        assert result["text"] == ""

    @pytest.mark.asyncio
    async def test_client_error_raises_runtime_error(self):
        provider, _ = _make_provider()
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(
            side_effect=_client_error("AccessDeniedException", "Denied")
        )

        with patch("app.llm.bedrock.asyncio.get_running_loop", return_value=mock_loop):
            with pytest.raises(RuntimeError, match="Bedrock API error"):
                await provider.generate_with_metadata("q")

    @pytest.mark.asyncio
    async def test_generic_exception_raises_runtime_error(self):
        provider, _ = _make_provider()
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(side_effect=OSError("network error"))

        with patch("app.llm.bedrock.asyncio.get_running_loop", return_value=mock_loop):
            with pytest.raises(RuntimeError, match="Unexpected error"):
                await provider.generate_with_metadata("q")


# ---------------------------------------------------------------------------
# generate_with_tools
# ---------------------------------------------------------------------------


class TestBedrockGenerateWithTools:
    @pytest.mark.asyncio
    async def test_no_tools_delegates_to_base_class(self):
        """Empty tools list falls back to base class generate_with_tools → generate."""
        provider, _ = _make_provider()
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(
            return_value=_make_invoke_response("Base response")
        )

        with patch("app.llm.bedrock.asyncio.get_running_loop", return_value=mock_loop), patch(
            "app.llm.bedrock.retry_async", side_effect=_passthrough_retry
        ), patch("app.llm.bedrock.get_cost_tracker"):
            result = await provider.generate_with_tools(
                [{"role": "user", "content": "hello"}], []
            )

        assert result["stop_reason"] == "text"
        assert result["text"] == "Base response"

    @pytest.mark.asyncio
    async def test_tool_use_stop_reason_returns_tool_use_dict(self):
        provider, _ = _make_provider()
        converse_response = {
            "stopReason": "tool_use",
            "output": {
                "message": {
                    "content": [
                        {
                            "toolUse": {
                                "name": "srv__mytool",
                                "input": {"param": "value"},
                            }
                        }
                    ]
                }
            },
        }

        with patch(
            "app.llm.bedrock.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=converse_response,
        ):
            result = await provider.generate_with_tools(
                [{"role": "user", "content": "run tool"}],
                [{"server_id": "srv", "name": "mytool", "description": "A tool"}],
            )

        assert result["stop_reason"] == "tool_use"
        assert result["tool_use"]["server_id"] == "srv"
        assert result["tool_use"]["tool_name"] == "mytool"
        assert result["tool_use"]["arguments"] == {"param": "value"}
        assert result["text"] == ""

    @pytest.mark.asyncio
    async def test_tool_use_with_none_input_defaults_to_empty_dict(self):
        """toolUse block with input=None defaults to {}."""
        provider, _ = _make_provider()
        converse_response = {
            "stopReason": "tool_use",
            "output": {
                "message": {
                    "content": [{"toolUse": {"name": "srv__t", "input": None}}]
                }
            },
        }

        with patch(
            "app.llm.bedrock.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=converse_response,
        ):
            result = await provider.generate_with_tools(
                [{"role": "user", "content": "go"}],
                [{"server_id": "srv", "name": "t", "description": "tool"}],
            )

        assert result["tool_use"]["arguments"] == {}

    @pytest.mark.asyncio
    async def test_end_turn_returns_text(self):
        provider, _ = _make_provider()
        converse_response = {
            "stopReason": "end_turn",
            "output": {
                "message": {
                    "content": [{"text": "Here is the answer."}]
                }
            },
        }

        with patch(
            "app.llm.bedrock.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=converse_response,
        ):
            result = await provider.generate_with_tools(
                [{"role": "user", "content": "question"}],
                [{"server_id": "s", "name": "t", "description": "tool"}],
            )

        assert result["stop_reason"] == "end_turn"
        assert result["text"] == "Here is the answer."

    @pytest.mark.asyncio
    async def test_multiple_text_blocks_concatenated(self):
        """Multiple text blocks in content are joined."""
        provider, _ = _make_provider()
        converse_response = {
            "stopReason": "end_turn",
            "output": {
                "message": {
                    "content": [{"text": "Part 1. "}, {"text": "Part 2."}]
                }
            },
        }

        with patch(
            "app.llm.bedrock.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=converse_response,
        ):
            result = await provider.generate_with_tools(
                [{"role": "user", "content": "q"}],
                [{"server_id": "s", "name": "t", "description": "d"}],
            )

        assert result["text"] == "Part 1. Part 2."

    @pytest.mark.asyncio
    async def test_with_system_prompt_included(self):
        provider, _ = _make_provider()
        converse_response = {
            "stopReason": "end_turn",
            "output": {"message": {"content": [{"text": "ok"}]}},
        }

        with patch(
            "app.llm.bedrock.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=converse_response,
        ) as mock_thread:
            await provider.generate_with_tools(
                [{"role": "user", "content": "hi"}],
                [{"server_id": "s", "name": "t", "description": "tool"}],
                system_prompt="Be concise.",
            )

        # Confirm system prompt was passed to the Converse call
        call_kwargs = mock_thread.call_args[1]
        assert call_kwargs["system"] == [{"text": "Be concise."}]

    @pytest.mark.asyncio
    async def test_empty_system_prompt_sends_empty_list(self):
        provider, _ = _make_provider()
        converse_response = {
            "stopReason": "end_turn",
            "output": {"message": {"content": []}},
        }

        with patch(
            "app.llm.bedrock.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=converse_response,
        ) as mock_thread:
            await provider.generate_with_tools(
                [{"role": "user", "content": "hi"}],
                [{"server_id": "s", "name": "t", "description": "tool"}],
            )

        call_kwargs = mock_thread.call_args[1]
        assert call_kwargs["system"] == []

    @pytest.mark.asyncio
    async def test_messages_converted_to_bedrock_format(self):
        """Multi-turn conversation is correctly reformatted for Bedrock."""
        provider, _ = _make_provider()
        converse_response = {
            "stopReason": "end_turn",
            "output": {"message": {"content": [{"text": "fine"}]}},
        }

        with patch(
            "app.llm.bedrock.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=converse_response,
        ) as mock_thread:
            await provider.generate_with_tools(
                [
                    {"role": "user", "content": "first"},
                    {"role": "assistant", "content": "response"},
                    {"role": "user", "content": "follow up"},
                ],
                [{"server_id": "s", "name": "t", "description": "d"}],
            )

        call_kwargs = mock_thread.call_args[1]
        msgs = call_kwargs["messages"]
        assert len(msgs) == 3
        assert msgs[0]["content"] == [{"text": "first"}]
        assert msgs[1]["role"] == "assistant"
        assert msgs[2]["content"] == [{"text": "follow up"}]

    @pytest.mark.asyncio
    async def test_converse_exception_raises_runtime_error(self):
        provider, _ = _make_provider()

        with patch(
            "app.llm.bedrock.asyncio.to_thread",
            new_callable=AsyncMock,
            side_effect=Exception("Converse failed"),
        ):
            with pytest.raises(RuntimeError, match="Bedrock Converse API error"):
                await provider.generate_with_tools(
                    [{"role": "user", "content": "hi"}],
                    [{"server_id": "s", "name": "t", "description": "tool"}],
                )

    @pytest.mark.asyncio
    async def test_tool_use_stop_reason_with_no_tool_use_block_falls_through(self):
        """stopReason=tool_use but no toolUse block → falls through to end_turn text."""
        provider, _ = _make_provider()
        converse_response = {
            "stopReason": "tool_use",
            "output": {
                "message": {
                    "content": [{"text": "fallthrough text"}]
                }
            },
        }

        with patch(
            "app.llm.bedrock.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=converse_response,
        ):
            result = await provider.generate_with_tools(
                [{"role": "user", "content": "hi"}],
                [{"server_id": "s", "name": "t", "description": "d"}],
            )

        # Falls through to text extraction block
        assert result["text"] == "fallthrough text"
