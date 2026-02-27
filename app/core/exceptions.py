"""Custom exception classes for the orchestrator.

Each exception carries:
  error_code    — machine-readable code for client-side error handling
  message       — human-readable description
  details       — optional structured context (field names, provider names, etc.)
  recovery_hint — actionable guidance for the API caller (shown in error responses)
"""

from typing import Any, Dict, Optional


class OrchestratorError(Exception):
    """Base exception for orchestrator errors."""

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        recovery_hint: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code or "ORCHESTRATOR_ERROR"
        self.details = details or {}
        self.recovery_hint = recovery_hint or (
            "An unexpected error occurred. Please retry your request. "
            "If the problem persists, contact support with the request_id."
        )


class AgentError(OrchestratorError):
    """Exception raised by agent operations."""

    def __init__(
        self,
        message: str,
        agent_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        recovery_hint: Optional[str] = None,
    ):
        super().__init__(
            message,
            error_code="AGENT_ERROR",
            details=details,
            recovery_hint=recovery_hint or (
                f"The agent '{agent_id}' encountered an error. "
                "Check that the agent is enabled and the task is within its capabilities. "
                "Retry with a different agent_id or simplify the task."
            ),
        )
        self.agent_id = agent_id


class LLMProviderError(OrchestratorError):
    """Exception raised by LLM provider operations."""

    def __init__(
        self,
        message: str,
        provider: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        recovery_hint: Optional[str] = None,
    ):
        super().__init__(
            message,
            error_code="LLM_PROVIDER_ERROR",
            details=details,
            recovery_hint=recovery_hint or (
                f"The LLM provider '{provider}' is temporarily unavailable. "
                "Check your LLM_PROVIDER configuration and credentials. "
                "Retry in 30–60 seconds. If using AWS Bedrock, verify your AWS_REGION and IAM permissions."
            ),
        )
        self.provider = provider


class ValidationError(OrchestratorError):
    """Exception raised for validation errors."""

    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        recovery_hint: Optional[str] = None,
    ):
        super().__init__(
            message,
            error_code="VALIDATION_ERROR",
            details=details,
            recovery_hint=recovery_hint or (
                f"The value provided for '{field}' is invalid. "
                "Review the API documentation for accepted values and retry."
            ),
        )
        self.field = field


class ConfigurationError(OrchestratorError):
    """Exception raised for server configuration errors."""

    def __init__(
        self,
        message: str,
        config_key: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        recovery_hint: Optional[str] = None,
    ):
        super().__init__(
            message,
            error_code="CONFIGURATION_ERROR",
            details=details,
            recovery_hint=recovery_hint or (
                f"The server is misconfigured (key: '{config_key}'). "
                "Contact your system administrator to correct the server configuration."
            ),
        )
        self.config_key = config_key


class ServiceUnavailableError(OrchestratorError):
    """Exception raised when a required service is unavailable."""

    def __init__(
        self,
        message: str,
        service: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        recovery_hint: Optional[str] = None,
    ):
        super().__init__(
            message,
            error_code="SERVICE_UNAVAILABLE",
            details=details,
            recovery_hint=recovery_hint or (
                f"The '{service}' service is currently unavailable. "
                "Retry after 60 seconds. Check GET /api/v1/health for system status."
            ),
        )
        self.service = service
