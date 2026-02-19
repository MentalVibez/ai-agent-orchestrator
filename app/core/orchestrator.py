"""Orchestrator engine for coordinating agent execution and workflows."""

import asyncio
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from app.models.agent import AgentResult

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    Coordinates agent execution.

    Workflow execution is handled by WorkflowExecutor and the POST /api/v1/workflows
    endpoint; this class does not implement workflow execution.
    """

    def __init__(self, agent_registry: Any, llm_manager: Optional[Any] = None):
        """
        Initialize the orchestrator.

        Args:
            agent_registry: Instance of AgentRegistry for managing agents
            llm_manager: Optional LLMManager for LLM-based routing when USE_LLM_ROUTING is True
        """
        self.agent_registry = agent_registry
        self._llm_manager = llm_manager

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
        selected_agent = None

        # Optional LLM-based routing
        from app.core.config import settings

        if getattr(settings, "use_llm_routing", False) and self._llm_manager:
            selected_agent = await self._try_llm_routing(task)
            if selected_agent is None:
                selected_agent = self._keyword_route(task_lower)
        else:
            selected_agent = self._keyword_route(task_lower)

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
                        await save_execution_history(result, execution_time_ms=execution_time_ms)
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

    def _keyword_route(self, task_lower: str) -> Optional[Any]:
        """Select an agent by keyword matching. Returns agent or None."""
        selected_agent = None
        network_keywords = [
            "network", "connectivity", "ping", "dns", "latency", "route", "traceroute", "port",
        ]
        if any(k in task_lower for k in network_keywords):
            selected_agent = self.agent_registry.get("network_diagnostics")
        system_keywords = ["system", "monitor", "cpu", "memory", "disk", "performance", "load"]
        if not selected_agent and any(k in task_lower for k in system_keywords):
            selected_agent = self.agent_registry.get("system_monitoring")
        log_keywords = ["log", "error", "exception", "debug", "trace", "troubleshoot"]
        if not selected_agent and any(k in task_lower for k in log_keywords):
            selected_agent = self.agent_registry.get("log_analysis")
        infra_keywords = ["infrastructure", "deploy", "server", "configure", "setup", "provision"]
        if not selected_agent and any(k in task_lower for k in infra_keywords):
            selected_agent = self.agent_registry.get("infrastructure")
        code_review_keywords = [
            "code review", "security review", "vulnerability", "code quality",
            "static analysis", "audit code",
        ]
        if not selected_agent and any(k in task_lower for k in code_review_keywords):
            selected_agent = self.agent_registry.get("code_review")
        if not selected_agent:
            all_agents = self.agent_registry.get_all()
            if all_agents:
                selected_agent = all_agents[0]
        return selected_agent

    async def _try_llm_routing(self, task: str) -> Optional[Any]:
        """Use LLM to pick an agent_id. Returns agent or None on failure/timeout."""
        from app.core.config import settings

        agents = self.agent_registry.get_all()
        if not agents:
            return None
        agent_list = "\n".join(
            f"- {a.agent_id}: {getattr(a, 'name', a.agent_id)}"
            for a in agents
        )
        prompt = (
            f"Given the user task below, choose the single best agent by ID. "
            f"Reply with exactly one JSON object: {{\"agent_id\": \"<id>\"}}. No other text.\n\n"
            f"Agents:\n{agent_list}\n\nUser task: {task[:500]}"
        )
        timeout = getattr(settings, "llm_routing_timeout_seconds", 10) or 10
        try:
            llm = self._llm_manager.get_provider()
            response = await asyncio.wait_for(
                llm.generate(prompt=prompt, system_prompt="You are a task router. Output only valid JSON."),
                timeout=float(timeout),
            )
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning("LLM routing failed, falling back to keyword: %s", e)
            return None
        # Parse JSON agent_id from response
        match = re.search(r"\{\s*[\"']agent_id[\"']\s*:\s*[\"']([^\"']+)[\"']\s*\}", response)
        if match:
            agent_id = match.group(1).strip()
            agent = self.agent_registry.get(agent_id)
            if agent:
                return agent
        try:
            data = json.loads(response.strip())
            agent_id = data.get("agent_id") if isinstance(data, dict) else None
            if agent_id:
                agent = self.agent_registry.get(agent_id)
                if agent:
                    return agent
        except json.JSONDecodeError:
            pass
        logger.warning("LLM routing returned invalid or unknown agent_id, falling back to keyword")
        return None

    async def coordinate_agents(
        self,
        agent_ids: List[str],
        task: str,
        context: Optional[Dict[str, Any]] = None,
        parallel: bool = False,
    ) -> List[AgentResult]:
        """
        Coordinate multiple agents to work on a task.

        Args:
            agent_ids: List of agent identifiers to coordinate
            task: Task description
            context: Optional context information
            parallel: If True, run all agents concurrently (no previous_results
                passed between them). If False (default), run sequentially and
                pass previous_results into each agent's context.

        Returns:
            List of AgentResult objects from each agent
        """
        if not agent_ids:
            return []

        context = context or {}

        # Retrieve agents from registry
        agents = []
        results: List[AgentResult] = []
        for agent_id in agent_ids:
            agent = self.agent_registry.get(agent_id)
            if agent:
                agents.append(agent)
            else:
                results.append(
                    AgentResult(
                        agent_id=agent_id,
                        agent_name=f"Unknown Agent ({agent_id})",
                        success=False,
                        output={},
                        error=f"Agent '{agent_id}' not found in registry",
                    )
                )

        if not agents:
            return results

        if parallel:
            # Run all agents concurrently; no previous_results between them
            parallel_results = await asyncio.gather(
                *[self._execute_single_agent(agent, task, context) for agent in agents],
                return_exceptions=True,
            )
            for i, r in enumerate(parallel_results):
                if isinstance(r, Exception):
                    results.append(
                        AgentResult(
                            agent_id=agents[i].agent_id,
                            agent_name=agents[i].name,
                            success=False,
                            output={},
                            error=f"Agent execution failed: {str(r)}",
                        )
                    )
                else:
                    results.append(r)
            return results

        # Sequential: pass previous_results into each subsequent agent's context
        for agent in agents:
            try:
                if results:
                    context = {**context, "previous_results": _summarize_results(results)}
                result = await self._execute_single_agent(agent, task, context)
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

    async def _execute_single_agent(
        self, agent: Any, task: str, context: Dict[str, Any]
    ) -> AgentResult:
        """Execute one agent with sandbox and persistence. Used by coordinate_agents."""
        import logging

        from app.core.persistence import save_execution_history
        from app.core.resource_limits import get_limits_for_agent
        from app.core.sandbox import get_sandbox

        logger = logging.getLogger(__name__)
        sandbox = get_sandbox()
        limits = get_limits_for_agent(agent.agent_id)
        exec_context = sandbox.get_context(agent.agent_id)
        if not exec_context:
            exec_context = sandbox.create_context(
                agent_id=agent.agent_id, resource_limits=limits
            )
        start_time = time.time()
        with sandbox.execute_with_limits(agent.agent_id, "execute"):
            result = await agent.execute(task, context)
        try:
            execution_time_ms = (time.time() - start_time) * 1000
            await save_execution_history(result, execution_time_ms=execution_time_ms)
        except Exception as e:
            logger.warning("Failed to save execution history: %s", e)
        return result


def _summarize_results(results: List[AgentResult]) -> List[Dict[str, Any]]:
    """Build previous_results summary for sequential coordinate_agents."""
    return [
        {
            "agent_id": r.agent_id,
            "success": r.success,
            "summary": str(r.output)[:200] if r.output else None,
        }
        for r in results
    ]
