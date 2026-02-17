"""Workflow executor for multi-step, multi-agent workflows."""

import logging
import time
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Set

from app.models.workflow import (
    Workflow,
    WorkflowResult,
    WorkflowStep,
    WorkflowStepResult,
    WorkflowStepStatus,
)

logger = logging.getLogger(__name__)


class WorkflowExecutor:
    """Executes multi-step workflows involving multiple agents."""

    def __init__(self, orchestrator: Any):
        """
        Initialize the workflow executor.

        Args:
            orchestrator: Orchestrator instance for agent coordination
        """
        self.orchestrator = orchestrator

    async def execute(
        self, workflow: Workflow, input_data: Optional[Dict[str, Any]] = None
    ) -> WorkflowResult:
        """
        Execute a workflow.

        Args:
            workflow: Workflow definition to execute
            input_data: Optional input data for the workflow

        Returns:
            WorkflowResult containing execution results
        """
        start_time = time.time()
        input_data = input_data or {}

        # Validate workflow
        if not self.validate_workflow(workflow):
            return WorkflowResult(
                workflow_id=workflow.workflow_id,
                success=False,
                step_results=[],
                error="Workflow validation failed",
                duration=0.0,
            )

        # Build dependency graph and execution order
        execution_order = self._build_execution_order(workflow.steps)

        # Track step results
        step_results: Dict[str, WorkflowStepResult] = {}
        step_outputs: Dict[str, Any] = {}
        workflow_context = input_data.copy()

        # Execute steps in order
        for step_batch in execution_order:
            for step in step_batch:
                try:
                    # Prepare context for this step
                    step_context = self._prepare_step_context(step, workflow_context, step_outputs)

                    # Execute step
                    step_result = await self.execute_step(step, step_context)
                    step_results[step.step_id] = step_result

                    # Store step output for subsequent steps
                    if step_result.status == WorkflowStepStatus.COMPLETED:
                        step_outputs[step.step_id] = step_result.agent_result
                        # Merge step output into workflow context
                        if isinstance(step_result.agent_result, dict):
                            workflow_context.update(step_result.agent_result)
                    elif step_result.status == WorkflowStepStatus.FAILED:
                        # Stop workflow on step failure (can be made configurable)
                        logger.error(f"Workflow step '{step.step_id}' failed: {step_result.error}")
                        break

                except Exception as e:
                    logger.error(f"Error executing workflow step '{step.step_id}': {str(e)}")
                    step_results[step.step_id] = WorkflowStepResult(
                        step_id=step.step_id,
                        status=WorkflowStepStatus.FAILED,
                        error=str(e),
                        timestamp=time.time(),
                    )
                    break

        # Aggregate results
        duration = time.time() - start_time
        all_step_results = [
            step_results.get(step.step_id)
            for step in workflow.steps
            if step.step_id in step_results
        ]
        success = all(
            result.status == WorkflowStepStatus.COMPLETED for result in all_step_results if result
        )

        # Save workflow execution to database
        try:
            from app.core.persistence import save_workflow_execution

            save_workflow_execution(
                workflow_id=workflow.workflow_id,
                input_data=input_data,
                output_data=workflow_context,
                status="completed" if success else "failed",
                error=None if success else "One or more steps failed",
                execution_time_ms=duration * 1000,
            )
        except Exception as e:
            logger.warning(f"Failed to save workflow execution: {str(e)}")

        return WorkflowResult(
            workflow_id=workflow.workflow_id,
            success=success,
            step_results=all_step_results,
            output=workflow_context,
            error=None if success else "Workflow execution failed",
            duration=duration,
        )

    async def execute_step(
        self, step: WorkflowStep, context: Optional[Dict[str, Any]] = None
    ) -> WorkflowStepResult:
        """
        Execute a single workflow step.

        Args:
            step: Workflow step definition
            context: Context data from previous steps

        Returns:
            WorkflowStepResult with step execution results
        """
        start_time = time.time()
        context = context or {}

        try:
            # Prepare task and context for agent
            task = step.task
            step_context = {**(step.context or {}), **context}

            # Execute agent via orchestrator
            agent_result = await self.orchestrator.coordinate_agents(
                agent_ids=[step.agent_id], task=task, context=step_context
            )

            # Get result from first agent (since we're using single agent per step)
            if agent_result and len(agent_result) > 0:
                result = agent_result[0]
                duration = time.time() - start_time

                if result.success:
                    return WorkflowStepResult(
                        step_id=step.step_id,
                        status=WorkflowStepStatus.COMPLETED,
                        agent_result=result.output,
                        error=None,
                        duration=duration,
                    )
                else:
                    return WorkflowStepResult(
                        step_id=step.step_id,
                        status=WorkflowStepStatus.FAILED,
                        agent_result=None,
                        error=result.error,
                        duration=duration,
                    )
            else:
                return WorkflowStepResult(
                    step_id=step.step_id,
                    status=WorkflowStepStatus.FAILED,
                    agent_result=None,
                    error="No agent result returned",
                    duration=time.time() - start_time,
                )

        except Exception as e:
            logger.error(f"Error executing step '{step.step_id}': {str(e)}")
            return WorkflowStepResult(
                step_id=step.step_id,
                status=WorkflowStepStatus.FAILED,
                agent_result=None,
                error=str(e),
                duration=time.time() - start_time,
            )

    def validate_workflow(self, workflow: Workflow) -> bool:
        """
        Validate a workflow definition.

        Args:
            workflow: Workflow definition to validate

        Returns:
            True if workflow is valid, False otherwise
        """
        if not workflow.workflow_id:
            logger.error("Workflow missing workflow_id")
            return False

        if not workflow.steps or len(workflow.steps) == 0:
            logger.error(f"Workflow '{workflow.workflow_id}' has no steps")
            return False

        # Validate steps
        step_ids = set()
        for step in workflow.steps:
            if not step.step_id:
                logger.error("Step missing step_id")
                return False

            if step.step_id in step_ids:
                logger.error(f"Duplicate step_id: {step.step_id}")
                return False
            step_ids.add(step.step_id)

            if not step.agent_id:
                logger.error(f"Step '{step.step_id}' missing agent_id")
                return False

            # Validate dependencies
            for dep in step.depends_on:
                if dep not in step_ids:
                    logger.error(f"Step '{step.step_id}' depends on unknown step '{dep}'")
                    return False

        # Check for circular dependencies
        if self._has_circular_dependencies(workflow.steps):
            logger.error(f"Workflow '{workflow.workflow_id}' has circular dependencies")
            return False

        # Verify agent availability
        agent_registry = self.orchestrator.agent_registry
        for step in workflow.steps:
            agent = agent_registry.get(step.agent_id)
            if not agent:
                logger.warning(f"Agent '{step.agent_id}' not found in registry (step may fail)")

        return True

    def _build_execution_order(self, steps: List[WorkflowStep]) -> List[List[WorkflowStep]]:
        """
        Build execution order based on dependencies.

        Args:
            steps: List of workflow steps

        Returns:
            List of step batches (steps in each batch can run in parallel)
        """
        # Build dependency graph
        in_degree = {step.step_id: len(step.depends_on) for step in steps}
        step_map = {step.step_id: step for step in steps}
        dependencies = defaultdict(list)

        for step in steps:
            for dep in step.depends_on:
                dependencies[dep].append(step.step_id)

        # Topological sort
        execution_order = []
        queue = deque([step_id for step_id, degree in in_degree.items() if degree == 0])

        while queue:
            batch = []
            batch_size = len(queue)

            for _ in range(batch_size):
                step_id = queue.popleft()
                batch.append(step_map[step_id])

                # Update in-degree for dependent steps
                for dependent_id in dependencies[step_id]:
                    in_degree[dependent_id] -= 1
                    if in_degree[dependent_id] == 0:
                        queue.append(dependent_id)

            if batch:
                execution_order.append(batch)

        # Check for remaining steps (circular dependency)
        if any(in_degree[step.step_id] > 0 for step in steps):
            logger.error("Circular dependency detected in workflow")
            # Return all steps as single batch (will fail but won't hang)
            return [steps]

        return execution_order

    def _has_circular_dependencies(self, steps: List[WorkflowStep]) -> bool:
        """Check for circular dependencies using DFS."""
        step_map = {step.step_id: step for step in steps}
        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def has_cycle(step_id: str) -> bool:
            visited.add(step_id)
            rec_stack.add(step_id)

            step = step_map[step_id]
            for dep in step.depends_on:
                if dep not in visited:
                    if has_cycle(dep):
                        return True
                elif dep in rec_stack:
                    return True

            rec_stack.remove(step_id)
            return False

        for step in steps:
            if step.step_id not in visited:
                if has_cycle(step.step_id):
                    return True

        return False

    def _prepare_step_context(
        self, step: WorkflowStep, workflow_context: Dict[str, Any], step_outputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Prepare context for a workflow step.

        Args:
            step: Workflow step
            workflow_context: Overall workflow context
            step_outputs: Outputs from previous steps

        Returns:
            Prepared context dictionary
        """
        context = workflow_context.copy()

        # Add outputs from dependent steps
        for dep_id in step.depends_on:
            if dep_id in step_outputs:
                dep_output = step_outputs[dep_id]
                if isinstance(dep_output, dict):
                    context.update(dep_output)
                else:
                    context[f"{dep_id}_output"] = dep_output

        # Merge step-specific context
        if step.context:
            context.update(step.context)

        return context
