"""Abstract base class for LLM providers."""

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, List, Optional


class LLMProvider(ABC):
    """Abstract interface for LLM providers."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        """
        Generate a text response from the LLM.

        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional provider-specific parameters

        Returns:
            Generated text response
        """
        raise NotImplementedError("generate method must be implemented")

    @abstractmethod
    async def stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """
        Stream a text response from the LLM.

        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional provider-specific parameters

        Yields:
            Text chunks as they are generated
        """
        raise NotImplementedError("stream method must be implemented")

    @abstractmethod
    async def generate_with_metadata(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Generate a response with metadata (tokens used, latency, etc.).

        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional provider-specific parameters

        Returns:
            Dictionary containing response and metadata
        """
        raise NotImplementedError("generate_with_metadata method must be implemented")

    async def generate_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Generate a response using native tool calling (when supported).
        Default implementation falls back to text generation.

        Args:
            messages: Conversation history [{"role": "user"|"assistant", "content": "..."}]
            tools: MCP tool definitions [{"server_id", "name", "description", "inputSchema"}]
            system_prompt: Optional system prompt
            **kwargs: Additional provider-specific parameters

        Returns:
            Dict with keys:
              - stop_reason: "tool_use" | "end_turn" | "text"
              - tool_use (when stop_reason=="tool_use"):
                  {"server_id": str, "tool_name": str, "arguments": dict}
              - text (when stop_reason in ["end_turn", "text"]): str
        """
        # Default: text-based fallback (Ollama and unknown providers)
        prompt = messages[-1].get("content", "") if messages else ""
        text = await self.generate(prompt, system_prompt=system_prompt, **kwargs)
        return {"stop_reason": "text", "text": text}
