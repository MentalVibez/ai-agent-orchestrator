"""Comprehensive unit tests for app/core/validation.py.

Covers validate_task, validate_context, _validate_nested,
validate_agent_ids, validate_goal, validate_agent_profile_id,
validate_workflow_id, and validate_run_context.
"""

from unittest.mock import patch

import pytest

from app.core.exceptions import ValidationError
from app.core.validation import (
    MAX_AGENT_IDS,
    MAX_CONTEXT_SIZE,
    MAX_GOAL_LENGTH,
    MAX_TASK_LENGTH,
    _validate_nested,
    validate_agent_ids,
    validate_agent_profile_id,
    validate_context,
    validate_goal,
    validate_run_context,
    validate_task,
    validate_workflow_id,
)

# ---------------------------------------------------------------------------
# validate_task
# ---------------------------------------------------------------------------


class TestValidateTask:
    def test_none_raises(self):
        with pytest.raises(ValidationError) as exc:
            validate_task(None)
        assert exc.value.field == "task"

    def test_empty_string_raises(self):
        with pytest.raises(ValidationError) as exc:
            validate_task("")
        assert exc.value.field == "task"

    def test_whitespace_only_raises(self):
        with pytest.raises(ValidationError) as exc:
            validate_task("   ")
        assert exc.value.field == "task"

    def test_non_string_raises(self):
        with pytest.raises(ValidationError) as exc:
            validate_task(42)
        assert exc.value.field == "task"

    def test_too_long_raises(self):
        with pytest.raises(ValidationError) as exc:
            validate_task("x" * (MAX_TASK_LENGTH + 1))
        assert exc.value.field == "task"

    def test_valid_task_returned(self):
        result = validate_task("Fix the broken service")
        assert result == "Fix the broken service"

    def test_strips_whitespace(self):
        result = validate_task("  Restart nginx  ")
        assert result == "Restart nginx"

    def test_control_chars_removed(self):
        result = validate_task("Diagnose\x00host\x07issues\x1f")
        assert "\x00" not in result
        assert "\x07" not in result
        assert "\x1f" not in result
        # Printable content is preserved
        assert "Diagnose" in result
        assert "issues" in result

    def test_newline_and_tab_preserved(self):
        # \n (0x0A) and \t (0x09) are NOT in the stripped range
        result = validate_task("Line1\nLine2\tTabbed")
        assert "\n" in result
        assert "\t" in result

    def test_exactly_max_length_allowed(self):
        result = validate_task("a" * MAX_TASK_LENGTH)
        assert len(result) == MAX_TASK_LENGTH


# ---------------------------------------------------------------------------
# validate_context
# ---------------------------------------------------------------------------


class TestValidateContext:
    def test_none_returns_empty_dict(self):
        assert validate_context(None) == {}

    def test_non_dict_raises(self):
        with pytest.raises(ValidationError) as exc:
            validate_context("not a dict")
        assert exc.value.field == "context"

    def test_valid_flat_dict_returned(self):
        data = {"host": "server-1", "port": 22}
        result = validate_context(data)
        assert result["host"] == "server-1"
        assert result["port"] == 22

    def test_oversized_context_raises(self):
        # Build a context whose str() representation exceeds MAX_CONTEXT_SIZE
        big_value = "x" * (MAX_CONTEXT_SIZE + 1)
        with pytest.raises(ValidationError) as exc:
            validate_context({"k": big_value})
        assert exc.value.field == "context"

    def test_non_string_key_raises(self):
        with pytest.raises(ValidationError) as exc:
            validate_context({42: "value"})  # type: ignore[arg-type]
        assert exc.value.field == "context"

    def test_string_value_too_long_raises(self):
        with pytest.raises(ValidationError) as exc:
            validate_context({"key": "x" * 10001})
        assert exc.value.field == "context"

    def test_control_chars_in_value_removed(self):
        result = validate_context({"msg": "hello\x00world"})
        assert "\x00" not in result["msg"]
        assert "hello" in result["msg"]

    def test_key_with_special_chars_sanitized(self):
        result = validate_context({"my-key_1": "val"})
        # Key chars are already valid
        assert "my-key_1" in result

    def test_invalid_key_chars_replaced(self):
        result = validate_context({"my key!": "val"})
        # Spaces and ! are replaced with _
        assert "my_key_" in result

    def test_bool_value_allowed(self):
        result = validate_context({"active": True})
        assert result["active"] is True

    def test_none_value_allowed(self):
        result = validate_context({"opt": None})
        assert result["opt"] is None

    def test_list_value_processed(self):
        result = validate_context({"items": [1, 2, 3]})
        assert result["items"] == [1, 2, 3]

    def test_nested_dict_value_processed(self):
        result = validate_context({"meta": {"env": "prod"}})
        assert result["meta"]["env"] == "prod"

    def test_non_standard_type_converted_to_string(self):
        # Bytes is not a standard JSON type — should be str()'d
        result = validate_context({"raw": b"bytes"})
        assert isinstance(result["raw"], str)

    def test_empty_dict_returns_empty(self):
        assert validate_context({}) == {}


