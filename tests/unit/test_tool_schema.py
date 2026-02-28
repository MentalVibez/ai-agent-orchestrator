"""Unit tests for app/llm/tool_schema.py — MCP tool schema conversion utilities."""

import pytest

from app.llm.tool_schema import (
    _safe_tool_name,
    decode_tool_name,
    mcp_tools_to_bedrock_schema,
    mcp_tools_to_openai_schema,
)


class TestSafeToolName:
    def test_simple_alphanumeric(self):
        result = _safe_tool_name("server1", "ping")
        assert result == "server1__ping"

    def test_special_chars_replaced_with_underscore(self):
        result = _safe_tool_name("my-server", "my.tool")
        assert "-" not in result
        assert "." not in result
        assert "__" in result

    def test_name_starting_with_digit_prefixed_with_t(self):
        # server_id starts with digit → combined starts with digit → prefix added
        result = _safe_tool_name("1server", "tool")
        assert result[0].isalpha()
        assert result.startswith("t_")

    def test_name_starting_with_underscore_prefixed(self):
        result = _safe_tool_name("_bad", "tool")
        assert result[0].isalpha()
        assert result.startswith("t_")

    def test_truncated_to_64_chars(self):
        result = _safe_tool_name("a" * 40, "b" * 40)
        assert len(result) <= 64

    def test_normal_name_not_prefixed(self):
        result = _safe_tool_name("srv", "get_data")
        assert result.startswith("srv")
        assert not result.startswith("t_")

    def test_hyphen_in_server_id_replaced(self):
        result = _safe_tool_name("my-server", "tool")
        assert "my_server__tool" in result


class TestDecodeToolName:
    def test_encoded_with_separator_decoded(self):
        server_id, tool_name = decode_tool_name("server1__ping")
        assert server_id == "server1"
        assert tool_name == "ping"

    def test_no_separator_returns_empty_server_and_full_name(self):
        server_id, tool_name = decode_tool_name("noseparator")
        assert server_id == ""
        assert tool_name == "noseparator"

    def test_multiple_separators_splits_on_first(self):
        server_id, tool_name = decode_tool_name("srv__tool__extra")
        assert server_id == "srv"
        assert tool_name == "tool__extra"

    def test_leading_separator(self):
        server_id, tool_name = decode_tool_name("__tool")
        assert server_id == ""
        assert tool_name == "tool"

    def test_roundtrip_safe_name_to_decode(self):
        original_server = "my-server"
        original_tool = "get.data"
        encoded = _safe_tool_name(original_server, original_tool)
        # decode recovers the encoded parts (not original, since special chars are replaced)
        server_id, tool_name = decode_tool_name(encoded)
        assert server_id  # non-empty
        assert tool_name  # non-empty


