# Security Audit Report – AI Agent Orchestrator

**Date:** 2026-02  
**Scope:** Authentication, input validation, MCP/config, file tools, runs API, planner, dependencies, deployment.

---

## Executive Summary

The application has solid baseline security: API key auth, rate limiting, security headers, CORS, input validation on orchestrate/workflow endpoints, and YAML safe_load for config. **Critical and high-risk issues** center on: (1) **file tools allowing arbitrary path access** (no workspace root restriction), (2) **run API accepting unvalidated goal/context** (DoS and prompt injection surface), (3) **MCP config trust** (command/args from YAML and env), and (4) **no run-level authorization** (any valid API key can read any run). Recommended immediate actions: restrict file tools to a configurable workspace root, add run request validation (goal/context length and profile allowlist), and document MCP/config and run-authorization assumptions.

---

## 1. Critical Findings

### C1. File tools allow reads outside intended scope (path traversal)

**Location:** `app/core/tools.py` – `FileReadTool`, `CodeSearchTool`, `DirectoryListTool`, `FileMetadataTool`

**Issue:** Paths are resolved with `Path(file_path).resolve()` but there is **no check that the path lies under a designated workspace root**. An agent (or an attacker who influences the task/context) can request `file_path: "../../../etc/passwd"` or any path on the server. Extension and size checks limit impact but do not prevent reading sensitive files under allowed extensions (e.g. `.json`, `.yml` in `/etc` or env dirs).

**Recommendation:**

- Introduce a configurable **workspace root** (e.g. `AGENT_WORKSPACE_ROOT` or `TOOLS_WORKSPACE_ROOT`). Default to current working directory or a dedicated directory; do not default to `/`.
- For every file/directory tool: resolve the path and ensure `resolved_path.is_relative_to(workspace_root)` (or the equivalent `os.path.commonpath` check). Reject with `AgentError` if outside.
- Document that disabling or overriding this in production is unsafe.

**Status:** Recommended fix: add `app/core/config` setting and enforce in all four tools.

---

### C2. Run API accepts unvalidated goal and context (DoS / prompt injection)

**Location:** `app/api/v1/routes/runs.py` (POST /run), `app/models/run.py` – `RunRequest`

**Issue:** `goal` and `context` are not validated for length or structure. A client can send a multi-megabyte goal or deeply nested context, leading to:

- **DoS:** High memory/CPU and LLM token cost.
- **Prompt injection:** Goal and context are passed into the planner prompt; malicious content can try to steer the LLM or tool choices.
- **Storage bloat:** Large values are stored in the `runs` table.

**Recommendation:**

- Enforce **max length for goal** (e.g. 10_000–20_000 characters), and **max serialized size for context** (e.g. 50KB), consistent with existing `validate_context` in `app/core/validation.py`.
- Validate **agent_profile_id** against the set of enabled profile IDs from config; reject unknown profiles with 400.
- Reuse or mirror the existing context sanitization (control-character stripping, depth limit, list size limit) for run context.

**Status:** Recommended: add a small `validate_run_request()` and call it in the run route.

---

## 2. High Findings

### H1. MCP server command and env from config (arbitrary command execution if config is tampered)

**Location:** `app/mcp/client_manager.py`, `app/mcp/config_loader.py`

**Issue:** MCP servers are started via `command` and `args` (and optional `env`) read from `config/mcp_servers.yaml`. Anyone who can add or modify that file (or point `ORCHESTRATOR_CONFIG_DIR` to a writable location) can execute arbitrary commands (e.g. `command: "rm", args: ["-rf", "/"]` or `env: {"PATH": "..."}`).

**Recommendation:**

- Treat MCP config as **trusted only if the process and deployment restrict who can write to it**. Document that:
  - Config files and `ORCHESTRATOR_CONFIG_DIR` must be writable only by trusted deployers.
  - Do not load config from user-controllable or world-writable directories.
- Optionally: allowlist allowed `command` values (e.g. `npx`, `node`, `uv`, `python`) and reject unknown commands.

**Status:** Document in SECURITY.md and deployment docs; optional allowlist can be added later.

---

### H2. No run-level authorization (any key can read any run)

**Location:** `app/api/v1/routes/runs.py` – GET /runs/{run_id}

**Issue:** Any request with a valid API key can retrieve any run by `run_id`. There is no binding of runs to “users” or API keys. For single-tenant, single-key deployments this may be acceptable; for multi-tenant or multiple keys, this is **information disclosure** and violates least privilege.

**Recommendation:**

- **Short term:** Document that the current model is single-tenant / single-key; runs are not scoped per identity.
- **Medium term:** If you introduce multiple API keys or users, store a key_id or user_id on the run and enforce in GET /runs/{run_id} that the caller can only access their own runs.

**Status:** Document; implement when moving to multi-tenant or multiple keys.

---

### H3. Planner tool arguments come from LLM (SSRF / abuse via MCP tools)