# ---------------------------------------------------------------------------
# _validate_nested
# ---------------------------------------------------------------------------


class TestValidateNested:
    def test_string_sanitized(self):
        result = _validate_nested("hello\x00world", depth=0, max_depth=3)
        assert result == "helloworld"

    def test_integer_passthrough(self):
        assert _validate_nested(42, depth=0, max_depth=3) == 42

    def test_none_passthrough(self):
        assert _validate_nested(None, depth=0, max_depth=3) is None

    def test_dict_recursed(self):
        result = _validate_nested({"a": "b\x01c"}, depth=0, max_depth=3)
        assert result["a"] == "bc"

    def test_list_recursed(self):
        result = _validate_nested(["a\x00b", "c"], depth=0, max_depth=3)
        assert result[0] == "ab"
        assert result[1] == "c"

    def test_depth_exceeded_raises(self):
        with pytest.raises(ValidationError) as exc:
            _validate_nested({"x": 1}, depth=4, max_depth=3)
        assert exc.value.field == "context"

    def test_list_truncated_at_100(self):
        long_list = list(range(150))
        result = _validate_nested(long_list, depth=0, max_depth=3)
        assert len(result) == 100

    def test_deeply_nested_within_limit(self):
        # Depth 0→1→2→3 is on the boundary (depth=3, max_depth=3 → exceeds)
        # But depth 0→1→2 should be fine
        data = {"a": {"b": {"c": "leaf"}}}
        result = _validate_nested(data, depth=0, max_depth=3)
        assert result["a"]["b"]["c"] == "leaf"

    def test_depth_at_max_with_primitive_does_not_raise(self):
        # At depth=3 with max_depth=3: 3 > 3 is False — scalar/primitive is fine
        assert _validate_nested(42, depth=3, max_depth=3) == 42
        assert _validate_nested(None, depth=3, max_depth=3) is None

    def test_depth_exceeds_max_raises(self):
        with pytest.raises(ValidationError):
            _validate_nested({"x": 1}, depth=4, max_depth=3)

    def test_dict_at_max_depth_raises_on_recurse(self):
        # Dict at depth=3 recurses values to depth=4 → raises
        with pytest.raises(ValidationError):
            _validate_nested({"x": 1}, depth=3, max_depth=3)


# ---------------------------------------------------------------------------
# validate_agent_ids
# ---------------------------------------------------------------------------


class TestValidateAgentIds:
    def test_none_returns_empty_list(self):
        assert validate_agent_ids(None) == []

    def test_empty_list_returns_empty(self):
        assert validate_agent_ids([]) == []

    def test_non_list_raises(self):
        with pytest.raises(ValidationError) as exc:
            validate_agent_ids("agent1")  # type: ignore[arg-type]
        assert exc.value.field == "agent_ids"

    def test_too_many_agents_raises(self):
        with pytest.raises(ValidationError) as exc:
            validate_agent_ids(["a"] * (MAX_AGENT_IDS + 1))
        assert exc.value.field == "agent_ids"

    def test_non_string_id_raises(self):
        with pytest.raises(ValidationError) as exc:
            validate_agent_ids([123])  # type: ignore[list-item]
        assert exc.value.field == "agent_ids"

    def test_id_with_invalid_chars_raises(self):
        with pytest.raises(ValidationError) as exc:
            validate_agent_ids(["my agent!"])
        assert exc.value.field == "agent_ids"

    def test_empty_string_id_raises(self):
        with pytest.raises(ValidationError) as exc:
            validate_agent_ids([""])
        assert exc.value.field == "agent_ids"

    def test_id_stripped_to_empty_raises(self):
        # A string of only invalid chars results in empty after sanitization
        with pytest.raises(ValidationError):
            validate_agent_ids(["!!!"])

    def test_valid_ids_returned(self):
        result = validate_agent_ids(["agent-1", "my_agent", "AgentA"])
        assert result == ["agent-1", "my_agent", "AgentA"]

    def test_exactly_max_agents_allowed(self):
        result = validate_agent_ids(["agent"] * MAX_AGENT_IDS)
        assert len(result) == MAX_AGENT_IDS

    def test_hyphen_and_underscore_allowed(self):
        result = validate_agent_ids(["my-agent_v2"])
        assert result == ["my-agent_v2"]


