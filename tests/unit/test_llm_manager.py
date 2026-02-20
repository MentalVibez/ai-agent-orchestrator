"""Unit tests for app/llm/manager.py — LLMManager."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestLLMManagerInitializeProvider:
    """Tests for LLMManager.initialize_provider()."""

    def test_initialize_provider_bedrock(self):
        """Initializes BedrockProvider and sets it as current."""
        mock_provider = MagicMock()
        with patch("app.llm.manager.BedrockProvider", return_value=mock_provider) as MockBedrock:
            from app.llm.manager import LLMManager
            mgr = LLMManager()
            result = mgr.initialize_provider("bedrock")
        MockBedrock.assert_called_once_with()
        assert result is mock_provider
        assert mgr.get_current_provider() is mock_provider

    def test_initialize_provider_openai(self):
        """Initializes OpenAIProvider and sets it as current."""
        mock_provider = MagicMock()
        with patch("app.llm.manager.OpenAIProvider", return_value=mock_provider) as MockOpenAI:
            from app.llm.manager import LLMManager
            mgr = LLMManager()
            result = mgr.initialize_provider("openai")
        MockOpenAI.assert_called_once_with()
        assert result is mock_provider
        assert mgr.get_current_provider() is mock_provider

    def test_initialize_provider_ollama(self):
        """Initializes OllamaProvider and sets it as current."""
        mock_provider = MagicMock()
        with patch("app.llm.manager.OllamaProvider", return_value=mock_provider) as MockOllama:
            from app.llm.manager import LLMManager
            mgr = LLMManager()
            result = mgr.initialize_provider("ollama")
        MockOllama.assert_called_once_with()
        assert result is mock_provider

    def test_initialize_provider_unknown_raises_value_error(self):
        """Raises ValueError for an unknown provider name."""
        from app.llm.manager import LLMManager
        mgr = LLMManager()
        with pytest.raises(ValueError, match="Unknown LLM provider: xyz"):
            mgr.initialize_provider("xyz")

    def test_initialize_provider_uses_settings_default(self):
        """When no provider_name given, falls back to settings.llm_provider."""
        mock_provider = MagicMock()
        with patch("app.llm.manager.settings") as mock_settings:
            mock_settings.llm_provider = "ollama"
            with patch("app.llm.manager.OllamaProvider", return_value=mock_provider):
                from app.llm.manager import LLMManager
                mgr = LLMManager()
                result = mgr.initialize_provider()
        assert result is mock_provider

    def test_initialize_provider_stores_in_providers_dict(self):
        """Provider is stored keyed by name for later retrieval."""
        mock_provider = MagicMock()
        with patch("app.llm.manager.OpenAIProvider", return_value=mock_provider):
            from app.llm.manager import LLMManager
            mgr = LLMManager()
            mgr.initialize_provider("openai")
        assert mgr._providers["openai"] is mock_provider


@pytest.mark.unit
class TestLLMManagerGetProvider:
    """Tests for LLMManager.get_provider()."""

    def test_get_provider_by_name_initializes_if_not_cached(self):
        """Calls initialize_provider when the named provider is not in cache."""
        mock_provider = MagicMock()
        with patch("app.llm.manager.OpenAIProvider", return_value=mock_provider):
            from app.llm.manager import LLMManager
            mgr = LLMManager()
            result = mgr.get_provider("openai")
        assert result is mock_provider

    def test_get_provider_by_name_returns_cached(self):
        """Returns cached provider without re-initializing."""
        mock_provider = MagicMock()
        with patch("app.llm.manager.OpenAIProvider", return_value=mock_provider):
            from app.llm.manager import LLMManager
            mgr = LLMManager()
            first = mgr.get_provider("openai")
            second = mgr.get_provider("openai")
        assert first is second is mock_provider

    def test_get_provider_no_name_initializes_if_no_current(self):
        """Calls initialize_provider() when no current provider is set."""
        mock_provider = MagicMock()
        with patch("app.llm.manager.settings") as mock_settings:
            mock_settings.llm_provider = "openai"
            with patch("app.llm.manager.OpenAIProvider", return_value=mock_provider):
                from app.llm.manager import LLMManager
                mgr = LLMManager()
                result = mgr.get_provider()
        assert result is mock_provider

    def test_get_provider_no_name_returns_current(self):
        """Returns existing _current_provider when already set."""
        from app.llm.manager import LLMManager
        mgr = LLMManager()
        fake = MagicMock()
        mgr._current_provider = fake
        assert mgr.get_provider() is fake


@pytest.mark.unit
class TestLLMManagerSetProvider:
    """Tests for LLMManager.set_provider() and get_current_provider()."""

    def test_get_current_provider_returns_none_initially(self):
        """A fresh LLMManager has no current provider."""
        from app.llm.manager import LLMManager
        mgr = LLMManager()
        assert mgr.get_current_provider() is None

    def test_set_provider_switches_current(self):
        """set_provider() changes the active provider."""
        mock_openai = MagicMock()
        mock_bedrock = MagicMock()
        with patch("app.llm.manager.OpenAIProvider", return_value=mock_openai):
            with patch("app.llm.manager.BedrockProvider", return_value=mock_bedrock):
                from app.llm.manager import LLMManager
                mgr = LLMManager()
                mgr.initialize_provider("openai")
                mgr.initialize_provider("bedrock")
                assert mgr.get_current_provider() is mock_bedrock
                mgr.set_provider("openai")
                assert mgr.get_current_provider() is mock_openai
