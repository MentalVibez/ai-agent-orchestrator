"""Run template loader and renderer.

Templates are defined in config/run_templates.yaml as pre-built run recipes
with parameterised goal strings. This module loads them and renders goals
from caller-supplied params.
"""

from typing import Any, Dict, List, Optional, Tuple

from app.mcp.config_loader import _load_yaml


def load_run_templates() -> Dict[str, Any]:
    """Return the full run_templates dict from config/run_templates.yaml."""
    data = _load_yaml("run_templates.yaml")
    return data.get("run_templates") or {}


def get_run_template(name: str) -> Optional[Dict[str, Any]]:
    """Return a single template by name, or None if not found."""
    return load_run_templates().get(name)


def list_run_templates() -> List[Dict[str, Any]]:
    """Return a list of template summaries (name, description, params schema)."""
    templates = load_run_templates()
    result = []
    for template_id, cfg in templates.items():
        params_schema = {
            param_name: {
                "description": param_cfg.get("description", ""),
                "required": param_cfg.get("required", False),
                "default": param_cfg.get("default"),
            }
            for param_name, param_cfg in (cfg.get("params") or {}).items()
        }
        result.append(
            {
                "id": template_id,
                "name": cfg.get("name", template_id),
                "description": cfg.get("description", ""),
                "agent_profile_id": cfg.get("agent_profile_id", "default"),
                "params": params_schema,
            }
        )
    return result


def render_template_goal(template: Dict[str, Any], params: Dict[str, str]) -> Tuple[str, str]:
    """Render the goal string from a template and caller-supplied params.

    Returns (rendered_goal, agent_profile_id).
    Raises ValueError for missing required params or unknown placeholders.
    """
    params_spec = template.get("params") or {}

    # Validate required params
    missing = [
        name
        for name, cfg in params_spec.items()
        if cfg.get("required") and name not in params
    ]
    if missing:
        raise ValueError(f"Missing required parameter(s): {', '.join(missing)}")

    # Merge defaults then caller values
    merged: Dict[str, str] = {}
    for name, cfg in params_spec.items():
        if "default" in cfg and cfg["default"] is not None:
            merged[name] = str(cfg["default"])
    merged.update({k: str(v) for k, v in params.items()})

    goal_template = template.get("goal_template", "")
    try:
        goal = goal_template.format_map(merged)
    except KeyError as e:
        raise ValueError(f"Unknown parameter in template: {e}")

    agent_profile_id = template.get("agent_profile_id", "default")
    return goal.strip(), agent_profile_id
