# Quality Improvement Suggestions

Prioritized ideas to improve the project. Check off as you go.

---

## High impact

### 1. **CI: Lint and type check**
- Add **Ruff** (or Flake8) and **mypy** to the test workflow so every PR runs lint + type check.
- Optionally add **pre-commit** (`.pre-commit-config.yaml`) with ruff, mypy, and a doc/format check so contributors get fast feedback locally.

### 2. **CI: Dependency security**
- In GitHub Actions, run `pip install pip-audit` (or `safety`) and `pip-audit` (or `safety check`) so known vulnerable dependencies fail the build or are reported.

### 3. **Tests for new modules**
- **Unit:** `app/core/prompt_injection.py` – `sanitize_user_input`, `apply_prompt_injection_filter` (blocklist redaction, enabled/disabled).
- **Unit:** `app/core/run_store.py` – create_run, get_run_by_id, update_run (with an in-memory or test DB).
- **Unit:** `app/core/validation.py` – `validate_goal`, `validate_agent_profile_id`, `validate_run_context` (length, allowlist, edge cases).
- **Integration:** POST /run then GET /runs/:id until completed (or timeout), with a “no MCP” profile so no Node dependency.

### 4. **Planner / LLM timeouts**
- Wrap planner LLM calls in `asyncio.wait_for(..., timeout=...)` (e.g. 60–120s) so a stuck provider doesn’t hang the run forever. On timeout, mark the run as failed and store an error message.

### 5. **Run cancellation**
- Add **POST /api/v1/runs/{run_id}/cancel** that sets run status to `cancelled`. The planner loop can check the run status at the start of each step and exit if cancelled (requires passing run_id or a shared “cancelled” set into the loop).

---

## Medium impact

### 6. **Changelog**
- Add a **CHANGELOG.md** entry for the MCP work: runs API, Playwright/Fetch, console, security audit, file-tool workspace, run validation, anti–prompt-injection. Keeps the release history accurate.

### 7. **Health check and MCP**
- Extend **GET /api/v1/health** (or a separate readiness endpoint) to optionally report MCP status, e.g. `mcp_connected: true/false` or list of connected server IDs. Helps operators confirm MCP is up.

### 8. **Documentation**
- **CONTRIBUTING.md:** Add “Run tests” (e.g. `pytest tests/`), “Add an MCP server” (edit `config/mcp_servers.yaml`), “Add an agent profile” (edit `config/agent_profiles.yaml`). Link from README.
- **README:** Add a “Quality / development” line: link to CONTRIBUTING, test command, and optional lint/type commands.

### 9. **TODOs and tech debt**
- Turn **TODOs** in code (e.g. OpenAI/Ollama stubs, messaging, log_analysis/infrastructure agents) into GitHub issues with “TODO” label so they’re tracked; optionally remove or shorten the in-code TODO comments and point to the issue.

### 10. **Dependency reproducibility**
- Consider **pip-tools** (`pip-compile requirements.in`) or a **lock file** (e.g. `requirements.txt` with pinned versions for production) so installs are reproducible and security audits are consistent.

---

## Nice to have

### 11. **Structured logging**
- Use a single JSON or structured format (e.g. `structlog` or `logging` with a formatter that includes `run_id`, `agent_id`, `request_id`) so logs are easier to search and aggregate.

### 12. **Run list endpoint**
- **GET /api/v1/runs?limit=20&status=completed** – paginated list of runs for debugging and simple dashboards. Optional filters: `profile_id`, `since`.

### 13. **OpenAPI tags and examples**
- In FastAPI route docstrings or `response_model`, add **examples** for POST /run and GET /runs/:id so the generated OpenAPI is more useful for frontends and docs.

### 14. **Human-in-the-loop (HITL)**
- For sensitive MCP tools (e.g. delete, send, pay), allow runs to pause in `awaiting_approval` and add **POST /runs/{id}/approve** and **POST /runs/{id}/reject** so an operator can approve or reject the pending tool call. (Already noted in the MCP roadmap.)

---

## Summary

| Priority   | Suggestion              | Effort  | Done |
|-----------|--------------------------|--------|------|
| High      | CI: Ruff + mypy         | Low    | Yes  |
| High      | CI: pip-audit           | Low    | Yes  |
| High      | Tests for new modules   | Medium | Yes  |
| High      | Planner LLM timeouts    | Low    | Yes  |
| High      | Run cancellation        | Medium | Yes  |
| Medium    | Changelog entry         | Low    | Yes  |
| Medium    | Health + MCP status     | Low    | Yes  |
| Medium    | CONTRIBUTING + README   | Low    | Yes  |
| Medium    | TODO → issues           | Low    | Yes (docs/TODO_TRACKING.md) |
| Medium    | Dependency pinning      | Low    | —    |
| Nice      | Structured logging      | Medium | — (request_id already in middleware) |
| Nice      | GET /runs list          | Low    | Yes  |
| Nice      | OpenAPI examples        | Low    | Yes (RunRequest examples) |
| Nice      | HITL                    | Higher | Stub (approve/reject endpoints) |