class TestMcpToolsToBedrockSchema:
    def test_empty_list_returns_empty(self):
        result = mcp_tools_to_bedrock_schema([])
        assert result == []

    def test_basic_tool_converted(self):
        tools = [
            {
                "server_id": "srv",
                "name": "ping",
                "description": "Ping a host",
                "inputSchema": {"type": "object", "properties": {"host": {"type": "string"}}},
            }
        ]
        result = mcp_tools_to_bedrock_schema(tools)
        assert len(result) == 1
        spec = result[0]["toolSpec"]
        assert "ping" in spec["name"]
        assert spec["description"] == "Ping a host"
        assert "host" in spec["inputSchema"]["json"]["properties"]

    def test_missing_input_schema_defaults_to_empty_object(self):
        tools = [{"server_id": "s", "name": "t", "description": "desc"}]
        result = mcp_tools_to_bedrock_schema(tools)
        assert result[0]["toolSpec"]["inputSchema"]["json"] == {
            "type": "object",
            "properties": {},
        }

    def test_none_input_schema_defaults_to_empty_object(self):
        tools = [{"server_id": "s", "name": "t", "description": "desc", "inputSchema": None}]
        result = mcp_tools_to_bedrock_schema(tools)
        assert result[0]["toolSpec"]["inputSchema"]["json"] == {
            "type": "object",
            "properties": {},
        }

    def test_description_truncated_to_512_chars(self):
        long_desc = "x" * 600
        tools = [{"server_id": "s", "name": "t", "description": long_desc}]
        result = mcp_tools_to_bedrock_schema(tools)
        assert len(result[0]["toolSpec"]["description"]) <= 512

    def test_missing_description_uses_empty_string(self):
        tools = [{"server_id": "s", "name": "t"}]
        result = mcp_tools_to_bedrock_schema(tools)
        assert result[0]["toolSpec"]["description"] == ""

    def test_multiple_tools_all_converted(self):
        tools = [
            {"server_id": "s1", "name": "ping", "description": "Ping"},
            {"server_id": "s2", "name": "dns", "description": "DNS lookup"},
        ]
        result = mcp_tools_to_bedrock_schema(tools)
        assert len(result) == 2
        names = [r["toolSpec"]["name"] for r in result]
        assert any("ping" in n for n in names)
        assert any("dns" in n for n in names)

    def test_tool_spec_structure(self):
        tools = [{"server_id": "srv", "name": "tool", "description": "A tool"}]
        result = mcp_tools_to_bedrock_schema(tools)
        spec = result[0]
        assert "toolSpec" in spec
        assert "name" in spec["toolSpec"]
        assert "description" in spec["toolSpec"]
        assert "inputSchema" in spec["toolSpec"]
        assert "json" in spec["toolSpec"]["inputSchema"]


class TestMcpToolsToOpenAISchema:
    def test_empty_list_returns_empty(self):
        result = mcp_tools_to_openai_schema([])
        assert result == []

    def test_basic_tool_converted(self):
        tools = [
            {
                "server_id": "srv",
                "name": "ping",
                "description": "Ping a host",
                "inputSchema": {
                    "type": "object",
                    "properties": {"host": {"type": "string"}},
                },
            }
        ]
        result = mcp_tools_to_openai_schema(tools)
        assert len(result) == 1
        func = result[0]["function"]
        assert "ping" in func["name"]
        assert func["description"] == "Ping a host"
        assert func["parameters"]["properties"]["host"]["type"] == "string"

    def test_type_is_function(self):
        tools = [{"server_id": "s", "name": "t", "description": "D"}]
        result = mcp_tools_to_openai_schema(tools)
        assert result[0]["type"] == "function"

    def test_missing_description_uses_empty_string(self):
        tools = [{"server_id": "s", "name": "t"}]
        result = mcp_tools_to_openai_schema(tools)
        assert result[0]["function"]["description"] == ""

    def test_missing_input_schema_defaults_to_empty_object(self):
        tools = [{"server_id": "s", "name": "t", "description": "desc"}]
        result = mcp_tools_to_openai_schema(tools)
        assert result[0]["function"]["parameters"] == {"type": "object", "properties": {}}

    def test_none_input_schema_defaults_to_empty_object(self):
        tools = [{"server_id": "s", "name": "t", "description": "d", "inputSchema": None}]
        result = mcp_tools_to_openai_schema(tools)
        assert result[0]["function"]["parameters"] == {"type": "object", "properties": {}}

    def test_description_truncated_to_512_chars(self):
        tools = [{"server_id": "s", "name": "t", "description": "x" * 600}]
        result = mcp_tools_to_openai_schema(tools)
        assert len(result[0]["function"]["description"]) <= 512

    def test_multiple_tools_all_converted(self):
        tools = [
            {"server_id": "s1", "name": "ping", "description": "Ping"},
            {"server_id": "s2", "name": "get_info", "description": "Get info"},
        ]
        result = mcp_tools_to_openai_schema(tools)
        assert len(result) == 2

    def test_function_structure_keys(self):
        tools = [{"server_id": "srv", "name": "t", "description": "desc"}]
        result = mcp_tools_to_openai_schema(tools)
        func = result[0]["function"]
        assert "name" in func
        assert "description" in func
        assert "parameters" in func
