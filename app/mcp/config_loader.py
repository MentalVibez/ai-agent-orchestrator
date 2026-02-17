"""Load MCP server and agent profile config from YAML."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# Default config directory (project root / config)
CONFIG_DIR = Path(os.getenv("ORCHESTRATOR_CONFIG_DIR", "config")).resolve()


def _load_yaml(filename: str) -> Dict[str, Any]:
    """Load a YAML file from config dir. Returns empty dict if missing."""
    path = CONFIG_DIR / filename
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def load_mcp_servers_config() -> Dict[str, Any]:
    """
    Load mcp_servers.yaml.
    Returns dict with key 'mcp_servers': { server_id: { name, transport, command?, args?, url?, env?, categories, enabled } }
    """
    data = _load_yaml("mcp_servers.yaml")
    return data


def load_agent_profiles_config() -> Dict[str, Any]:
    """
    Load agent_profiles.yaml.
    Returns dict with key 'agent_profiles': { profile_id: { name, description, role_prompt, allowed_mcp_servers, model, enabled } }
    """
    data = _load_yaml("agent_profiles.yaml")
    return data


def get_enabled_mcp_servers() -> List[tuple]:
    """
    Return list of (server_id, server_config) for enabled servers only.
    """
    data = load_mcp_servers_config()
    servers = data.get("mcp_servers") or {}
    return [
        (sid, cfg)
        for sid, cfg in servers.items()
        if isinstance(cfg, dict) and cfg.get("enabled") is True
    ]


def get_enabled_agent_profiles() -> List[tuple]:
    """
    Return list of (profile_id, profile_config) for enabled profiles only.
    """
    data = load_agent_profiles_config()
    profiles = data.get("agent_profiles") or {}
    return [
        (pid, cfg)
        for pid, cfg in profiles.items()
        if isinstance(cfg, dict) and cfg.get("enabled") is True
    ]


def get_agent_profile(profile_id: str) -> Optional[Dict[str, Any]]:
    """Get a single agent profile by id, or None if not found/disabled."""
    data = load_agent_profiles_config()
    profiles = data.get("agent_profiles") or {}
    cfg = profiles.get(profile_id)
    if isinstance(cfg, dict) and cfg.get("enabled") is not False:
        return cfg
    return None
