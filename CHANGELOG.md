# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **MCP (Model Context Protocol)**: Orchestrator as MCP client; register servers in `config/mcp_servers.yaml`, agent profiles in `config/agent_profiles.yaml`. Playwright and Fetch MCP servers enabled by default; Deep Research and Browser profiles.
- **Runs API**: `POST /api/v1/run` (goal + agent_profile_id), `GET /api/v1/runs/{run_id}`, `POST /api/v1/runs/{run_id}/cancel`, `GET /api/v1/agent-profiles`, `GET /api/v1/mcp/servers`. Planner loop with optional MCP tools or legacy orchestrator fallback.
- **Personal Multi-Agent Console**: `GET /console` serves a single-page UI to submit goals, pick profiles, and view run status and results.
- **Security**: File tools restricted to `AGENT_WORKSPACE_ROOT`; run request validation (goal length, context, profile allowlist); security audit (SECURITY_AUDIT.md); anti–prompt-injection (blocklist + structural hardening); planner LLM timeout and run cancellation.
- **Quality**: CI jobs for Ruff, mypy, pip-audit; unit tests for prompt_injection, run_store, run validation; integration tests for runs API; health response includes optional `mcp_connected`; QUALITY_SUGGESTIONS.md and TODO tracking.

### Changed
- Health response model includes optional `mcp_connected` field.
- Planner loop checks for cancelled run each step and supports configurable LLM timeout (`PLANNER_LLM_TIMEOUT_SECONDS`).

## [1.0.0] - 2025-01-27

### Added
- **Tool System**: Comprehensive tool framework for agents with file reading, code search, directory listing
- **Code Review Agent**: Security-focused code analysis agent with vulnerability detection
- **Dynamic Prompt Generation**: Context-aware prompt generation system for all agents
- Comprehensive testing suite with unit and integration tests
- LLM cost tracking and analytics system with cost breakdown by agent and endpoint
- Agent sandboxing for security isolation with resource limits
- Database persistence layer (SQLite) for execution history and agent state
- Workflow executor for multi-step, multi-agent workflows
- System Monitoring Agent implementation
- Prometheus metrics endpoint with comprehensive metrics
- GitHub Actions CI/CD workflow for automated testing
- Cost metrics API endpoints (`/api/v1/metrics/costs`)
- Workflow loading from YAML/JSON files
- Example workflow definitions
- Kubernetes deployment manifests and guides
- Community features (CONTRIBUTING.md, CODE_OF_CONDUCT.md, issue templates)

### Changed
- Enhanced orchestrator with execution history persistence
- Improved error handling with custom exception classes
- Updated requirements.txt with testing and database dependencies

### Security
- Added agent sandboxing with resource limits (CPU, memory, execution time)
- Implemented permission checks for agent operations
- Added audit logging for agent actions

## [0.1.0] - 2024-XX-XX

### Added
- Initial MVP release
- Network Diagnostics Agent
- Basic orchestrator with task routing
- API key authentication
- Rate limiting
- CORS support
- Security headers
- AWS Bedrock LLM provider integration
- Docker and Docker Compose support
- CloudFormation templates for AWS deployment

