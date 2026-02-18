"""Ansible Agent for remediation (DEX fix layer)."""

import asyncio
import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from app.agents.base import BaseAgent
from app.llm.base import LLMProvider
from app.models.agent import AgentResult

logger = logging.getLogger(__name__)

# Security: only allow safe playbook filenames — no path traversal, no shell metacharacters
_PLAYBOOK_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-]+\.(yml|yaml)$")

# Security: only allow alphanumeric, hyphen, underscore, dot, slash for inventory paths
_INVENTORY_SAFE_RE = re.compile(r"^[a-zA-Z0-9_\-./]+$")

# Security: only allow safe host/group names for --limit
_LIMIT_SAFE_RE = re.compile(r"^[a-zA-Z0-9_\-.,]+$")

SUBPROCESS_TIMEOUT_SECONDS = 300  # 5-minute hard timeout for playbook execution


def _default_playbooks_dir() -> Path:
    """Default playbooks directory: project root / playbooks."""
    return Path(__file__).resolve().parent.parent.parent / "playbooks"


class AnsibleAgent(BaseAgent):
    """Agent that runs Ansible playbooks for remediation (DEX fix layer)."""

    def __init__(
        self,
        llm_provider: LLMProvider,
        playbooks_dir: Optional[Path] = None,
        ansible_path: Optional[str] = None,
    ):
        """
        Initialize the Ansible Agent.

        Args:
            llm_provider: LLM provider (for future summarization of playbook output)
            playbooks_dir: Directory containing playbooks; default project_root/playbooks
            ansible_path: Path to ansible-playbook; default from PATH
        """
        super().__init__(
            agent_id="ansible",
            name="Ansible Remediation Agent",
            description="Runs Ansible playbooks to fix issues (restart services, config changes, patches)",
            llm_provider=llm_provider,
            capabilities=[
                "remediation",
                "playbook_execution",
                "configuration_management",
                "service_management",
            ],
        )
        self._playbooks_dir = Path(playbooks_dir) if playbooks_dir else _default_playbooks_dir()
        self._ansible_path = ansible_path or shutil.which("ansible-playbook") or "ansible-playbook"

    async def execute(self, task: str, context: Optional[Dict[str, Any]] = None) -> AgentResult:
        """
        Run an Ansible playbook.

        Context may include:
          - playbook: name of playbook file (e.g. "restart_service.yml") or path relative to playbooks_dir
          - inventory: path to inventory file (optional; must resolve within playbooks_dir)
          - limit: limit to host/group (e.g. "host1" or "webservers") — alphanumeric only
          - extra_vars: dict of extra variables (e.g. {"service_name": "nginx"}) — must be a dict
        """
        context = context or {}
        playbook_name = (context.get("playbook") or "").strip()
        if not playbook_name:
            return self._format_result(
                success=False,
                output={},
                error="context.playbook is required (e.g. 'restart_service.yml')",
                metadata={"agent_id": self.agent_id, "task": task},
            )

        # Security: validate playbook filename — no path traversal, no shell metacharacters
        if not _PLAYBOOK_NAME_RE.match(playbook_name):
            return self._format_result(
                success=False,
                output={},
                error=(
                    f"Invalid playbook name '{playbook_name}'. "
                    "Must match pattern: [a-zA-Z0-9_-]+.(yml|yaml)"
                ),
                metadata={"agent_id": self.agent_id},
            )

        playbook_path = self._playbooks_dir / playbook_name
        if not playbook_path.is_file():
            return self._format_result(
                success=False,
                output={},
                error=f"Playbook not found: {playbook_name} (looked in {self._playbooks_dir})",
                metadata={"agent_id": self.agent_id, "playbooks_dir": str(self._playbooks_dir)},
            )

        # Security: ensure resolved path is within playbooks_dir (redundant but defence-in-depth)
        try:
            playbook_path.resolve().relative_to(self._playbooks_dir.resolve())
        except ValueError:
            return self._format_result(
                success=False,
                output={},
                error="Playbook path escapes playbooks directory.",
                metadata={"agent_id": self.agent_id},
            )

        args = [str(playbook_path)]

        # Security: validate inventory path
        inventory = context.get("inventory")
        if inventory:
            inventory_str = str(inventory).strip()
            if not _INVENTORY_SAFE_RE.match(inventory_str):
                return self._format_result(
                    success=False,
                    output={},
                    error="Invalid inventory path: only alphanumeric, hyphen, underscore, dot, slash allowed.",
                    metadata={"agent_id": self.agent_id},
                )
            inventory_path = Path(inventory_str)
            if not inventory_path.is_absolute():
                inventory_path = (self._playbooks_dir / inventory_path).resolve()
            try:
                inventory_path.relative_to(self._playbooks_dir.resolve())
            except ValueError:
                return self._format_result(
                    success=False,
                    output={},
                    error="Inventory path must be within the playbooks directory.",
                    metadata={"agent_id": self.agent_id},
                )
            args.extend(["-i", str(inventory_path)])

        # Security: validate --limit argument
        limit = context.get("limit")
        if limit:
            limit_str = str(limit).strip()
            if not _LIMIT_SAFE_RE.match(limit_str):
                return self._format_result(
                    success=False,
                    output={},
                    error="Invalid limit value: only alphanumeric, hyphen, underscore, dot, comma allowed.",
                    metadata={"agent_id": self.agent_id},
                )
            args.extend(["--limit", limit_str])

        # Security: extra_vars must be a dict; serialize as JSON blob to prevent key=value injection
        extra = context.get("extra_vars")
        if extra is not None:
            if not isinstance(extra, dict):
                return self._format_result(
                    success=False,
                    output={},
                    error="extra_vars must be a dict (e.g. {'service_name': 'nginx'}), not a string.",
                    metadata={"agent_id": self.agent_id},
                )
            if extra:
                # Pass as JSON blob — avoids any key=value shell parsing by ansible-playbook
                args.extend(["-e", json.dumps(extra)])

        logger.info(
            "Ansible: running playbook=%s limit=%s inventory=%s extra_vars_keys=%s",
            playbook_name,
            limit or "(none)",
            inventory or "(none)",
            list(extra.keys()) if isinstance(extra, dict) else "(none)",
        )

        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    self._ansible_path,
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(self._playbooks_dir),
                ),
                timeout=SUBPROCESS_TIMEOUT_SECONDS,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=SUBPROCESS_TIMEOUT_SECONDS
            )
            out_str = stdout.decode().strip() if stdout else ""
            err_str = stderr.decode().strip() if stderr else ""

            success = proc.returncode == 0
            return self._format_result(
                success=success,
                output={
                    "playbook": playbook_name,
                    "return_code": proc.returncode,
                    "stdout": out_str,
                    "stderr": err_str,
                },
                error=None if success else (err_str or f"exit code {proc.returncode}"),
                metadata={
                    "agent_id": self.agent_id,
                    "task": task,
                    "playbook": playbook_name,
                },
            )
        except asyncio.TimeoutError:
            return self._format_result(
                success=False,
                output={},
                error=f"Playbook execution timed out after {SUBPROCESS_TIMEOUT_SECONDS}s",
                metadata={"agent_id": self.agent_id, "playbook": playbook_name},
            )
        except FileNotFoundError:
            return self._format_result(
                success=False,
                output={},
                error=f"ansible-playbook not found (install Ansible and ensure {self._ansible_path} is in PATH)",
                metadata={"agent_id": self.agent_id},
            )
        except Exception as e:
            logger.exception("Ansible execution failed")
            return self._format_result(
                success=False,
                output={},
                error=str(e),
                metadata={"agent_id": self.agent_id},
            )