**Location:** `app/planner/loop.py` – `call_tool(server_id, tool_name, arguments)` with `arguments` from parsed LLM output

**Issue:** Tool arguments are taken directly from the planner LLM output and passed to MCP servers (e.g. Fetch, Playwright). A compromised or prompted LLM could produce:

- **SSRF:** URLs to internal services (`http://169.254.169.254/`, `http://localhost:port`, file://).
- **Abuse:** Playwright navigating to phishing sites or performing unwanted actions.

**Recommendation:**

- Rely on **MCP servers** to validate and restrict inputs (e.g. Fetch blocking file:// and private IP ranges).
- **Document** that the orchestrator trusts planner output and that MCP servers should implement URL allowlists/blocklists and safe defaults.
- Optionally add an **orchestrator-level URL allowlist/blocklist** for known-dangerous schemes and hosts before calling fetch/playwright tools.

**Status:** Document; consider central URL/host policy if you add more HTTP/browser tools.

---

## 3. Medium Findings

### M1. Sandbox resource limits only on Unix

**Location:** `app/core/sandbox.py` – `resource.setrlimit(...)`

**Issue:** The `resource` module is Unix-only. On Windows, memory and CPU limits are not applied, so agent and tool execution are less constrained.

**Recommendation:** Document platform behavior; on Windows consider process-level limits or running agents in a container/VM if strong isolation is required.

---

### M2. Console page unauthenticated

**Location:** `app/main.py` – GET /console serves `examples/console.html`

**Issue:** The console is reachable by anyone who can reach the server. It does not expose data by itself (API calls require the API key), but it exposes the “run a goal” workflow and could be used to probe the API.

**Recommendation:** For production, consider putting /console behind the same API key (e.g. query param or cookie) or disabling the route when not needed.

---

### M3. Run context not sanitized like orchestrate context

**Location:** RunRequest.context is stored and passed to the planner without the same sanitization as `validate_context()` in the orchestrate route.

**Issue:** Orchestrate uses `validate_context()` (depth, size, control chars); run context does not. This increases DoS and prompt-injection surface for runs.

**Recommendation:** Reuse or mirror `validate_context()` for run request context (see C2).

---

## 4. Low / Informational

### L1. API key is single shared secret

**Location:** `app/core/auth.py`

**Issue:** One API key for all callers; no per-caller identity or revocation.

**Recommendation:** Acceptable for single-tenant; document. For multiple keys, introduce a key store and optional key_id for auditing.

---

### L2. Health endpoint unauthenticated

**Location:** `app/main.py` – GET /api/v1/health

**Issue:** Health does not require an API key. Typical for load balancers.

**Recommendation:** Keep as-is; document that health may reveal “degraded” status. Avoid returning internal details.

---

### L3. CORS_ORIGINS misconfiguration

**Issue:** If set to `*` or overly broad, cross-origin abuse is easier.

**Recommendation:** Document that CORS should list only trusted front-end origins; avoid `*` in production.

---

### L4. Dependencies

**Recommendation:** Run `pip audit` or `safety check` (and CI) regularly; fix known vulnerabilities in dependencies.

---

## 5. Positive Findings

- **API key authentication** on all sensitive endpoints; can be disabled only explicitly.
- **Rate limiting** per IP on all endpoints (configurable).
- **Security headers** (CSP, X-Frame-Options, etc.) in place.
- **CORS** restricted to configured origins.
- **Orchestrate/workflow input validation:** task length, context size/depth/sanitization, agent_ids and workflow_id validated and sanitized.
- **YAML config:** `yaml.safe_load` used; no arbitrary class loading.
- **Secrets:** From environment; .env in .gitignore.
- **File tools:** Extension allowlist and file size limit reduce impact of path issues; adding workspace root would address the main gap.

---

## 6. Recommended Action Order

1. **Immediate:** Add workspace root for file tools and enforce it in all four tools (C1). ✅ Done.
2. **Immediate:** Add run request validation: goal max length, context max size and sanitization, agent_profile_id allowlist (C2, M3). ✅ Done.
3. **Immediate:** Add anti–prompt-injection: structural hardening (delimiters + instruction) and optional blocklist filter on user goal. ✅ Done (`app/core/prompt_injection.py`, planner prompt, `PROMPT_INJECTION_FILTER_ENABLED`).
4. **Short term:** Update SECURITY.md with MCP config trust, run authorization model, and planner/MCP trust (H1, H2, H3). ✅ Done.
5. **Short term:** Document sandbox platform behavior and console exposure (M1, M2).
6. **Ongoing:** Dependency scanning (L4); consider run-level authorization when moving to multi-tenant (H2).

---

## 7. References

- Existing: `SECURITY.md`, `app/core/validation.py`, `app/core/auth.py`
- OWASP API Security Top 10, CWE-22 (Path Traversal), CWE-400 (DoS)
