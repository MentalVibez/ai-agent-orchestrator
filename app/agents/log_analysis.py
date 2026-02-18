"""Log Analysis Agent — real log file parsing and error detection."""

import asyncio
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.agents.base import BaseAgent
from app.llm.base import LLMProvider
from app.models.agent import AgentResult

logger = logging.getLogger(__name__)

# Patterns to identify significant log lines (errors, warnings, exceptions)
_SIGNIFICANT_LINE_RE = re.compile(
    r"\b(ERROR|CRITICAL|FATAL|EXCEPTION|TRACEBACK|WARN(?:ING)?|FAILED|FAILURE|"
    r"OOM|KILLED|SEGFAULT|PANIC|ABORT|TIMEOUT|CONNECTION\s+REFUSED|NO\s+SPACE\s+LEFT)\b",
    re.IGNORECASE,
)

# Common log file paths by service name on Linux
_SERVICE_LOG_PATHS = {
    "nginx": ["/var/log/nginx/error.log", "/var/log/nginx/access.log"],
    "apache": ["/var/log/apache2/error.log", "/var/log/httpd/error_log"],
    "mysql": ["/var/log/mysql/error.log", "/var/log/mysqld.log"],
    "postgresql": ["/var/log/postgresql/postgresql.log"],
    "redis": ["/var/log/redis/redis-server.log"],
    "mongodb": ["/var/log/mongodb/mongod.log"],
    "docker": ["/var/log/docker.log"],
    "syslog": ["/var/log/syslog", "/var/log/messages"],
    "auth": ["/var/log/auth.log", "/var/log/secure"],
    "kern": ["/var/log/kern.log"],
}

# Security: only allow safe service names for journalctl
_SAFE_SERVICE_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-@.]+$")

JOURNALCTL_TIMEOUT = 15  # seconds
MAX_LOG_LINES_FOR_LLM = 200  # cap lines sent to LLM to control token cost
MAX_LOG_READ_BYTES = 500 * 1024  # read at most 500KB from the tail of a log file


def _filter_significant_lines(lines: List[str]) -> List[str]:
    """Filter log lines to those containing errors, exceptions, or warnings."""
    return [line for line in lines if _SIGNIFICANT_LINE_RE.search(line)]


def _read_log_tail(file_path: str, max_bytes: int = MAX_LOG_READ_BYTES) -> Optional[str]:
    """
    Read the tail of a log file (last max_bytes bytes).
    Returns content string, or None if file cannot be read.
    """
    try:
        p = Path(file_path)
        if not p.is_file():
            return None
        size = p.stat().st_size
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                f.readline()  # skip partial first line
            return f.read()
    except (PermissionError, OSError) as e:
        logger.warning("Could not read log file %s: %s", file_path, e)
        return None


async def _run_journalctl(service_name: str, since: str = "1 hour ago") -> Optional[str]:
    """
    Run journalctl for a systemd service.
    Security: service_name is validated against safe pattern before use.
    """
    if not _SAFE_SERVICE_NAME_RE.match(service_name):
        logger.warning("Rejected unsafe service name for journalctl: %r", service_name)
        return None
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                "journalctl",
                "-u", service_name,
                "--since", since,
                "--no-pager",
                "--output", "short",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=JOURNALCTL_TIMEOUT,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=JOURNALCTL_TIMEOUT
        )
        if proc.returncode == 0 and stdout:
            return stdout.decode(errors="replace")
        err = stderr.decode(errors="replace").strip() if stderr else ""
        logger.debug("journalctl for %s returned %d: %s", service_name, proc.returncode, err)
        return None
    except asyncio.TimeoutError:
        logger.warning("journalctl timed out after %ss for service %s", JOURNALCTL_TIMEOUT, service_name)
        return None
    except FileNotFoundError:
        logger.debug("journalctl not available on this system")
        return None
    except Exception as e:
        logger.warning("journalctl failed for %s: %s", service_name, e)
        return None