# ---------------------------------------------------------------------------
# validate_goal (supplement to test_validation_run.py)
# ---------------------------------------------------------------------------


class TestValidateGoalExtended:
    def test_whitespace_only_raises(self):
        with pytest.raises(ValidationError) as exc:
            validate_goal("   ")
        assert exc.value.field == "goal"

    def test_exactly_max_length_allowed(self):
        result = validate_goal("x" * MAX_GOAL_LENGTH)
        assert len(result) == MAX_GOAL_LENGTH

    def test_strips_and_sanitizes(self):
        result = validate_goal("  Run diagnostics\x00  ")
        assert result == "Run diagnostics"


# ---------------------------------------------------------------------------
# validate_agent_profile_id (supplement)
# ---------------------------------------------------------------------------


class TestValidateAgentProfileIdExtended:
    def test_non_string_raises(self):
        with patch("app.mcp.config_loader.get_enabled_agent_profiles") as m:
            m.return_value = [("default", {})]
            with pytest.raises(ValidationError) as exc:
                validate_agent_profile_id(123)  # type: ignore[arg-type]
            assert exc.value.field == "agent_profile_id"

    def test_empty_string_returns_default(self):
        with patch("app.mcp.config_loader.get_enabled_agent_profiles") as m:
            m.return_value = [("default", {})]
            result = validate_agent_profile_id("")
            assert result == "default"


# ---------------------------------------------------------------------------
# validate_workflow_id
# ---------------------------------------------------------------------------


class TestValidateWorkflowId:
    def test_none_raises(self):
        with pytest.raises(ValidationError) as exc:
            validate_workflow_id(None)
        assert exc.value.field == "workflow_id"

    def test_empty_string_raises(self):
        with pytest.raises(ValidationError) as exc:
            validate_workflow_id("")
        assert exc.value.field == "workflow_id"

    def test_non_string_raises(self):
        with pytest.raises(ValidationError) as exc:
            validate_workflow_id(42)  # type: ignore[arg-type]
        assert exc.value.field == "workflow_id"

    def test_invalid_chars_stripped_to_empty_raises(self):
        with pytest.raises(ValidationError) as exc:
            validate_workflow_id("!@#$%")
        assert exc.value.field == "workflow_id"

    def test_too_long_raises(self):
        with pytest.raises(ValidationError) as exc:
            validate_workflow_id("a" * 101)
        assert exc.value.field == "workflow_id"

    def test_valid_id_returned(self):
        result = validate_workflow_id("wf-network-scan-v2")
        assert result == "wf-network-scan-v2"

    def test_alphanumeric_with_hyphen_underscore(self):
        result = validate_workflow_id("My_Workflow-1")
        assert result == "My_Workflow-1"

    def test_exactly_100_chars_allowed(self):
        result = validate_workflow_id("a" * 100)
        assert len(result) == 100

    def test_special_chars_stripped(self):
        # validate_workflow_id strips chars via re.sub then checks length/empty
        # "wf!scan" → "wfscan" (valid)
        result = validate_workflow_id("wf!scan")
        assert result == "wfscan"


# ---------------------------------------------------------------------------
# validate_run_context (supplement)
# ---------------------------------------------------------------------------


class TestValidateRunContext:
    def test_delegates_to_validate_context(self):
        # validate_run_context is an alias — ensure it passes same validation
        with pytest.raises(ValidationError):
            validate_run_context([1, 2, 3])  # type: ignore[arg-type]

    def test_valid_context_passthrough(self):
        result = validate_run_context({"hostname": "web-01", "port": 443})
        assert result["hostname"] == "web-01"
