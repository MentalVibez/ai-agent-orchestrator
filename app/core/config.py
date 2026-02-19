"""Application configuration management using Pydantic Settings."""

from typing import List

from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application Settings
    app_name: str = Field(default="AI Agent Orchestrator", alias="APP_NAME")
    app_version: str = Field(default="1.0.0", alias="APP_VERSION")
    debug: bool = Field(default=False, alias="DEBUG")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # CORS Settings
    cors_origins: str = Field(
        default="https://yourdomain.com,http://localhost:3000,http://localhost:8000",
        alias="CORS_ORIGINS",
    )

    # LLM Provider Settings
    llm_provider: str = Field(default="bedrock", alias="LLM_PROVIDER")
    llm_model: str = Field(default="anthropic.claude-3-haiku-20240307-v1:0", alias="LLM_MODEL")
    llm_temperature: float = Field(default=0.7, alias="LLM_TEMPERATURE")
    llm_max_tokens: int = Field(default=4096, alias="LLM_MAX_TOKENS")

    # AWS Bedrock Configuration
    aws_region: str = Field(default="us-east-1", alias="AWS_REGION")
    aws_access_key_id: str = Field(default="", alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str = Field(default="", alias="AWS_SECRET_ACCESS_KEY")

    # OpenAI Configuration
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-3.5-turbo", alias="OPENAI_MODEL")

    # Ollama Configuration
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="llama2", alias="OLLAMA_MODEL")

    # Server Settings
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")

    # Security Settings
    api_key: str = Field(default="", alias="API_KEY")
    rate_limit_per_minute: int = Field(default=60, alias="RATE_LIMIT_PER_MINUTE")
    require_api_key: bool = Field(default=True, alias="REQUIRE_API_KEY")
    # Webhook secret for HMAC-SHA256 validation of Prometheus Alertmanager payloads.
    # Set to a strong random string (e.g. openssl rand -hex 32). Empty = webhook auth disabled.
    webhook_secret: str = Field(default="", alias="WEBHOOK_SECRET")
    # Restrict file tools (read, list, search, metadata) to paths under this directory. Empty = use process cwd.
    agent_workspace_root: str = Field(default="", alias="AGENT_WORKSPACE_ROOT")
    # Best-effort prompt injection filter: redact blocklist phrases in user goal/context. Set false to disable.
    prompt_injection_filter_enabled: bool = Field(
        default=True, alias="PROMPT_INJECTION_FILTER_ENABLED"
    )
    # Planner: timeout per LLM call (seconds). 0 = no timeout.
    planner_llm_timeout_seconds: int = Field(default=120, alias="PLANNER_LLM_TIMEOUT_SECONDS")
    # Maximum concurrent webhook-triggered runs before returning HTTP 429.
    webhook_max_concurrent_runs: int = Field(default=5, alias="WEBHOOK_MAX_CONCURRENT_RUNS")
    # Webhook alert deduplication window in seconds.
    webhook_dedup_ttl_seconds: int = Field(default=300, alias="WEBHOOK_DEDUP_TTL_SECONDS")
    # Use LLM to route POST /orchestrate tasks to an agent (when True). Fallback to keyword routing on failure.
    use_llm_routing: bool = Field(default=False, alias="USE_LLM_ROUTING")
    # Timeout in seconds for LLM routing call. 0 = use default (10).
    llm_routing_timeout_seconds: int = Field(default=10, alias="LLM_ROUTING_TIMEOUT_SECONDS")
    # Optional job queue for runs (e.g. redis://localhost:6379). Empty = run planner in-process.
    run_queue_url: str = Field(default="", alias="RUN_QUEUE_URL")
    # Optional OpenTelemetry tracing. When True, trace runs and planner steps/tool calls (OTLP or console).
    otel_enabled: bool = Field(default=False, alias="OTEL_ENABLED")
    # OTLP endpoint for traces (e.g. http://localhost:4318/v1/traces). Empty = use SDK default.
    otel_exporter_otlp_endpoint: str = Field(default="", alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    # Optional: ChromaDB persistence directory. Empty = in-memory (data lost on restart).
    # Set to a path like /app/data/chroma to persist RAG documents across restarts.
    chroma_persist_directory: str = Field(default="", alias="CHROMA_PERSIST_DIRECTORY")

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins string into a list."""
        return [origin.strip() for origin in self.cors_origins.split(",")]

    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)


# Global settings instance
settings = Settings()
