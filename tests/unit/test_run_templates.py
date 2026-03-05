"""Unit tests for app/core/run_templates.py."""


import pytest

from app.core.run_templates import (
    get_run_template,
    list_run_templates,
    load_run_templates,
    render_template_goal,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FAKE_TEMPLATES = {
    "disk-check": {
        "name": "Disk Check",
        "description": "Check disk on a host",
        "agent_profile_id": "default",
        "goal_template": "Check disk on {host}. Alert if above {threshold}%.",
        "params": {
            "host": {"description": "Hostname", "required": True},
            "threshold": {"description": "Threshold %", "required": False, "default": "80"},
        },
    },
    "service-restart": {
        "name": "Service Restart",
        "description": "Restart a service",
        "agent_profile_id": "infrastructure",
        "goal_template": "Restart {service} on {host}.",
        "params": {
            "host": {"description": "Hostname", "required": True},
            "service": {"description": "Service name", "required": True},
        },
    },
    "no-params": {
        "name": "No Params",
        "description": "A template with no params",
        "agent_profile_id": "default",
        "goal_template": "Run a health check.",
        "params": {},
    },
}


@pytest.fixture(autouse=True)
def patch_load(monkeypatch):
    """Patch _load_yaml so tests never touch the filesystem."""
    monkeypatch.setattr(
        "app.core.run_templates._load_yaml",
        lambda _filename: {"run_templates": _FAKE_TEMPLATES},
    )


# ---------------------------------------------------------------------------
# load_run_templates
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLoadRunTemplates:
    def test_returns_dict(self):
        result = load_run_templates()
        assert isinstance(result, dict)
        assert "disk-check" in result

    def test_empty_when_yaml_missing(self, monkeypatch):
        monkeypatch.setattr(
            "app.core.run_templates._load_yaml",
            lambda _: {},
        )
        assert load_run_templates() == {}

    def test_empty_when_key_absent(self, monkeypatch):
        monkeypatch.setattr(
            "app.core.run_templates._load_yaml",
            lambda _: {"other_key": {}},
        )
        assert load_run_templates() == {}


# ---------------------------------------------------------------------------
# get_run_template
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetRunTemplate:
    def test_returns_template_by_name(self):
        t = get_run_template("disk-check")
        assert t is not None
        assert t["name"] == "Disk Check"

    def test_returns_none_for_unknown(self):
        assert get_run_template("nonexistent") is None


# ---------------------------------------------------------------------------
# list_run_templates
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListRunTemplates:
    def test_returns_list(self):
        result = list_run_templates()
        assert isinstance(result, list)
        assert len(result) == 3

    def test_each_item_has_required_keys(self):
        for item in list_run_templates():
            assert "id" in item
            assert "name" in item
            assert "description" in item
            assert "agent_profile_id" in item
            assert "params" in item

    def test_params_schema_structure(self):
        result = list_run_templates()
        disk = next(t for t in result if t["id"] == "disk-check")
        assert "host" in disk["params"]
        assert disk["params"]["host"]["required"] is True
        assert disk["params"]["threshold"]["required"] is False
        assert disk["params"]["threshold"]["default"] == "80"

    def test_template_without_params(self):
        result = list_run_templates()
        no_params = next(t for t in result if t["id"] == "no-params")
        assert no_params["params"] == {}


# ---------------------------------------------------------------------------
# render_template_goal
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRenderTemplateGoal:
    def test_renders_required_param(self):
        template = _FAKE_TEMPLATES["disk-check"]
        goal, profile = render_template_goal(template, {"host": "prod-01"})
        assert "prod-01" in goal
        assert "80%" in goal  # default applied
        assert profile == "default"

    def test_caller_overrides_default(self):
        template = _FAKE_TEMPLATES["disk-check"]
        goal, _ = render_template_goal(template, {"host": "prod-01", "threshold": "90"})
        assert "90%" in goal

    def test_missing_required_param_raises(self):
        template = _FAKE_TEMPLATES["disk-check"]
        with pytest.raises(ValueError, match="Missing required parameter"):
            render_template_goal(template, {})

    def test_missing_multiple_required_params_raises(self):
        template = _FAKE_TEMPLATES["service-restart"]
        with pytest.raises(ValueError, match="Missing required parameter"):
            render_template_goal(template, {})

    def test_returns_agent_profile_id(self):
        template = _FAKE_TEMPLATES["service-restart"]
        _, profile = render_template_goal(template, {"host": "h", "service": "nginx"})
        assert profile == "infrastructure"

    def test_no_params_template(self):
        template = _FAKE_TEMPLATES["no-params"]
        goal, profile = render_template_goal(template, {})
        assert goal == "Run a health check."
        assert profile == "default"

    def test_extra_params_ignored(self):
        """Extra params that aren't in the template should be silently accepted."""
        template = _FAKE_TEMPLATES["disk-check"]
        # {extra} is not in the template's goal_template string, but it shouldn't cause an error
        goal, _ = render_template_goal(template, {"host": "h", "extra": "ignored"})
        assert "h" in goal

    def test_goal_is_stripped(self):
        """YAML block scalars can have trailing newlines; ensure they're stripped."""
        template = {
            "name": "t",
            "agent_profile_id": "default",
            "goal_template": "  Goal with spaces.  \n",
            "params": {},
        }
        goal, _ = render_template_goal(template, {})
        assert goal == "Goal with spaces."

    def test_string_coercion_of_param_values(self):
        """Numeric values passed as params should be coerced to strings."""
        template = _FAKE_TEMPLATES["disk-check"]
        goal, _ = render_template_goal(template, {"host": "h", "threshold": 95})
        assert "95%" in goal
