"""Utilities to convert MCP tool definitions to provider-specific schemas."""

import re
from typing import Any, Dict, List


def _safe_tool_name(server_id: str, tool_name: str) -> str:
    """Encode server_id and tool_name into a valid LLM tool name (alphanumeric + underscore)."""
    combined = f"{server_id}__{tool_name}"
    # Replace any non-alphanumeric characters (except underscore) with underscore
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", combined)
    # Ensure it starts with a letter
    if safe and not safe[0].isalpha():
        safe = "t_" + safe
    return safe[:64]  # Most providers cap at 64 chars


def decode_tool_name(encoded: str) -> tuple:
    """
    Decode an encoded tool name back to (server_id, tool_name).
    Returns ('', encoded) if separator not found.
    """
    if "__" in encoded:
        parts = encoded.split("__", 1)
        return parts[0], parts[1]
    return "", encoded


def mcp_tools_to_bedrock_schema(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Convert MCP tool list to Bedrock Converse API toolConfig.tools format.
    Each MCP tool has: server_id, name, description, inputSchema.
    """
    bedrock_tools = []
    for t in tools:
        server_id = t.get("server_id", "")
        tool_name = t.get("name", "")
        encoded_name = _safe_tool_name(server_id, tool_name)
        schema = t.get("inputSchema") or {"type": "object", "properties": {}}
        bedrock_tools.append(
            {
                "toolSpec": {
                    "name": encoded_name,
                    "description": (t.get("description") or "")[:512],
                    "inputSchema": {"json": schema},
                }
            }
        )
    return bedrock_tools


def mcp_tools_to_openai_schema(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Convert MCP tool list to OpenAI chat.completions tools format.
    Each MCP tool has: server_id, name, description, inputSchema.
    """
    openai_tools = []
    for t in tools:
        server_id = t.get("server_id", "")
        tool_name = t.get("name", "")
        encoded_name = _safe_tool_name(server_id, tool_name)
        schema = t.get("inputSchema") or {"type": "object", "properties": {}}
        openai_tools.append(
            {
                "type": "function",
                "function": {
                    "name": encoded_name,
                    "description": (t.get("description") or "")[:512],
                    "parameters": schema,
                },
            }
        )
    return openai_tools
