"""Unit tests for Prompt Generator."""

import pytest

from app.core.prompt_generator import PromptGenerator, get_prompt_generator


@pytest.mark.unit
class TestPromptGenerator:
    """Test cases for PromptGenerator."""

    @pytest.fixture
    def prompt_gen(self):
        """Create a prompt generator instance."""
        return PromptGenerator()

    def test_initialization(self, prompt_gen: PromptGenerator):
        """Test prompt generator initialization."""
        assert prompt_gen._tool_registry is not None

    def test_generate_agent_prompt_basic(self, prompt_gen: PromptGenerator):
        """Test generating basic agent prompt."""
        prompts = prompt_gen.generate_agent_prompt(
            agent_id="network_diagnostics", task="Check connectivity"
        )

        assert "system_prompt" in prompts
        assert "user_prompt" in prompts
        assert "Check connectivity" in prompts["user_prompt"]

    def test_generate_agent_prompt_with_context(self, prompt_gen: PromptGenerator):
        """Test generating prompt with context."""
        context = {"hostname": "example.com", "port": 443}
        prompts = prompt_gen.generate_agent_prompt(
            agent_id="network_diagnostics", task="Check connectivity", context=context
        )

        assert "example.com" in prompts["user_prompt"] or "443" in prompts["user_prompt"]

    def test_generate_agent_prompt_with_project_analysis(self, prompt_gen: PromptGenerator):
        """Test generating prompt with project analysis."""
        project_analysis = {"technologies": ["Python", "FastAPI"], "framework": "FastAPI"}
        prompts = prompt_gen.generate_agent_prompt(
            agent_id="code_review", task="Review code", project_analysis=project_analysis
        )

        assert "Python" in prompts["system_prompt"] or "FastAPI" in prompts["system_prompt"]

    def test_generate_agent_prompt_with_previous_results(self, prompt_gen: PromptGenerator):
        """Test generating prompt with previous results."""
        previous_results = [
            {"agent_id": "network_diagnostics", "success": True, "summary": "Network OK"}
        ]
        prompts = prompt_gen.generate_agent_prompt(
            agent_id="system_monitoring", task="Monitor system", previous_results=previous_results
        )

        assert (
            "Previous" in prompts["user_prompt"] or "network_diagnostics" in prompts["user_prompt"]
        )

    def test_generate_system_prompt_network_diagnostics(self, prompt_gen: PromptGenerator):
        """Test generating system prompt for network diagnostics."""
        prompt = prompt_gen._generate_system_prompt("network_diagnostics", {}, {})

        assert "network" in prompt.lower()
        assert "diagnostic" in prompt.lower() or "connectivity" in prompt.lower()

    def test_generate_system_prompt_system_monitoring(self, prompt_gen: PromptGenerator):
        """Test generating system prompt for system monitoring."""
        prompt = prompt_gen._generate_system_prompt("system_monitoring", {}, {})

        assert "system" in prompt.lower() or "monitor" in prompt.lower()

    def test_generate_system_prompt_code_review(self, prompt_gen: PromptGenerator):
        """Test generating system prompt for code review."""
        prompt = prompt_gen._generate_system_prompt("code_review", {}, {})

        assert "code" in prompt.lower() or "review" in prompt.lower()
        assert "security" in prompt.lower() or "quality" in prompt.lower()

    def test_generate_system_prompt_with_security_focus(self, prompt_gen: PromptGenerator):
        """Test generating system prompt with security focus."""
        context = {"security_focus": True}
        prompt = prompt_gen._generate_system_prompt("code_review", context, {})

        assert "security" in prompt.lower()

    def test_generate_system_prompt_with_performance_focus(self, prompt_gen: PromptGenerator):
        """Test generating system prompt with performance focus."""
        context = {"performance_focus": True}
        prompt = prompt_gen._generate_system_prompt("code_review", context, {})

        assert "performance" in prompt.lower()

    def test_generate_user_prompt_basic(self, prompt_gen: PromptGenerator):
        """Test generating basic user prompt."""
        prompt = prompt_gen._generate_user_prompt(
            "network_diagnostics", "Check connectivity", {}, {}, []
        )

        assert "Check connectivity" in prompt
        assert "Task:" in prompt

    def test_generate_user_prompt_with_context(self, prompt_gen: PromptGenerator):
        """Test generating user prompt with context."""
        context = {"hostname": "example.com", "port": 443}
        prompt = prompt_gen._generate_user_prompt("network_diagnostics", "Check", context, {}, [])

        assert "Context" in prompt or "example.com" in prompt

    def test_generate_user_prompt_code_review_specific(self, prompt_gen: PromptGenerator):
        """Test generating code review specific user prompt."""
        prompt = prompt_gen._generate_user_prompt("code_review", "Review code", {}, {}, [])

        assert "vulnerability" in prompt.lower() or "security" in prompt.lower()
        assert "recommendation" in prompt.lower() or "priority" in prompt.lower()

    def test_generate_workflow_prompt(self, prompt_gen: PromptGenerator):
        """Test generating workflow prompt."""
        workflow_context = {"input": "test"}
        step_outputs = {"step1": {"result": "ok"}}

        prompts = prompt_gen.generate_workflow_prompt(
            workflow_id="test_workflow",
            step_id="step2",
            task="Execute step",
            workflow_context=workflow_context,
            step_outputs=step_outputs,
        )

        assert "system_prompt" in prompts
        assert "user_prompt" in prompts

    def test_enhance_prompt_with_tools(self, prompt_gen: PromptGenerator):
        """Test enhancing prompt with tools."""
        prompt = "Base prompt"
        enhanced = prompt_gen.enhance_prompt_with_tools(
            prompt, "code_review", ["file_read", "code_search"]
        )

        assert "file_read" in enhanced or "code_search" in enhanced
        assert "Tools" in enhanced or "tools" in enhanced

    def test_enhance_prompt_without_tools(self, prompt_gen: PromptGenerator):
        """Test enhancing prompt without tools."""
        prompt = "Base prompt"
        enhanced = prompt_gen.enhance_prompt_with_tools(prompt, "code_review", [])

        # Should not add tools section if no tools
        assert enhanced == prompt or "Tools" not in enhanced

    def test_get_prompt_generator_singleton(self):
        """Test that get_prompt_generator returns singleton."""
        gen1 = get_prompt_generator()
        gen2 = get_prompt_generator()

        assert gen1 is gen2