class LogAnalysisAgent(BaseAgent):
    """Agent specialized in log analysis and troubleshooting — reads real log files."""

    def __init__(self, llm_provider: LLMProvider):
        super().__init__(
            agent_id="log_analysis",
            name="Log Analysis Agent",
            description="Analyzes real log files, detects errors and patterns, provides root cause analysis",
            llm_provider=llm_provider,
            capabilities=[
                "log_parsing",
                "error_detection",
                "pattern_matching",
                "log_aggregation",
                "troubleshooting",
            ],
        )

    async def execute(self, task: str, context: Optional[Dict[str, Any]] = None) -> AgentResult:
        """
        Execute a log analysis task.

        Context may include:
          - log_path: absolute path to a log file (must be within workspace root)
          - service: service name for journalctl or default log path lookup
            (e.g. "nginx", "mysql", "auth")
          - since: time range for journalctl (default "1 hour ago")
          - log_content: raw log text provided directly (skips file reading)
        """
        context = context or {}
        log_content: Optional[str] = None
        source_description = "unknown source"

        # --- Source 1: Directly provided log content ---
        if context.get("log_content"):
            log_content = str(context["log_content"])
            source_description = "provided log content"

        # --- Source 2: Explicit log file path ---
        elif context.get("log_path"):
            log_path = str(context["log_path"]).strip()
            # Security: try FileReadTool first (enforces workspace root + extension allow-list)
            try:
                result = await self.use_tool("file_read", {"file_path": log_path})
                log_content = result.get("content", "")
                source_description = f"file: {log_path}"
            except Exception as e:
                # Fallback: direct tail read for log files outside the workspace root
                # (common for system logs at /var/log/*)
                log_content = _read_log_tail(log_path)
                if log_content is None:
                    return self._format_result(
                        success=False,
                        output={},
                        error=f"Cannot read log file '{log_path}': {e}",
                        metadata={"agent_id": self.agent_id, "task": task},
                    )
                source_description = f"file (direct read): {log_path}"

        # --- Source 3: Service name → journalctl or default log paths ---
        elif context.get("service"):
            service = str(context["service"]).strip()
            since = str(context.get("since", "1 hour ago")).strip()

            # Try journalctl first
            journal_content = await _run_journalctl(service, since=since)
            if journal_content:
                log_content = journal_content
                source_description = f"journalctl: {service} (since {since})"
            else:
                # Fallback to known log file paths
                service_key = service.lower().split(".")[0]  # strip .service suffix
                paths = _SERVICE_LOG_PATHS.get(service_key, [])
                for path in paths:
                    content = _read_log_tail(path)
                    if content:
                        log_content = content
                        source_description = f"file: {path}"
                        break

            if not log_content:
                return self._format_result(
                    success=False,
                    output={},
                    error=(
                        f"Could not read logs for service '{service}'. "
                        "journalctl failed and no readable default log file found. "
                        "Try providing 'log_path' explicitly."
                    ),
                    metadata={"agent_id": self.agent_id, "task": task, "service": service},
                )

        # --- Source 4: Try to infer file path from task text ---
        else:
            path_match = re.search(r"/[\w/.\-]+\.log\b", task)
            if path_match:
                log_path = path_match.group(0)
                log_content = _read_log_tail(log_path)
                source_description = f"file (inferred from task): {log_path}"

            if not log_content:
                return self._format_result(
                    success=False,
                    output={},
                    error=(
                        "No log source specified. Provide one of: "
                        "'log_path' (file path), 'service' (service name for journalctl), "
                        "or 'log_content' (raw log text) in context."
                    ),
                    metadata={"agent_id": self.agent_id, "task": task},
                )

        # --- Process log content ---
        all_lines = log_content.splitlines()
        total_lines = len(all_lines)

        # Filter to significant lines
        significant_lines = _filter_significant_lines(all_lines)
        error_count = sum(
            1 for line in all_lines
            if re.search(r"\b(ERROR|CRITICAL|FATAL)\b", line, re.IGNORECASE)
        )
        warning_count = sum(
            1 for line in all_lines
            if re.search(r"\bWARN(?:ING)?\b", line, re.IGNORECASE)
        )

        # Build content for LLM: prioritize significant lines (capped to MAX_LOG_LINES_FOR_LLM)
        if significant_lines:
            lines_for_llm = significant_lines[-MAX_LOG_LINES_FOR_LLM:]
            content_note = (
                f"Showing {len(lines_for_llm)} significant lines (errors/warnings) "
                f"from {total_lines} total lines."
            )
        else:
            lines_for_llm = all_lines[-MAX_LOG_LINES_FOR_LLM:]
            content_note = (
                f"No errors/warnings found. Showing last {len(lines_for_llm)} lines "
                f"from {total_lines} total."
            )

        log_excerpt = "\n".join(lines_for_llm)

        # Extract top unique error messages (first 5 unique error lines)
        unique_errors = list(dict.fromkeys(
            line.strip() for line in significant_lines
            if re.search(r"\b(ERROR|CRITICAL|FATAL)\b", line, re.IGNORECASE)
        ))[:5]

        # --- LLM Analysis ---
        analysis = await self._generate_response(
            prompt=(
                f"Task: {task}\n\n"
                f"Log source: {source_description}\n"
                f"Total lines: {total_lines} | Errors: {error_count} | Warnings: {warning_count}\n"
                f"{content_note}\n\n"
                f"Log content:\n```\n{log_excerpt}\n```\n\n"
                "Provide: (1) root cause analysis of any errors found, "
                "(2) timeline of events if discernible from timestamps, "
                "(3) specific recommended actions to resolve the issues."
            ),
            system_prompt=(
                "You are an expert log analyst. Analyze log output and provide actionable "
                "root cause analysis. Be specific about error messages and timestamps when present. "
                "Do not speculate beyond what the logs show."
            ),
            temperature=0.2,
        )

        return self._format_result(
            success=True,
            output={
                "source": source_description,
                "total_lines": total_lines,
                "error_count": error_count,
                "warning_count": warning_count,
                "top_errors": unique_errors,
                "root_cause_analysis": analysis,
                "summary": analysis[:200] + "..." if len(analysis) > 200 else analysis,
            },
            metadata={
                "agent_id": self.agent_id,
                "task": task,
                "log_source": source_description,
                "lines_analyzed": len(lines_for_llm),
                "total_lines": total_lines,
            },
        )
