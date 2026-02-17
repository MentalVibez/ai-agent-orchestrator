"""Tool system for agents to access external resources safely."""

import logging
import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.exceptions import AgentError

logger = logging.getLogger(__name__)


def _get_workspace_root() -> Path:
    """Return the allowed workspace root for file tools (security: prevent path traversal)."""
    from app.core.config import settings

    root = getattr(settings, "agent_workspace_root", None) or ""
    if root and os.path.isabs(root):
        return Path(root).resolve()
    if root:
        return Path(root).resolve()
    return Path.cwd().resolve()


def _resolve_within_workspace(file_path: str, agent_id: str) -> Path:
    """
    Resolve path and ensure it is under the configured workspace root.
    Raises AgentError if outside workspace (path traversal attempt).
    """
    root = _get_workspace_root()
    resolved = Path(file_path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise AgentError(
            f"Path is outside allowed workspace: {resolved}",
            agent_id=agent_id,
            details={"workspace_root": str(root), "resolved": str(resolved)},
        )
    return resolved


class AgentTool(ABC):
    """Base class for agent tools."""

    def __init__(self, tool_id: str, name: str, description: str):
        """
        Initialize tool.

        Args:
            tool_id: Unique tool identifier
            name: Human-readable tool name
            description: Tool description
        """
        self.tool_id = tool_id
        self.name = name
        self.description = description

    @abstractmethod
    async def execute(
        self, agent_id: str, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute the tool.

        Args:
            agent_id: ID of agent requesting tool execution
            params: Tool parameters
            context: Optional execution context

        Returns:
            Tool execution result

        Raises:
            AgentError: If tool execution fails
        """
        pass

    def validate_params(self, params: Dict[str, Any]) -> bool:
        """
        Validate tool parameters.

        Args:
            params: Parameters to validate

        Returns:
            True if valid, False otherwise
        """
        return True


class FileReadTool(AgentTool):
    """Tool for reading files safely."""

    MAX_FILE_SIZE = 1 * 1024 * 1024  # 1MB limit
    ALLOWED_EXTENSIONS = {
        ".py",
        ".js",
        ".ts",
        ".json",
        ".yaml",
        ".yml",
        ".md",
        ".txt",
        ".sh",
        ".sql",
    }

    def __init__(self):
        super().__init__(
            tool_id="file_read",
            name="Read File",
            description="Read contents of a file (read-only, size-limited)",
        )

    async def execute(
        self, agent_id: str, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Read file contents."""
        file_path = params.get("file_path")
        if not file_path:
            raise AgentError(
                "file_path parameter is required",
                agent_id=agent_id,
                details={"tool": self.tool_id, "params": params},
            )

        # Validate file path (prevent directory traversal)
        try:
            resolved_path = _resolve_within_workspace(file_path, agent_id)
            # Check if file exists
            if not resolved_path.exists():
                raise AgentError(f"File not found: {file_path}", agent_id=agent_id)

            # Check file extension
            if resolved_path.suffix not in self.ALLOWED_EXTENSIONS:
                raise AgentError(
                    f"File type not allowed: {resolved_path.suffix}",
                    agent_id=agent_id,
                    details={"allowed_extensions": list(self.ALLOWED_EXTENSIONS)},
                )

            # Check file size
            file_size = resolved_path.stat().st_size
            if file_size > self.MAX_FILE_SIZE:
                raise AgentError(
                    f"File too large: {file_size} bytes (max: {self.MAX_FILE_SIZE})",
                    agent_id=agent_id,
                )

            # Read file
            with open(resolved_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            return {
                "success": True,
                "file_path": str(resolved_path),
                "content": content,
                "size": file_size,
                "lines": len(content.splitlines()),
            }

        except AgentError:
            raise
        except Exception as e:
            raise AgentError(f"Failed to read file: {str(e)}", agent_id=agent_id)


class CodeSearchTool(AgentTool):
    """Tool for searching codebase with grep-like functionality."""

    MAX_RESULTS = 100
    MAX_PATTERN_LENGTH = 200

    def __init__(self):
        super().__init__(
            tool_id="code_search",
            name="Code Search",
            description="Search codebase for patterns (grep-like functionality)",
        )

    async def execute(
        self, agent_id: str, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Search codebase for patterns."""
        pattern = params.get("pattern")
        file_pattern = params.get("file_pattern", "*.py")
        directory = params.get("directory", ".")
        case_sensitive = params.get("case_sensitive", False)

        if not pattern:
            raise AgentError("pattern parameter is required", agent_id=agent_id)

        if len(pattern) > self.MAX_PATTERN_LENGTH:
            raise AgentError(
                f"Pattern too long: {len(pattern)} characters (max: {self.MAX_PATTERN_LENGTH})",
                agent_id=agent_id,
            )

        try:
            # Validate directory (must be within workspace)
            search_dir = _resolve_within_workspace(directory, agent_id)
            if not search_dir.exists() or not search_dir.is_dir():
                raise AgentError(f"Invalid directory: {directory}", agent_id=agent_id)

            # Use grep or Python regex search
            results = []
            pattern_re = re.compile(pattern, re.IGNORECASE if not case_sensitive else 0)

            for file_path in search_dir.rglob(file_pattern):
                if file_path.is_file():
                    try:
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            for line_num, line in enumerate(f, 1):
                                if pattern_re.search(line):
                                    results.append(
                                        {
                                            "file": str(file_path.relative_to(search_dir)),
                                            "line": line_num,
                                            "content": line.strip()[:200],  # Limit line length
                                        }
                                    )
                                    if len(results) >= self.MAX_RESULTS:
                                        break
                    except Exception:
                        continue  # Skip files that can't be read

                if len(results) >= self.MAX_RESULTS:
                    break

            return {
                "success": True,
                "pattern": pattern,
                "results": results,
                "count": len(results),
                "truncated": len(results) >= self.MAX_RESULTS,
            }

        except AgentError:
            raise
        except Exception as e:
            raise AgentError(f"Code search failed: {str(e)}", agent_id=agent_id)


class DirectoryListTool(AgentTool):
    """Tool for listing directory contents."""

    MAX_DEPTH = 3
    MAX_ENTRIES = 100

    def __init__(self):
        super().__init__(
            tool_id="directory_list",
            name="List Directory",
            description="List files and directories in a path",
        )

    async def execute(
        self, agent_id: str, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """List directory contents."""
        directory = params.get("directory", ".")
        max_depth = min(params.get("max_depth", 2), self.MAX_DEPTH)

        try:
            dir_path = _resolve_within_workspace(directory, agent_id)
            if not dir_path.exists() or not dir_path.is_dir():
                raise AgentError(f"Invalid directory: {directory}", agent_id=agent_id)

            entries = []
            for root, dirs, files in os.walk(dir_path):
                depth = root.replace(str(dir_path), "").count(os.sep)
                if depth > max_depth:
                    continue

                rel_root = os.path.relpath(root, dir_path)
                for d in dirs:
                    entries.append(
                        {"type": "directory", "path": os.path.join(rel_root, d), "name": d}
                    )

                for f in files:
                    file_path = Path(root) / f
                    entries.append(
                        {
                            "type": "file",
                            "path": os.path.join(rel_root, f),
                            "name": f,
                            "size": file_path.stat().st_size if file_path.exists() else 0,
                        }
                    )

                if len(entries) >= self.MAX_ENTRIES:
                    break

            return {
                "success": True,
                "directory": str(dir_path),
                "entries": entries[: self.MAX_ENTRIES],
                "count": len(entries),
                "truncated": len(entries) >= self.MAX_ENTRIES,
            }

        except AgentError:
            raise
        except Exception as e:
            raise AgentError(f"Directory listing failed: {str(e)}", agent_id=agent_id)


class FileMetadataTool(AgentTool):
    """Tool for getting file metadata."""

    def __init__(self):
        super().__init__(
            tool_id="file_metadata",
            name="File Metadata",
            description="Get metadata about a file (size, type, permissions)",
        )

    async def execute(
        self, agent_id: str, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Get file metadata."""
        file_path = params.get("file_path")
        if not file_path:
            raise AgentError("file_path parameter is required", agent_id=agent_id)

        try:
            resolved_path = _resolve_within_workspace(file_path, agent_id)
            if not resolved_path.exists():
                raise AgentError(f"File not found: {file_path}", agent_id=agent_id)

            stat = resolved_path.stat()

            return {
                "success": True,
                "file_path": str(resolved_path),
                "exists": True,
                "size": stat.st_size,
                "is_file": resolved_path.is_file(),
                "is_directory": resolved_path.is_dir(),
                "extension": resolved_path.suffix,
                "modified": stat.st_mtime,
            }

        except AgentError:
            raise
        except Exception as e:
            raise AgentError(f"Failed to get file metadata: {str(e)}", agent_id=agent_id)
