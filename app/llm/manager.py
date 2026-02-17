"""LLM provider manager for selecting and initializing providers."""

from typing import Any, Dict, Optional

from app.core.config import settings
from app.llm.base import LLMProvider
from app.llm.bedrock import BedrockProvider
from app.llm.ollama import OllamaProvider
from app.llm.openai import OpenAIProvider


class LLMManager:
    """Manages LLM provider selection and initialization."""

    def __init__(self):
        """Initialize the LLM manager."""
        self._providers: Dict[str, LLMProvider] = {}
        self._current_provider: Optional[LLMProvider] = None

    def initialize_provider(
        self, provider_name: Optional[str] = None, **kwargs: Any
    ) -> LLMProvider:
        """
        Initialize and set the current LLM provider.

        Args:
            provider_name: Name of the provider (bedrock, openai, ollama)
            **kwargs: Provider-specific initialization parameters

        Returns:
            Initialized LLM provider instance
        """
        provider_name = provider_name or settings.llm_provider

        if provider_name == "bedrock":
            provider = BedrockProvider(**kwargs)
        elif provider_name == "openai":
            provider = OpenAIProvider(**kwargs)
        elif provider_name == "ollama":
            provider = OllamaProvider(**kwargs)
        else:
            raise ValueError(f"Unknown LLM provider: {provider_name}")

        self._providers[provider_name] = provider
        self._current_provider = provider
        return provider

    def get_provider(self, provider_name: Optional[str] = None) -> LLMProvider:
        """
        Get a provider instance, initializing if necessary.

        Args:
            provider_name: Name of the provider (optional, uses current if not specified)

        Returns:
            LLM provider instance
        """
        if provider_name:
            if provider_name not in self._providers:
                return self.initialize_provider(provider_name)
            return self._providers[provider_name]

        if not self._current_provider:
            return self.initialize_provider()

        return self._current_provider

    def set_provider(self, provider_name: str) -> None:
        """
        Switch to a different provider.

        Args:
            provider_name: Name of the provider to switch to
        """
        self._current_provider = self.get_provider(provider_name)

    def get_current_provider(self) -> Optional[LLMProvider]:
        """
        Get the current active provider.

        Returns:
            Current LLM provider instance or None
        """
        return self._current_provider
