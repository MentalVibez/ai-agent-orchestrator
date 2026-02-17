"""Custom exception classes for the orchestrator."""

from typing import Any, Dict, Optional


class OrchestratorError(Exception):
    """Base exception for orchestrator errors."""

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize orchestrator error.

        Args:
            message: Error message
            error_code: Optional error code
            details: Optional error details
        """
        super().__init__(message)
        self.message = message
        self.error_code = error_code or "ORCHESTRATOR_ERROR"
        self.details = details or {}


class AgentError(OrchestratorError):
    """Exception raised by agent operations."""

    def __init__(
        self, message: str, agent_id: Optional[str] = None, details: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize agent error.

        Args:
            message: Error message
            agent_id: Agent identifier
            details: Optional error details
        """
        super().__init__(message, error_code="AGENT_ERROR", details=details)
        self.agent_id = agent_id


class LLMProviderError(OrchestratorError):
    """Exception raised by LLM provider operations."""

    def __init__(
        self, message: str, provider: Optional[str] = None, details: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize LLM provider error.

        Args:
            message: Error message
            provider: LLM provider name
            details: Optional error details
        """
        super().__init__(message, error_code="LLM_PROVIDER_ERROR", details=details)
        self.provider = provider


class ValidationError(OrchestratorError):
    """Exception raised for validation errors."""

    def __init__(
        self, message: str, field: Optional[str] = None, details: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize validation error.

        Args:
            message: Error message
            field: Field that failed validation
            details: Optional error details
        """
        super().__init__(message, error_code="VALIDATION_ERROR", details=details)
        self.field = field


class ConfigurationError(OrchestratorError):
    """Exception raised for configuration errors."""

    def __init__(
        self,
        message: str,
        config_key: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize configuration error.

        Args:
            message: Error message
            config_key: Configuration key that caused error
            details: Optional error details
        """
        super().__init__(message, error_code="CONFIGURATION_ERROR", details=details)
        self.config_key = config_key


class ServiceUnavailableError(OrchestratorError):
    """Exception raised when a service is unavailable."""

    def __init__(
        self, message: str, service: Optional[str] = None, details: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize service unavailable error.

        Args:
            message: Error message
            service: Service name
            details: Optional error details
        """
        super().__init__(message, error_code="SERVICE_UNAVAILABLE", details=details)
        self.service = service
