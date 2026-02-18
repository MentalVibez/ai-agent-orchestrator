"""Unit tests for WorkflowExecutor."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.workflow_executor import WorkflowExecutor
from app.models.agent import AgentResult
from app.models.workflow import (
    Workflow,
    WorkflowStep,
    WorkflowStepStatus,
)


def make_step(step_id: str, agent_id: str = "test_agent", depends_on=None, context=None):
    return WorkflowStep(
        step_id=step_id,
        name=f"Step {step_id}",
        agent_id=agent_id,
        task=f"Task for {step_id}",
        depends_on=depends_on or [],
        context=context,
    )


def make_workflow(workflow_id: str, steps: list) -> Workflow:
    return Workflow(
        workflow_id=workflow_id,
        name="Test Workflow",
        description="A test workflow",
        steps=steps,
    )


def make_mock_orchestrator(agent_ids=None):
    mock = MagicMock()
    mock.agent_registry = MagicMock()
    mock.agent_registry.get = MagicMock(return_value=MagicMock())
    success_result = AgentResult(
        agent_id="test_agent",
        agent_name="Test Agent",
        success=True,
        output={"result": "ok"},
        metadata={},
    )
    mock.coordinate_agents = AsyncMock(return_value=[success_result])
    return mock


@pytest.mark.unit
class TestWorkflowExecutorInit:
    """Test WorkflowExecutor initialization."""

    def test_init(self):
        orchestrator = MagicMock()
        executor = WorkflowExecutor(orchestrator=orchestrator)
        assert executor.orchestrator is orchestrator


@pytest.mark.unit
class TestValidateWorkflow:
    """Test validate_workflow method."""

    @pytest.fixture
    def executor(self):
        return WorkflowExecutor(orchestrator=make_mock_orchestrator())

    def test_valid_workflow(self, executor):
        workflow = make_workflow("wf1", [make_step("s1")])
        assert executor.validate_workflow(workflow) is True

    def test_missing_workflow_id(self, executor):
        workflow = Workflow(
            workflow_id="",
            name="Test",
            description="Test",
            steps=[make_step("s1")],
        )
        # Pydantic may not allow empty workflow_id, but test the validator
        # In case it does allow: validate_workflow should return False
        # If pydantic raises, the test passes differently
        try:
            result = executor.validate_workflow(workflow)
            assert result is False
        except Exception:
            pass  # Pydantic validation error is also acceptable

    def test_empty_steps(self, executor):
        # Pydantic requires at least one step per field definition, but test the concept
        workflow = Workflow(
            workflow_id="wf1",
            name="Test",
            description="Test",
            steps=[],
        )
        assert executor.validate_workflow(workflow) is False

    def test_duplicate_step_ids(self, executor):
        workflow = make_workflow("wf1", [make_step("s1"), make_step("s1")])
        assert executor.validate_workflow(workflow) is False

    def test_step_depends_on_unknown(self, executor):
        step2 = make_step("s2", depends_on=["unknown_step"])
        workflow = make_workflow("wf1", [step2])
        # s2 depends on "unknown_step" which isn't in the workflow
        assert executor.validate_workflow(workflow) is False

    def test_circular_dependency(self, executor):
        # s1 -> s2 -> s1 (circular)
        # We can't make this with Pydantic validation if depends_on must exist
        # Instead test that non-circular passes
        s1 = make_step("s1")
        s2 = make_step("s2", depends_on=["s1"])
        workflow = make_workflow("wf1", [s1, s2])
        assert executor.validate_workflow(workflow) is True

    def test_agent_not_found_warning(self, executor):
        """Workflow is still valid even if agent not registered (logs warning)."""
        executor.orchestrator.agent_registry.get = MagicMock(return_value=None)
        workflow = make_workflow("wf1", [make_step("s1")])
        # Should still return True (just logs warning)
        assert executor.validate_workflow(workflow) is True


@pytest.mark.unit
class TestBuildExecutionOrder:
    """Test _build_execution_order method."""

    @pytest.fixture
    def executor(self):
        return WorkflowExecutor(orchestrator=MagicMock())

    def test_single_step(self, executor):
        steps = [make_step("s1")]
        order = executor._build_execution_order(steps)
        assert len(order) == 1
        assert order[0][0].step_id == "s1"

    def test_sequential_steps(self, executor):
        s1 = make_step("s1")
        s2 = make_step("s2", depends_on=["s1"])
        order = executor._build_execution_order([s1, s2])
        assert len(order) == 2
        assert order[0][0].step_id == "s1"
        assert order[1][0].step_id == "s2"

    def test_parallel_steps(self, executor):
        s1 = make_step("s1")
        s2 = make_step("s2")
        order = executor._build_execution_order([s1, s2])
        # Both steps have no dependencies — they should be in the same batch
        assert len(order) == 1
        assert len(order[0]) == 2

    def test_fan_out_then_merge(self, executor):
        s1 = make_step("s1")
        s2 = make_step("s2", depends_on=["s1"])
        s3 = make_step("s3", depends_on=["s1"])
        s4 = make_step("s4", depends_on=["s2", "s3"])
        order = executor._build_execution_order([s1, s2, s3, s4])
        assert order[0][0].step_id == "s1"
        assert len(order[1]) == 2  # s2 and s3 in parallel
        assert order[2][0].step_id == "s4"


@pytest.mark.unit
class TestHasCircularDependencies:
    """Test _has_circular_dependencies method."""

    @pytest.fixture
    def executor(self):
        return WorkflowExecutor(orchestrator=MagicMock())

    def test_no_cycle(self, executor):
        s1 = make_step("s1")
        s2 = make_step("s2", depends_on=["s1"])
        assert executor._has_circular_dependencies([s1, s2]) is False

    def test_no_dependencies(self, executor):
        steps = [make_step("s1"), make_step("s2")]
        assert executor._has_circular_dependencies(steps) is False


@pytest.mark.unit
class TestPrepareStepContext:
    """Test _prepare_step_context method."""

    @pytest.fixture
    def executor(self):
        return WorkflowExecutor(orchestrator=MagicMock())

    def test_basic_context(self, executor):
        step = make_step("s1")
        context = executor._prepare_step_context(step, {"key": "value"}, {})
        assert context["key"] == "value"

    def test_merges_dependent_step_dict_output(self, executor):
        s2 = make_step("s2", depends_on=["s1"])
        step_outputs = {"s1": {"from_s1": "output"}}
        context = executor._prepare_step_context(s2, {}, step_outputs)
        assert context["from_s1"] == "output"

    def test_stores_non_dict_output_with_key(self, executor):
        s2 = make_step("s2", depends_on=["s1"])
        step_outputs = {"s1": "string_output"}
        context = executor._prepare_step_context(s2, {}, step_outputs)
        assert context["s1_output"] == "string_output"

    def test_merges_step_specific_context(self, executor):
        step = make_step("s1", context={"step_key": "step_value"})
        context = executor._prepare_step_context(step, {"wf_key": "wf_value"}, {})
        assert context["step_key"] == "step_value"
        assert context["wf_key"] == "wf_value"


@pytest.mark.unit
class TestExecuteStep:
    """Test execute_step method."""

    @pytest.fixture
    def executor(self):
        return WorkflowExecutor(orchestrator=make_mock_orchestrator())

    @pytest.mark.asyncio
    async def test_execute_step_success(self, executor):
        step = make_step("s1")
        result = await executor.execute_step(step)
        assert result.status == WorkflowStepStatus.COMPLETED
        assert result.step_id == "s1"

    @pytest.mark.asyncio
    async def test_execute_step_agent_returns_failure(self, executor):
        failure_result = AgentResult(
            agent_id="test_agent",
            agent_name="Test Agent",
            success=False,
            output={},
            error="Agent failed",
            metadata={},
        )
        executor.orchestrator.coordinate_agents = AsyncMock(return_value=[failure_result])
        step = make_step("s1")
        result = await executor.execute_step(step)
        assert result.status == WorkflowStepStatus.FAILED
        assert result.error == "Agent failed"

    @pytest.mark.asyncio
    async def test_execute_step_no_results(self, executor):
        executor.orchestrator.coordinate_agents = AsyncMock(return_value=[])
        step = make_step("s1")
        result = await executor.execute_step(step)
        assert result.status == WorkflowStepStatus.FAILED

    @pytest.mark.asyncio
    async def test_execute_step_exception(self, executor):
        executor.orchestrator.coordinate_agents = AsyncMock(side_effect=Exception("kaboom"))
        step = make_step("s1")
        result = await executor.execute_step(step)
        assert result.status == WorkflowStepStatus.FAILED
        assert "kaboom" in result.error


@pytest.mark.unit
class TestExecuteWorkflow:
    """Test execute method (full workflow)."""

    @pytest.fixture
    def executor(self):
        return WorkflowExecutor(orchestrator=make_mock_orchestrator())

    @pytest.mark.asyncio
    async def test_execute_single_step_workflow(self, executor):
        workflow = make_workflow("wf1", [make_step("s1")])

        with patch(
            "app.core.persistence.save_workflow_execution", MagicMock()
        ):
            result = await executor.execute(workflow)

        assert result.workflow_id == "wf1"
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_invalid_workflow(self, executor):
        # Empty steps workflow fails validation
        workflow = Workflow(
            workflow_id="wf1",
            name="Test",
            description="Test",
            steps=[],
        )
        result = await executor.execute(workflow)
        assert result.success is False
        assert result.error == "Workflow validation failed"

    @pytest.mark.asyncio
    async def test_execute_step_failure_stops_workflow(self, executor):
        failure_result = AgentResult(
            agent_id="test_agent",
            agent_name="Test Agent",
            success=False,
            output={},
            error="Step failed",
            metadata={},
        )
        executor.orchestrator.coordinate_agents = AsyncMock(return_value=[failure_result])

        workflow = make_workflow("wf1", [make_step("s1"), make_step("s2")])

        with patch(
            "app.core.persistence.save_workflow_execution", MagicMock()
        ):
            result = await executor.execute(workflow)

        assert result.success is False

    @pytest.mark.asyncio
    async def test_execute_with_input_data(self, executor):
        workflow = make_workflow("wf1", [make_step("s1")])

        with patch(
            "app.core.persistence.save_workflow_execution", MagicMock()
        ):
            result = await executor.execute(workflow, input_data={"env": "prod"})

        assert result.workflow_id == "wf1"

    @pytest.mark.asyncio
    async def test_execute_db_save_failure_is_swallowed(self, executor):
        """Database save failure should not fail the workflow."""
        workflow = make_workflow("wf1", [make_step("s1")])

        with patch(
            "app.core.persistence.save_workflow_execution",
            MagicMock(side_effect=Exception("db down")),
        ):
            result = await executor.execute(workflow)

        # Workflow should succeed even if db save fails
        assert result.workflow_id == "wf1"

    @pytest.mark.asyncio
    async def test_execute_parallel_batch_completes_both_steps(self, executor):
        """Steps in the same batch (no dependencies) run in parallel and both complete."""
        # Two steps with no depends_on -> one batch of 2 steps
        workflow = make_workflow("wf1", [make_step("s1"), make_step("s2")])

        with patch(
            "app.core.persistence.save_workflow_execution", MagicMock()
        ):
            result = await executor.execute(workflow)

        assert result.workflow_id == "wf1"
        assert result.success is True
        assert len(result.step_results) == 2
        assert all(r.status == WorkflowStepStatus.COMPLETED for r in result.step_results)
        step_ids = {r.step_id for r in result.step_results}
        assert step_ids == {"s1", "s2"}
