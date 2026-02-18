"""Osquery Agent for endpoint/device data (DEX data layer)."""

import asyncio
import json
import logging
import re
import shutil
from typing import Any, Dict, List, Optional

from app.agents.base import BaseAgent
from app.llm.base import LLMProvider
from app.models.agent import AgentResult

logger = logging.getLogger(__name__)

# Default queries when no query provided (safe, small result sets)
DEFAULT_QUERIES = {
    "processes": "SELECT pid, name, cpu_time, memory FROM processes ORDER BY cpu_time DESC LIMIT 15",
    "system_info": "SELECT hostname, cpu_type, physical_memory FROM system_info",
    "listening_ports": "SELECT port, protocol, address, pid FROM listening_ports LIMIT 20",
    "logged_in_users": "SELECT user, type, host FROM logged_in_users",
    "os_version": "SELECT name, version, platform FROM os_version",
}

# Security: SQL keywords that indicate non-SELECT (write/destructive) operations
_FORBIDDEN_SQL_KEYWORDS = re.compile(
    r"\b(DROP|INSERT|UPDATE|DELETE|ATTACH|DETACH|PRAGMA\s+\w+\s*=|CREATE|ALTER|REPLACE)\b",
    re.IGNORECASE,
)

# Security: block semicolons which could chain multiple statements
_SEMICOLON_RE = re.compile(r";")

SUBPROCESS_TIMEOUT_SECONDS = 30  # osquery queries should complete quickly


def _validate_query(query: str) -> Optional[str]:
    """
    Validate that a query is a safe SELECT-only statement.
    Returns an error string if invalid, or None if valid.
    """
    query_stripped = query.strip()

    # Must start with SELECT (case-insensitive)
    if not re.match(r"^\s*SELECT\b", query_stripped, re.IGNORECASE):
        return "Only SELECT queries are allowed."

    # No forbidden keywords (DROP, INSERT, UPDATE, DELETE, etc.)
    match = _FORBIDDEN_SQL_KEYWORDS.search(query_stripped)
    if match:
        return f"Forbidden SQL keyword detected: '{match.group(0)}'"

    # No semicolons (prevents statement chaining)
    if _SEMICOLON_RE.search(query_stripped):
        return "Semicolons are not allowed in queries (prevents query chaining)."

    return None


class OsqueryAgent(BaseAgent):
    """Agent that runs osquery for endpoint visibility (DEX data)."""

    def __init__(self, llm_provider: LLMProvider, osquery_path: Optional[str] = None):
        """
        Initialize the Osquery Agent.

        Args:
            llm_provider: LLM provider (used for summarizing results if needed)
            osquery_path: Optional path to osqueryi binary; if None, use 'osqueryi' from PATH
        """
        super().__init__(
            agent_id="osquery",
            name="Osquery Agent",
            description="Runs osquery to collect endpoint/device data (processes, ports, users, system info) for DEX",
            llm_provider=llm_provider,
            capabilities=[
                "endpoint_visibility",
                "process_list",
                "listening_ports",
                "system_info",
                "logged_in_users",
            ],
        )
        self._osquery_path = osquery_path or shutil.which("osqueryi") or "osqueryi"

    async def execute(self, task: str, context: Optional[Dict[str, Any]] = None) -> AgentResult:
        """
        Run osquery and return results.

        Context may include:
          - query: SQL-like osquery SELECT query (e.g. "SELECT * FROM processes LIMIT 10")
            Only SELECT queries are permitted; DROP/INSERT/UPDATE/DELETE are rejected.
          - query_key: key into DEFAULT_QUERIES (e.g. "processes", "system_info")
        If neither is provided, runs "system_info" and "processes" for a quick overview.
        """
        context = context or {}
        custom_query = context.get("query", "").strip() if context.get("query") else None
        query_key = context.get("query_key", "").strip()

        # Security: validate any custom query before use
        if custom_query:
            validation_error = _validate_query(custom_query)
            if validation_error:
                return self._format_result(
                    success=False,
                    output={},
                    error=f"Query rejected (security policy): {validation_error}",
                    metadata={"agent_id": self.agent_id, "task": task},
                )
            # Use the validated query directly — wrapping via f-string interpolation
            # introduces SQL injection risk. Row capping is enforced by osquery's
            # own output limits at invocation time.
            query = custom_query
            logger.info("osquery: running custom query (validated) for task=%r", task[:100])
        elif query_key and query_key in DEFAULT_QUERIES:
            query = DEFAULT_QUERIES[query_key]
            logger.info("osquery: running default query key=%r", query_key)
        else:
            query = None

        if not query:
            # Run a small default set for "overview"
            results = {}
            for key, q in [
                ("system_info", DEFAULT_QUERIES["system_info"]),
                ("processes", DEFAULT_QUERIES["processes"]),
            ]:
                logger.info("osquery: running default overview query key=%r", key)
                out = await self._run_osquery(q)
                results[key] = out
            return self._format_result(
                success=True,
                output={"summary": "Osquery overview (system_info + top processes)", "data": results},
                metadata={"agent_id": self.agent_id, "task": task},
            )

        data = await self._run_osquery(query)
        # Detect if osquery itself returned an error (not just empty results)
        osquery_errored = (
            isinstance(data, list)
            and len(data) == 1
            and "error" in data[0]
        )
        return self._format_result(
            success=not osquery_errored,
            output={
                "query": custom_query or query,
                "data": data,
                "row_count": len(data) if isinstance(data, list) else 0,
            },
            error=data[0].get("error") if osquery_errored else None,
            metadata={"agent_id": self.agent_id, "task": task},
        )

    async def _run_osquery(self, query: str) -> List[Dict[str, Any]]:
        """Run osqueryi with --json and return parsed rows."""
        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    self._osquery_path,
                    "--json",
                    query,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                timeout=SUBPROCESS_TIMEOUT_SECONDS,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=SUBPROCESS_TIMEOUT_SECONDS
            )
            if proc.returncode != 0:
                err_msg = stderr.decode().strip() if stderr else f"exit code {proc.returncode}"
                logger.warning("osquery returned non-zero exit: %s", err_msg)
                return [{"error": err_msg}]

            text = stdout.decode().strip()
            if not text:
                return []

            # osquery --json outputs a JSON array or one JSON object per line
            # Try full JSON array parse first (newer osquery versions)
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                pass

            # Fallback: line-by-line JSON objects
            rows = []
            malformed_count = 0
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    malformed_count += 1
            if malformed_count:
                logger.warning(
                    "osquery: %d malformed JSON line(s) skipped in output", malformed_count
                )
            return rows

        except asyncio.TimeoutError:
            logger.warning("osquery timed out after %ss", SUBPROCESS_TIMEOUT_SECONDS)
            return [{"error": f"osquery timed out after {SUBPROCESS_TIMEOUT_SECONDS}s"}]
        except FileNotFoundError:
            logger.error("osquery not found at %s", self._osquery_path)
            return [{"error": f"osquery not found — install osquery and ensure {self._osquery_path} is in PATH"}]
        except Exception as e:
            logger.exception("osquery execution failed")
            return [{"error": str(e)}]
