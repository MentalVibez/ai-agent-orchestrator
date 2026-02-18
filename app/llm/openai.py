"""OpenAI LLM provider implementation."""

import time
from typing import Any, AsyncIterator, Dict, Optional

from openai import AsyncOpenAI, OpenAIError

from app.core.config import settings
from app.llm.base import LLMProvider


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
