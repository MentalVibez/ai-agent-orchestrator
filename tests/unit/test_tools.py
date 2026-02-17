"""Unit tests for Agent Tools."""

import tempfile
from pathlib import Path

import pytest

from app.core.exceptions import AgentError
from app.core.tools import (
    CodeSearchTool,
    DirectoryListTool,
    FileMetadataTool,
    FileReadTool,
)


@pytest.mark.unit
class TestFileReadTool:
    """Test cases for FileReadTool."""

    @pytest.fixture
    def tool(self):
        """Create a file read tool."""
        return FileReadTool()

    @pytest.fixture
    def temp_file(self):
        """Create a temporary file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def test():\n    pass\n")
            temp_path = Path(f.name)
        yield temp_path
        temp_path.unlink()

    @pytest.mark.asyncio
    async def test_execute_success(self, tool: FileReadTool, temp_file: Path):
        """Test successful file read."""
        result = await tool.execute("test_agent", {"file_path": str(temp_file)})

        assert result["success"] is True
        assert "content" in result
        assert "def test()" in result["content"]
        assert result["size"] > 0
        assert result["lines"] > 0

    @pytest.mark.asyncio
    async def test_execute_missing_file_path(self, tool: FileReadTool):
        """Test file read with missing file_path parameter."""
        with pytest.raises(AgentError) as exc_info:
            await tool.execute("test_agent", {})

        assert "file_path" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_execute_file_not_found(self, tool: FileReadTool):
        """Test file read with non-existent file."""
        with pytest.raises(AgentError) as exc_info:
            await tool.execute("test_agent", {"file_path": "/nonexistent/file.py"})

        assert "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_execute_invalid_extension(self, tool: FileReadTool):
        """Test file read with invalid extension."""
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
            temp_path = Path(f.name)

        try:
            with pytest.raises(AgentError) as exc_info:
                await tool.execute("test_agent", {"file_path": str(temp_path)})

            assert "not allowed" in str(exc_info.value).lower()
        finally:
            temp_path.unlink()

    def test_validate_params(self, tool: FileReadTool):
        """Test parameter validation."""
        assert tool.validate_params({"file_path": "test.py"}) is True


@pytest.mark.unit
class TestCodeSearchTool:
    """Test cases for CodeSearchTool."""

    @pytest.fixture
    def tool(self):
        """Create a code search tool."""
        return CodeSearchTool()

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory with test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("def test_function():\n    pass\n")
            yield Path(tmpdir)

    @pytest.mark.asyncio
    async def test_execute_success(self, tool: CodeSearchTool, temp_dir: Path):
        """Test successful code search."""
        result = await tool.execute(
            "test_agent", {"pattern": "def test", "directory": str(temp_dir)}
        )

        assert result["success"] is True
        assert "results" in result
        assert result["count"] > 0

    @pytest.mark.asyncio
    async def test_execute_missing_pattern(self, tool: CodeSearchTool):
        """Test code search with missing pattern."""
        with pytest.raises(AgentError) as exc_info:
            await tool.execute("test_agent", {"directory": "."})

        assert "pattern" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_execute_pattern_too_long(self, tool: CodeSearchTool):
        """Test code search with pattern too long."""
        long_pattern = "a" * 201
        with pytest.raises(AgentError) as exc_info:
            await tool.execute("test_agent", {"pattern": long_pattern})

        assert "too long" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_execute_invalid_directory(self, tool: CodeSearchTool):
        """Test code search with invalid directory."""
        with pytest.raises(AgentError) as exc_info:
            await tool.execute("test_agent", {"pattern": "test", "directory": "/nonexistent"})

        assert "invalid" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_execute_case_sensitive(self, tool: CodeSearchTool, temp_dir: Path):
        """Test case-sensitive search."""
        result = await tool.execute(
            "test_agent", {"pattern": "DEF", "directory": str(temp_dir), "case_sensitive": True}
        )

        # Should not find "def" when case-sensitive
        assert result["count"] == 0


@pytest.mark.unit
class TestDirectoryListTool:
    """Test cases for DirectoryListTool."""

    @pytest.fixture
    def tool(self):
        """Create a directory list tool."""
        return DirectoryListTool()

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory with files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "file1.txt").touch()
            (Path(tmpdir) / "subdir").mkdir()
            yield Path(tmpdir)

    @pytest.mark.asyncio
    async def test_execute_success(self, tool: DirectoryListTool, temp_dir: Path):
        """Test successful directory listing."""
        result = await tool.execute("test_agent", {"directory": str(temp_dir)})

        assert result["success"] is True
        assert "entries" in result
        assert result["count"] > 0
        assert any(e["name"] == "file1.txt" for e in result["entries"])

    @pytest.mark.asyncio
    async def test_execute_with_max_depth(self, tool: DirectoryListTool, temp_dir: Path):
        """Test directory listing with max depth."""
        result = await tool.execute("test_agent", {"directory": str(temp_dir), "max_depth": 1})

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_invalid_directory(self, tool: DirectoryListTool):
        """Test directory listing with invalid directory."""
        with pytest.raises(AgentError) as exc_info:
            await tool.execute("test_agent", {"directory": "/nonexistent"})

        assert "invalid" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_execute_default_directory(self, tool: DirectoryListTool):
        """Test directory listing with default directory."""
        result = await tool.execute("test_agent", {})

        assert result["success"] is True


@pytest.mark.unit
class TestFileMetadataTool:
    """Test cases for FileMetadataTool."""

    @pytest.fixture
    def tool(self):
        """Create a file metadata tool."""
        return FileMetadataTool()

    @pytest.fixture
    def temp_file(self):
        """Create a temporary file."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = Path(f.name)
        yield temp_path
        temp_path.unlink()

    @pytest.mark.asyncio
    async def test_execute_success(self, tool: FileMetadataTool, temp_file: Path):
        """Test successful file metadata retrieval."""
        result = await tool.execute("test_agent", {"file_path": str(temp_file)})

        assert result["success"] is True
        assert result["exists"] is True
        assert "size" in result
        assert "is_file" in result
        assert "extension" in result

    @pytest.mark.asyncio
    async def test_execute_missing_file_path(self, tool: FileMetadataTool):
        """Test file metadata with missing file_path."""
        with pytest.raises(AgentError) as exc_info:
            await tool.execute("test_agent", {})

        assert "file_path" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_execute_file_not_found(self, tool: FileMetadataTool):
        """Test file metadata with non-existent file."""
        with pytest.raises(AgentError) as exc_info:
            await tool.execute("test_agent", {"file_path": "/nonexistent/file"})

        assert "not found" in str(exc_info.value).lower()
