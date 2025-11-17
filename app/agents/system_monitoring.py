"""System Monitoring Agent for system resource monitoring."""

from typing import Dict, Any, Optional
from app.agents.base import BaseAgent
from app.models.agent import AgentResult
from app.llm.base import LLMProvider


class SystemMonitoringAgent(BaseAgent):
    """Agent specialized in system resource monitoring."""

    def __init__(self, llm_provider: LLMProvider):
        """
        Initialize the System Monitoring Agent.

        Args:
            llm_provider: LLM provider instance
        """
        super().__init__(
            agent_id="system_monitoring",
            name="System Monitoring Agent",
            description="Monitors system resources including CPU, memory, disk usage, and processes",
            llm_provider=llm_provider,
            capabilities=[
                "cpu_monitoring",
                "memory_monitoring",
                "disk_usage",
                "process_management",
                "system_health"
            ]
        )

    async def execute(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None
    ) -> AgentResult:
        """
        Execute a system monitoring task.

        Args:
            task: System monitoring task description
            context: Optional context (e.g., target system, metrics to monitor)

        Returns:
            AgentResult with monitoring results
        """
        try:
            context = context or {}
            
            # Collect system metrics (simulated - in production, would use actual system APIs)
            metrics = self._collect_metrics(context)
            
            # Use dynamic prompt generation
            from app.core.prompt_generator import get_prompt_generator
            prompt_gen = get_prompt_generator()
            
            # Add metrics to context for prompt generation
            enhanced_context = {**context, "metrics": metrics}
            prompts = prompt_gen.generate_agent_prompt(
                agent_id=self.agent_id,
                task=task,
                context=enhanced_context
            )
            system_prompt = prompts["system_prompt"]
            user_prompt = prompts["user_prompt"]
            
            # Generate response using LLM
            response = await self._generate_response(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.3  # Lower temperature for more focused technical responses
            )
            
            # Format output
            output = {
                "summary": response[:200] + "..." if len(response) > 200 else response,
                "full_analysis": response,
                "monitoring_type": self._identify_monitoring_type(task),
                "metrics_collected": metrics,
                "context_used": context
            }
            
            return self._format_result(
                success=True,
                output=output,
                metadata={
                    "agent_id": self.agent_id,
                    "task": task,
                    "context_keys": list(context.keys()) if context else [],
                    "metrics_count": len(metrics) if metrics else 0
                }
            )
            
        except Exception as e:
            return self._format_result(
                success=False,
                output={},
                error=f"System monitoring failed: {str(e)}",
                metadata={
                    "agent_id": self.agent_id,
                    "task": task
                }
            )
    
    def _collect_metrics(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Collect system metrics (simulated for MVP).
        
        In production, this would use actual system APIs like psutil.
        
        Args:
            context: Context information
            
        Returns:
            Dictionary of system metrics
        """
        # Simulated metrics - in production, use psutil or similar
        import platform
        import os
        
        metrics = {
            "platform": platform.system(),
            "platform_version": platform.version(),
            "cpu_count": os.cpu_count() or "unknown",
            "hostname": platform.node()
        }
        
        # Add context-provided metrics if available
        if "cpu_usage" in context:
            metrics["cpu_usage_percent"] = context["cpu_usage"]
        if "memory_usage" in context:
            metrics["memory_usage_percent"] = context["memory_usage"]
        if "disk_usage" in context:
            metrics["disk_usage_percent"] = context["disk_usage"]
        
        return metrics
    
    def _identify_monitoring_type(self, task: str) -> str:
        """Identify the type of system monitoring needed."""
        task_lower = task.lower()
        
        if any(keyword in task_lower for keyword in ['cpu', 'processor', 'load']):
            return "cpu_monitoring"
        elif any(keyword in task_lower for keyword in ['memory', 'ram', 'swap']):
            return "memory_monitoring"
        elif any(keyword in task_lower for keyword in ['disk', 'storage', 'space']):
            return "disk_monitoring"
        elif any(keyword in task_lower for keyword in ['process', 'service', 'application']):
            return "process_monitoring"
        elif any(keyword in task_lower for keyword in ['health', 'status', 'overall']):
            return "system_health"
        else:
            return "general_monitoring"

