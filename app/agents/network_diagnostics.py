"""Network Diagnostics Agent for network connectivity and routing issues."""

from typing import Any, Dict, Optional

from app.agents.base import BaseAgent
from app.llm.base import LLMProvider
from app.models.agent import AgentResult


class NetworkDiagnosticsAgent(BaseAgent):
    """Agent specialized in network diagnostics and troubleshooting."""

    def __init__(self, llm_provider: LLMProvider):
        """
        Initialize the Network Diagnostics Agent.

        Args:
            llm_provider: LLM provider instance
        """
        super().__init__(
            agent_id="network_diagnostics",
            name="Network Diagnostics Agent",
            description="Handles network connectivity, latency, routing, and DNS issues",
            llm_provider=llm_provider,
            capabilities=[
                "network_connectivity",
                "latency_analysis",
                "routing_diagnostics",
                "dns_resolution",
                "port_scanning",
            ],
        )

    async def execute(self, task: str, context: Optional[Dict[str, Any]] = None) -> AgentResult:
        """
        Execute a network diagnostics task.

        Args:
            task: Network diagnostics task description
            context: Optional context (e.g., hostname, IP address, port)

        Returns:
            AgentResult with diagnostics results
        """
        try:
            context = context or {}

            # Use dynamic prompt generation
            from app.core.prompt_generator import get_prompt_generator

            prompt_gen = get_prompt_generator()
            prompts = prompt_gen.generate_agent_prompt(
                agent_id=self.agent_id, task=task, context=context
            )
            system_prompt = prompts["system_prompt"]
            user_prompt = prompts["user_prompt"]

            # Generate response using LLM
            response = await self._generate_response(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.3,  # Lower temperature for more focused technical responses
            )

            # Format output
            output = {
                "summary": response[:200] + "..." if len(response) > 200 else response,
                "full_analysis": response,
                "diagnostic_type": self._identify_diagnostic_type(task),
                "context_used": context,
            }

            return self._format_result(
                success=True,
                output=output,
                metadata={
                    "agent_id": self.agent_id,
                    "task": task,
                    "context_keys": list(context.keys()) if context else [],
                },
            )

        except Exception as e:
            return self._format_result(
                success=False,
                output={},
                error=f"Network diagnostics failed: {str(e)}",
                metadata={"agent_id": self.agent_id, "task": task},
            )

    def _identify_diagnostic_type(self, task: str) -> str:
        """Identify the type of network diagnostic needed."""
        task_lower = task.lower()

        if any(keyword in task_lower for keyword in ["ping", "connectivity", "reachable"]):
            return "connectivity_check"
        elif any(keyword in task_lower for keyword in ["dns", "resolve", "domain"]):
            return "dns_resolution"
        elif any(keyword in task_lower for keyword in ["latency", "delay", "slow"]):
            return "latency_analysis"
        elif any(keyword in task_lower for keyword in ["route", "traceroute", "path"]):
            return "routing_analysis"
        elif any(keyword in task_lower for keyword in ["port", "scan", "firewall"]):
            return "port_analysis"
        else:
            return "general_diagnostics"
