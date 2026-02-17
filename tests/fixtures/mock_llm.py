"""Mock LLM provider for testing."""

from typing import Any, AsyncIterator, Dict, Optional

from app.llm.base import LLMProvider


class MockLLMProvider(LLMProvider):
    """Mock LLM provider for testing."""

    def __init__(self, responses: Optional[Dict[str, str]] = None):
        """
        Initialize mock LLM provider.

        Args:
            responses: Optional dict mapping prompts to responses
        """
        self.responses = responses or {}
        self.call_history = []
        self.default_response = "This is a mock LLM response."

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        """Generate a mock response."""
        self.call_history.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "temperature": temperature,
                "max_tokens": max_tokens,
                **kwargs,
            }
        )

        # Check if we have a specific response for this prompt
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        if full_prompt in self.responses:
            return self.responses[full_prompt]

        # Return default or prompt-based response
        return self.responses.get(prompt, self.default_response)

    async def stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream a mock response."""
        response = await self.generate(prompt, system_prompt, temperature, max_tokens, **kwargs)
        # Yield response in chunks
        words = response.split()
        for word in words:
            yield word + " "

    async def generate_with_metadata(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Generate a mock response with metadata."""
        text = await self.generate(prompt, system_prompt, temperature, max_tokens, **kwargs)

        # Estimate token usage (rough: 1 token ≈ 4 characters)
        input_tokens = len((system_prompt or "") + prompt) // 4
        output_tokens = len(text) // 4

        return {
            "text": text,
            "metadata": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "latency_seconds": 0.1,
                "model": "mock-model",
                "region": "us-east-1",
            },
        }

    def reset(self):
        """Reset call history."""
        self.call_history = []
