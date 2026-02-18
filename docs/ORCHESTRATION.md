# Orchestration: Legacy vs MCP Runs

This document clarifies the two orchestration paths and when each is used.

## When to use which

| Use case | Endpoint | Behavior |
|----------|----------|----------|
| **Goal-based, tool-choosing flows** | `POST /api/v1/run` | LLM plans steps and chooses MCP tools (or legacy agents) until it finishes. Use for open-ended goals like "Check connectivity to example.com and summarize." |
| **Direct task-to-agent dispatch** | `POST /api/v1/orchestrate` | Task is routed to one or more agents by keyword (or by LLM if `USE_LLM_ROUTING=true`). Use when you know the task type and optionally want to pin `agent_ids`. |

- **`POST /run`** — Goal + `agent_profile_id`. The planner loop runs; the LLM decides which tools to call or, if no MCP tools are available, the run falls back to the legacy orchestrator (see below).
- **`POST /orchestrate`** — Task + optional `context` and optional `agent_ids`. If `agent_ids` is provided, those agents are run (sequentially or in parallel with `parallel=True` in code). If not, the orchestrator selects an agent by keyword (or by LLM when `USE_LLM_ROUTING=true`).

## When does the planner fall back to legacy agents?

For `POST /api/v1/run`, the planner uses **MCP tools** only when the chosen agent profile has at least one **allowed MCP server** and that server is connected. Otherwise it **falls back to the legacy orchestrator**:

- The **default** profile has `allowed_mcp_servers: []` in `config/agent_profiles.yaml`, so with no config change, **all runs use the legacy orchestrator** (keyword-based task routing, single agent execution).
- When you add MCP server IDs to a profile’s `allowed_mcp_servers` and those servers are enabled in `config/mcp_servers.yaml`, the planner will use those MCP tools for that profile.
- If the profile lists MCP servers but none are connected at startup, the planner still falls back to the legacy orchestrator for that run.

So: **no MCP tools for the profile ⇒ legacy orchestrator** (one-shot route + execute).

## What does `agent_profile_id` control?

`agent_profile_id` (e.g. `default`, `browser`, `deep_research`) selects:

1. **Role prompt** — The system prompt that tells the LLM how to plan (e.g. "output one JSON action: tool_call or finish").
2. **Allowed MCP servers** — The set of MCP servers whose tools the LLM is allowed to call. Empty list ⇒ no MCP tools ⇒ legacy orchestrator.
3. **Model override** (optional) — Profile can specify a different LLM model; `null` means use the app default.

It does **not** select a specific legacy agent by ID. Legacy agents (network_diagnostics, system_monitoring, etc.) are chosen internally by the orchestrator from the task text when the run is in legacy mode.
