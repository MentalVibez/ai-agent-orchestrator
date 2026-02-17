"""Orchestrator engine for coordinating agent execution and workflows."""

import time
from typing import Any, Dict, List, Optional

from app.models.agent import AgentResult
from app.models.workflow import WorkflowResult


class Orchestrator:
    """Coordinates agent execution and workflow management."""

    def __init__(self, agent_registry: Any):
        """
        Initialize the orchestrator.

        Args:
            agent_registry: Instance of AgentRegistry for managing agents
        """
        self.agent_registry = agent_registry

    async def route_task(self, task: str, context: Optional[Dict[str, Any]] = None) -> AgentResult:
        """
        Route a task to the appropriate agent(s).

        Args:
            task: Description of the task to be executed
            context: Optional context information for the task

        Returns:
            AgentResult containing the execution results
        """
        if not task or not task.strip():
            return AgentResult(
                agent_id="orchestrator",
                agent_name="Orchestrator",
                success=False,
                output={},
                error="Task description is required",
            )

        context = context or {}
        task_lower = task.lower()

        # Simple keyword-based routing (can be enhanced with LLM-based routing)
        selected_agent = None

        # Network diagnostics keywords
        network_keywords = [
            "network",
            "connectivity",
            "ping",
            "dns",
            "latency",
            "route",
            "traceroute",
            "port",
        ]
        if any(keyword in task_lower for keyword in network_keywords):
            selected_agent = self.agent_registry.get("network_diagnostics")

        # System monitoring keywords
        system_keywords = ["system", "monitor", "cpu", "memory", "disk", "performance", "load"]
        if not selected_agent and any(keyword in task_lower for keyword in system_keywords):
            selected_agent = self.agent_registry.get("system_monitoring")

        # Log analysis keywords
        log_keywords = ["log", "error", "exception", "debug", "trace", "troubleshoot"]
        if not selected_agent and any(keyword in task_lower for keyword in log_keywords):
            selected_agent = self.agent_registry.get("log_analysis")

        # Infrastructure keywords
        infra_keywords = ["infrastructure", "deploy", "server", "configure", "setup", "provision"]
        if not selected_agent and any(keyword in task_lower for keyword in infra_keywords):
            selected_agent = self.agent_registry.get("infrastructure")

        # Code review keywords
        code_review_keywords = [
            "code review",
            "security review",
            "vulnerability",
            "code quality",
            "static analysis",
            "audit code",
        ]
        if not selected_agent and any(keyword in task_lower for keyword in code_review_keywords):
            selected_agent = self.agent_registry.get("code_review")

        # If no specific agent found, try to find by capability
        if not selected_agent:
            # Try to find any agent that might handle this
            all_agents = self.agent_registry.get_all()
            if all_agents:
                # Default to first available agent (can be enhanced)
                selected_agent = all_agents[0]

        # Execute the selected agent with sandboxing
        if selected_agent:
            try:
                from app.core.resource_limits import get_limits_for_agent
                from app.core.sandbox import get_sandbox

                sandbox = get_sandbox()
                limits = get_limits_for_agent(selected_agent.agent_id)

                # Create or get execution context
                exec_context = sandbox.get_context(selected_agent.agent_id)
                if not exec_context:
                    exec_context = sandbox.create_context(
                        agent_id=selected_agent.agent_id, resource_limits=limits
                    )

                # Execute with sandbox limits
                start_time = time.time()
                with sandbox.execute_with_limits(selected_agent.agent_id, "execute"):
                    result = await selected_agent.execute(task, context)

                    # Save execution history
                    try:
                        from app.core.persistence import save_execution_history

                        execution_time_ms = (time.time() - start_time) * 1000
                        save_execution_history(result, execution_time_ms=execution_time_ms)
                    except Exception as e:
                        # Log but don't fail on persistence errors
                        import logging

                        logging.getLogger(__name__).warning(
                            f"Failed to save execution history: {str(e)}"
                        )

                    return result
            except Exception as e:
                return AgentResult(
                    agent_id="orchestrator",
                    agent_name="Orchestrator",
                    success=False,
                    output={},
                    error=f"Agent execution failed: {str(e)}",
                    metadata={"selected_agent": selected_agent.agent_id},
                )
        else:
            # No agent available
            return AgentResult(
                agent_id="orchestrator",
                agent_name="Orchestrator",
                success=False,
                output={},
                error="No suitable agent found to handle this task",
                metadata={"task": task, "available_agents": self.agent_registry.list_agents()},
            )

    async def execute_workflow(
        self, workflow_id: str, input_data: Optional[Dict[str, Any]] = None
    ) -> WorkflowResult:
        """
        Execute a predefined workflow.

        Args:
            workflow_id: Identifier of the workflow to execute
            input_data: Optional input data for the workflow

        Returns:
            WorkflowResult containing the workflow execution results
        """
        # TODO: Implement workflow execution logic
        # 1. Load workflow definition
        # 2. Execute workflow steps in order
        # 3. Handle step dependencies and data passing
        # 4. Aggregate results from all steps
        # 5. Return workflow result
        raise NotImplementedError("execute_workflow method must be implemented")

    async def coordinate_agents(
        self, agent_ids: List[str], task: str, context: Optional[Dict[str, Any]] = None
    ) -> List[AgentResult]:
        """
        Coordinate multiple agents to work on a task.

        Args:
            agent_ids: List of agent identifiers to coordinate
            task: Task description
            context: Optional context information

        Returns:
            List of AgentResult objects from each agent
        """
        if not agent_ids:
            return []

        context = context or {}
        results = []

        # Retrieve agents from registry
        agents = []
        for agent_id in agent_ids:
            agent = self.agent_registry.get(agent_id)
            if agent:
                agents.append(agent)
            else:
                # Create error result for missing agent
                results.append(
                    AgentResult(
                        agent_id=agent_id,
                        agent_name=f"Unknown Agent ({agent_id})",
                        success=False,
                        output={},
                        error=f"Agent '{agent_id}' not found in registry",
                    )
                )

        # Execute agents sequentially (can be enhanced to run in parallel)
        for agent in agents:
            try:
                from app.core.resource_limits import get_limits_for_agent
                from app.core.sandbox import get_sandbox

                sandbox = get_sandbox()
                limits = get_limits_for_agent(agent.agent_id)

                # Create or get execution context
                exec_context = sandbox.get_context(agent.agent_id)
                if not exec_context:
                    exec_context = sandbox.create_context(
                        agent_id=agent.agent_id, resource_limits=limits
                    )

                # Pass previous results as context for subsequent agents
                if results:
                    context["previous_results"] = [
                        {
                            "agent_id": r.agent_id,
                            "success": r.success,
                            "summary": str(r.output)[:200] if r.output else None,
                        }
                        for r in results
                    ]

                # Execute with sandbox limits
                start_time = time.time()
                with sandbox.execute_with_limits(agent.agent_id, "execute"):
                    result = await agent.execute(task, context)

                    # Save execution history
                    try:
                        from app.core.persistence import save_execution_history

                        execution_time_ms = (time.time() - start_time) * 1000
                        save_execution_history(result, execution_time_ms=execution_time_ms)
                    except Exception as e:
                        # Log but don't fail on persistence errors
                        import logging

                        logging.getLogger(__name__).warning(
                            f"Failed to save execution history: {str(e)}"
                        )

                    results.append(result)
            except Exception as e:
                results.append(
                    AgentResult(
                        agent_id=agent.agent_id,
                        agent_name=agent.name,
                        success=False,
                        output={},
                        error=f"Agent execution failed: {str(e)}",
                    )
                )

        return results
