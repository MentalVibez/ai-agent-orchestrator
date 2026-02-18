"""Dynamic prompt generation for context-aware agent prompts."""

import logging
from typing import Any, Dict, List, Optional

from app.core.tool_registry import get_tool_registry

logger = logging.getLogger(__name__)


class PromptGenerator:
    """Generates context-aware prompts for agents."""

    def __init__(self):
        """Initialize prompt generator."""
        self._tool_registry = get_tool_registry()

    def generate_agent_prompt(
        self,
        agent_id: str,
        task: str,
        context: Optional[Dict[str, Any]] = None,
        project_analysis: Optional[Dict[str, Any]] = None,
        previous_results: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, str]:
        """
        Generate context-aware prompts for an agent.

        Args:
            agent_id: Agent identifier
            task: Task description
            context: Optional context information
            project_analysis: Optional project analysis results
            previous_results: Optional results from previous agent executions

        Returns:
            Dictionary with 'system_prompt' and 'user_prompt'
        """
        context = context or {}
        project_analysis = project_analysis or {}
        previous_results = previous_results or []

        # Generate system prompt based on agent type
        system_prompt = self._generate_system_prompt(agent_id, context, project_analysis)

        # Generate user prompt with context
        user_prompt = self._generate_user_prompt(
            agent_id, task, context, project_analysis, previous_results
        )

        return {"system_prompt": system_prompt, "user_prompt": user_prompt}

    def _generate_system_prompt(
        self, agent_id: str, context: Dict[str, Any], project_analysis: Dict[str, Any]
    ) -> str:
        """Generate system prompt based on agent type and context."""

        # Base prompts for each agent type
        agent_prompts = {
            "network_diagnostics": """You are a network diagnostics expert. Analyze network connectivity issues,
provide diagnostic guidance, and suggest troubleshooting steps. Be specific and actionable.""",
            "system_monitoring": """You are a system monitoring expert. Analyze system resource metrics,
identify performance issues, and provide actionable recommendations. Be specific and technical.""",
            "code_review": """You are an expert code reviewer specializing in security analysis and code quality.
Analyze code for vulnerabilities, security issues, and quality problems. Provide specific, actionable recommendations.""",
            "log_analysis": """You are a log analysis expert. Analyze logs for errors, patterns, and anomalies.
Provide troubleshooting insights and recommendations.""",
            "infrastructure": """You are an infrastructure expert. Analyze infrastructure configurations,
provisioning needs, and deployment requirements. Provide specific recommendations.""",
        }

        base_prompt = agent_prompts.get(
            agent_id, "You are an expert assistant. Provide accurate and helpful responses."
        )

        # Enhance with project analysis if available
        if project_analysis:
            technologies = project_analysis.get("technologies", [])
            if technologies:
                base_prompt += f"\n\nProject Technologies: {', '.join(technologies)}"
                base_prompt += "\nTailor your analysis and recommendations to these technologies."

            framework = project_analysis.get("framework")
            if framework:
                base_prompt += f"\n\nPrimary Framework: {framework}"
                base_prompt += f"\nConsider {framework}-specific best practices and patterns."

        # Add context-specific enhancements
        if context.get("security_focus"):
            base_prompt += "\n\nSecurity Focus: Prioritize security vulnerabilities and risks in your analysis."

        if context.get("performance_focus"):
            base_prompt += "\n\nPerformance Focus: Prioritize performance bottlenecks and optimization opportunities."

        return base_prompt

    def _generate_user_prompt(
        self,
        agent_id: str,
        task: str,
        context: Dict[str, Any],
        project_analysis: Dict[str, Any],
        previous_results: List[Dict[str, Any]],
    ) -> str:
        """Generate user prompt with context and previous results."""

        prompt = f"Task: {task}\n\n"

        # Add context information
        if context:
            prompt += "Context Information:\n"
            for key, value in context.items():
                if key not in ["security_focus", "performance_focus"]:  # Already in system prompt
                    if isinstance(value, (str, int, float, bool)):
                        prompt += f"- {key}: {value}\n"
                    elif isinstance(value, list) and len(value) > 0:
                        prompt += f"- {key}: {', '.join(str(v) for v in value[:5])}\n"
            prompt += "\n"

        # Add project analysis if available
        if project_analysis:
            prompt += "Project Analysis:\n"

            if project_analysis.get("technologies"):
                prompt += f"Technologies: {', '.join(project_analysis['technologies'])}\n"

            if project_analysis.get("framework"):
                prompt += f"Framework: {project_analysis['framework']}\n"

            if project_analysis.get("structure"):
                prompt += f"Project Structure: {len(project_analysis['structure'])} files/directories analyzed\n"

            prompt += "\n"

        # Add previous results if available
        if previous_results:
            prompt += "Previous Analysis Results:\n"
            for i, result in enumerate(previous_results[:3], 1):  # Limit to 3 previous results
                agent_id_prev = result.get("agent_id", "unknown")
                success = result.get("success", False)
                summary = result.get("summary", str(result.get("output", ""))[:200])
                prompt += (
                    f"{i}. {agent_id_prev}: {'Success' if success else 'Failed'} - {summary}\n"
                )
            prompt += "\n"

        # Add agent-specific prompt enhancements
        if agent_id == "code_review":
            prompt += """Please provide:
1. Security vulnerabilities found (if any) with severity levels
2. Code quality issues
3. Specific recommendations with code examples
4. Priority levels (Critical, High, Medium, Low)
5. Best practices suggestions"""

        elif agent_id == "network_diagnostics":
            prompt += """Please provide:
1. Analysis of the network issue
2. Recommended diagnostic steps
3. Potential causes
4. Troubleshooting recommendations"""

        elif agent_id == "system_monitoring":
            prompt += """Please provide:
1. Analysis of system health and performance
2. Identification of any issues or anomalies
3. Resource utilization assessment
4. Recommendations for optimization or troubleshooting"""

        else:
            prompt += "Please provide a detailed analysis and actionable recommendations."

        return prompt

    def generate_workflow_prompt(
        self,
        workflow_id: str,
        step_id: str,
        task: str,
        workflow_context: Dict[str, Any],
        step_outputs: Dict[str, Any],
    ) -> Dict[str, str]:
        """
        Generate prompt for workflow step execution.

        Args:
            workflow_id: Workflow identifier
            step_id: Current step identifier
            task: Step task description
            workflow_context: Overall workflow context
            step_outputs: Outputs from previous steps

        Returns:
            Dictionary with 'system_prompt' and 'user_prompt'
        """
        # Build context from previous steps
        previous_results = []
        for step_id_prev, output in step_outputs.items():
            if isinstance(output, dict):
                previous_results.append(
                    {"agent_id": step_id_prev, "output": output, "success": True}
                )

        # Use standard prompt generation with workflow context
        return self.generate_agent_prompt(
            agent_id="",  # Will be determined by step
            task=task,
            context=workflow_context,
            previous_results=previous_results,
        )

    def enhance_prompt_with_tools(
        self, prompt: str, agent_id: str, available_tools: Optional[List[str]] = None
    ) -> str:
        """
        Enhance prompt with tool availability information.

        Args:
            prompt: Base prompt
            agent_id: Agent identifier
            available_tools: List of available tool IDs

        Returns:
            Enhanced prompt
        """
        if available_tools is None:
            tools = self._tool_registry.get_tools_for_agent(agent_id)
            available_tools = [tool.tool_id for tool in tools]

        if available_tools:
            prompt += f"\n\nAvailable Tools: {', '.join(available_tools)}"
            prompt += "\nYou can request tool usage if needed for deeper analysis."

        return prompt


# Global prompt generator instance
_prompt_generator: Optional[PromptGenerator] = None


def get_prompt_generator() -> PromptGenerator:
    """Get the global prompt generator instance."""
    global _prompt_generator
    if _prompt_generator is None:
        _prompt_generator = PromptGenerator()
    return _prompt_generator
