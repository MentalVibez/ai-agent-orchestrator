"""OpenAI LLM provider implementation."""

import json
import time
from typing import Any, AsyncIterator, Dict, List, Optional

from openai import AsyncOpenAI, OpenAIError

from app.core.config import settings
from app.llm.base import LLMProvider
from app.llm.tool_schema import decode_tool_name, mcp_tools_to_openai_schema


class OpenAIProvider(LLMProvider):
    """OpenAI provider using GPT models."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """
        Initialize OpenAI provider.

        Args:
            api_key: OpenAI API key
            model: Model identifier
        """
        self.api_key = api_key or settings.openai_api_key
        self.model = model or settings.openai_model
        self.client = AsyncOpenAI(api_key=self.api_key)

    def _build_messages(self, prompt: str, system_prompt: Optional[str]) -> list:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        try:
            params: Dict[str, Any] = {
                "model": self.model,
                "messages": self._build_messages(prompt, system_prompt),
            }
            if temperature is not None:
                params["temperature"] = temperature
            if max_tokens is not None:
                params["max_tokens"] = max_tokens

            response = await self.client.chat.completions.create(**params)
            return response.choices[0].message.content or ""
        except OpenAIError as e:
            raise RuntimeError(f"OpenAI API error: {e}") from e

    async def stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        params: Dict[str, Any] = {
            "model": self.model,
            "messages": self._build_messages(prompt, system_prompt),
            "stream": True,
        }
        if temperature is not None:
            params["temperature"] = temperature
        if max_tokens is not None:
            params["max_tokens"] = max_tokens

        try:
            async with await self.client.chat.completions.create(**params) as stream:
                async for chunk in stream:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
        except OpenAIError as e:
            raise RuntimeError(f"OpenAI API error: {e}") from e

    async def generate_with_metadata(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        try:
            params: Dict[str, Any] = {
                "model": self.model,
                "messages": self._build_messages(prompt, system_prompt),
            }
            if temperature is not None:
                params["temperature"] = temperature
            if max_tokens is not None:
                params["max_tokens"] = max_tokens

            start = time.monotonic()
            response = await self.client.chat.completions.create(**params)
            latency_ms = (time.monotonic() - start) * 1000

            text = response.choices[0].message.content or ""
            usage = response.usage

            return {
                "response": text,
                "model": response.model,
                "provider": "openai",
                "usage": {
                    "prompt_tokens": usage.prompt_tokens if usage else 0,
                    "completion_tokens": usage.completion_tokens if usage else 0,
                    "total_tokens": usage.total_tokens if usage else 0,
                },
                "metadata": {
                    "latency_ms": latency_ms,
                    "finish_reason": response.choices[0].finish_reason,
                },
            }
        except OpenAIError as e:
            raise RuntimeError(f"OpenAI API error: {e}") from e

    async def generate_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Generate using OpenAI function calling (tools parameter)."""
        if not tools:
            return await super().generate_with_tools(messages, tools, system_prompt, **kwargs)

        openai_messages = []
        if system_prompt:
            openai_messages.append({"role": "system", "content": system_prompt})
        for m in messages:
            openai_messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})

        openai_tools = mcp_tools_to_openai_schema(tools)
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=openai_messages,
                tools=openai_tools,
                tool_choice="auto",
            )
        except OpenAIError as e:
            raise RuntimeError(f"OpenAI API error in generate_with_tools: {e}") from e

        choice = response.choices[0]
        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            tc = choice.message.tool_calls[0]
            encoded_name = tc.function.name
            server_id, tool_name = decode_tool_name(encoded_name)
            try:
                arguments = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            return {
                "stop_reason": "tool_use",
                "tool_use": {
                    "server_id": server_id,
                    "tool_name": tool_name,
                    "arguments": arguments,
                },
                "text": "",
            }

        return {"stop_reason": "end_turn", "text": choice.message.content or ""}
