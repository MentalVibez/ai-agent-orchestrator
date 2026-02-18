"""Unit tests for run-related validation (validate_goal, validate_agent_profile_id, validate_run_context)."""

from unittest.mock import patch

import pytest

from app.core.exceptions import ValidationError
from app.core.validation import (
    validate_agent_profile_id,
    validate_goal,
    validate_run_context,
)


@pytest.mark.unit
class TestValidateGoal:
    """Test cases for validate_goal."""

    def test_goal_required(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_goal(None)
        assert exc_info.value.field == "goal"
        with pytest.raises(ValidationError):
            validate_goal("")

    def test_goal_must_be_string(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_goal(123)
        assert exc_info.value.field == "goal"

    def test_goal_max_length(self):
        from app.core.validation import MAX_GOAL_LENGTH

        with pytest.raises(ValidationError) as exc_info:
            validate_goal("x" * (MAX_GOAL_LENGTH + 1))
        assert exc_info.value.field == "goal"

    def test_goal_stripped_and_sanitized(self):
        result = validate_goal("  Fetch the data  ")
        assert result == "Fetch the data"

    def test_goal_control_chars_removed(self):
        result = validate_goal("Hello\x00World\x1f")
        assert "\x00" not in result and "\x1f" not in result


@pytest.mark.unit
class TestValidateAgentProfileId:
    """Test cases for validate_agent_profile_id."""

    def test_none_returns_default(self):
        with patch("app.mcp.config_loader.get_enabled_agent_profiles") as m:
            m.return_value = [("default", {}), ("browser", {})]
            assert validate_agent_profile_id(None) == "default"

    def test_invalid_chars_raises(self):
        with patch("app.mcp.config_loader.get_enabled_agent_profiles") as m:
            m.return_value = [("default", {})]
            with pytest.raises(ValidationError) as exc_info:
                validate_agent_profile_id("pro file!")
            assert exc_info.value.field == "agent_profile_id"

    def test_unknown_profile_raises(self):
        with patch("app.mcp.config_loader.get_enabled_agent_profiles") as m:
            m.return_value = [("default", {}), ("browser", {})]
            with pytest.raises(ValidationError) as exc_info:
                validate_agent_profile_id("unknown_profile")
            assert (
                "Unknown" in exc_info.value.message or "unknown" in exc_info.value.message.lower()
            )

    def test_known_profile_returns_sanitized(self):
        with patch("app.mcp.config_loader.get_enabled_agent_profiles") as m:
            m.return_value = [("default", {}), ("browser", {})]
            assert validate_agent_profile_id("browser") == "browser"
            assert validate_agent_profile_id("default") == "default"


@pytest.mark.unit
class TestValidateRunContext:
    """Test cases for validate_run_context (delegates to validate_context)."""

    def test_none_returns_empty_dict(self):
        assert validate_run_context(None) == {}

    def test_valid_context_returned(self):
        result = validate_run_context({"key": "value"})
        assert result == {"key": "value"}

    def test_not_dict_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_run_context("not a dict")
        assert exc_info.value.field == "context"
