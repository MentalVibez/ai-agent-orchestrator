"""Unit tests for Code Review Agent."""

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.code_review import CodeReviewAgent
from tests.fixtures.mock_llm import MockLLMProvider


@pytest.mark.unit
class TestCodeReviewAgent:
    """Test cases for CodeReviewAgent."""

    @pytest.fixture
    def agent(self, mock_llm_provider: MockLLMProvider):
        """Create a code review agent."""
        return CodeReviewAgent(llm_provider=mock_llm_provider)

    @pytest.mark.asyncio
    async def test_agent_initialization(self, agent: CodeReviewAgent):
        """Test agent is properly initialized."""
        assert agent.agent_id == "code_review"
        assert agent.name == "Code Review Agent"
        assert "security_analysis" in agent.capabilities
        assert "vulnerability_detection" in agent.capabilities

    @pytest.mark.asyncio
    async def test_execute_success_with_file_path(self, agent: CodeReviewAgent):
        """Test successful code review with file path."""
        context = {"file_path": "test.py", "focus_areas": ["security"]}

        # Mock tool calls
        with patch.object(agent, "use_tool") as mock_tool:
            mock_tool.side_effect = [
                {"entries": []},  # directory_list
                {"content": "def test(): pass", "size": 100, "lines": 5},  # file_read
            ]

            result = await agent.execute("Review this file for security issues", context=context)

            assert result.success is True
            assert result.agent_id == "code_review"
            assert "output" in result.output or "summary" in result.output

    @pytest.mark.asyncio
    async def test_execute_success_with_directory(self, agent: CodeReviewAgent):
        """Test successful code review with directory."""
        context = {"directory": ".", "focus_areas": ["quality"]}

        with patch.object(agent, "use_tool") as mock_tool:
            mock_tool.return_value = {"entries": [{"type": "file", "path": "test.py"}]}

            result = await agent.execute("Review code quality", context=context)

            assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_with_security_focus(self, agent: CodeReviewAgent):
        """Test code review with security focus."""
        context = {"directory": ".", "focus_areas": ["security"]}

        with patch.object(agent, "use_tool") as mock_tool:
            mock_tool.side_effect = [
                {"entries": []},  # directory_list
                {"count": 0, "results": []},  # code_search (no matches)
            ]

            result = await agent.execute("Find security vulnerabilities", context=context)

            assert result.success is True
            assert "security" in str(result.output).lower() or "security" in str(result.metadata)

    @pytest.mark.asyncio
    async def test_execute_handles_errors(self, agent: CodeReviewAgent):
        """Test error handling during execution."""
        failing_provider = MockLLMProvider()
        failing_provider.generate = AsyncMock(side_effect=Exception("LLM Error"))
        failing_agent = CodeReviewAgent(llm_provider=failing_provider)

        result = await failing_agent.execute("Test task")

        assert result.success is False
        assert "error" in result.error.lower() or result.error is not None

    @pytest.mark.asyncio
    async def test_collect_code_info_with_file(self, agent: CodeReviewAgent):
        """Test collecting code info with file path."""
        with patch.object(agent, "use_tool") as mock_tool:
            mock_tool.side_effect = [
                {"entries": []},  # directory_list
                {"content": "code", "size": 100, "lines": 10},  # file_read
            ]

            code_info = await agent._collect_code_info("test.py", ".", ["security"])

            assert "files_analyzed" in code_info
            assert len(code_info["files_analyzed"]) > 0

    @pytest.mark.asyncio
    async def test_collect_code_info_with_directory(self, agent: CodeReviewAgent):
        """Test collecting code info with directory."""
        with patch.object(agent, "use_tool") as mock_tool:
            mock_tool.return_value = {"entries": [{"type": "file", "path": "test.py"}]}

            code_info = await agent._collect_code_info(None, ".", ["quality"])

            assert "structure" in code_info

    @pytest.mark.asyncio
    async def test_collect_code_info_handles_tool_errors(self, agent: CodeReviewAgent):
        """Test that tool errors don't crash code info collection."""
        with patch.object(agent, "use_tool", side_effect=Exception("Tool error")):
            code_info = await agent._collect_code_info(None, ".", [])

            assert "error" in code_info or "files_analyzed" in code_info

    def test_build_system_prompt_security_focus(self, agent: CodeReviewAgent):
        """Test building system prompt with security focus."""
        prompt = agent._build_system_prompt(["security"])

        assert "security" in prompt.lower()
        assert "vulnerability" in prompt.lower() or "vulnerabilities" in prompt.lower()

    def test_build_system_prompt_quality_focus(self, agent: CodeReviewAgent):
        """Test building system prompt with quality focus."""
        prompt = agent._build_system_prompt(["quality"])

        assert "quality" in prompt.lower()
        assert "maintainability" in prompt.lower() or "best practices" in prompt.lower()

    def test_build_system_prompt_both_focus(self, agent: CodeReviewAgent):
        """Test building system prompt with both security and quality focus."""
        prompt = agent._build_system_prompt(["security", "quality"])

        assert "security" in prompt.lower()
        assert "quality" in prompt.lower()

    def test_build_user_prompt(self, agent: CodeReviewAgent):
        """Test building user prompt."""
        code_info = {
            "files_analyzed": [{"path": "test.py", "content": "code", "lines": 10}],
            "patterns": [],
            "structure": [],
        }
        context = {"focus_areas": ["security"]}

        prompt = agent._build_user_prompt("Review code", code_info, context)

        assert "Review code" in prompt
        assert "test.py" in prompt

    def test_identify_review_type_security(self, agent: CodeReviewAgent):
        """Test identifying security review type."""
        review_type = agent._identify_review_type("Find security vulnerabilities", ["security"])
        assert review_type == "security_review"

    def test_identify_review_type_quality(self, agent: CodeReviewAgent):
        """Test identifying quality review type."""
        review_type = agent._identify_review_type("Check code quality", ["quality"])
        assert review_type == "quality_review"

    def test_identify_review_type_performance(self, agent: CodeReviewAgent):
        """Test identifying performance review type."""
        review_type = agent._identify_review_type("Optimize performance", [])
        assert review_type == "performance_review"

    def test_identify_review_type_comprehensive(self, agent: CodeReviewAgent):
        """Test identifying comprehensive review type."""
        review_type = agent._identify_review_type("Review code", ["security", "quality"])
        assert review_type == "comprehensive_review"

    def test_extract_issues(self, agent: CodeReviewAgent):
        """Test extracting issues from response."""
        response = "Vulnerability found: SQL injection risk\nIssue: Hardcoded password"
        issues = agent._extract_issues(response)

        assert len(issues) > 0
        assert any(
            "vulnerability" in str(issue).lower() or "issue" in str(issue).lower()
            for issue in issues
        )

    def test_extract_recommendations(self, agent: CodeReviewAgent):
        """Test extracting recommendations from response."""
        response = "Recommendation: Use parameterized queries\nShould consider: Input validation"
        recommendations = agent._extract_recommendations(response)

        assert len(recommendations) > 0
        assert any(
            "recommend" in str(rec).lower() or "suggest" in str(rec).lower()
            for rec in recommendations
        )
