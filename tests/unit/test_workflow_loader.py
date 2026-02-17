"""Unit tests for Workflow Loader."""

import json
import tempfile
from pathlib import Path

import pytest
import yaml

from app.core.workflow_loader import WorkflowLoader, get_workflow_loader


@pytest.mark.unit
class TestWorkflowLoader:
    """Test cases for WorkflowLoader."""

    @pytest.fixture
    def temp_workflows_dir(self):
        """Create a temporary workflows directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def sample_workflow_data(self):
        """Sample workflow data."""
        return {
            "workflow_id": "test_workflow",
            "name": "Test Workflow",
            "description": "A test workflow",
            "enabled": True,
            "steps": [
                {
                    "step_id": "step1",
                    "agent_id": "network_diagnostics",
                    "task": "Check connectivity",
                    "depends_on": [],
                }
            ],
        }

    def test_initialization_default_dir(self):
        """Test initialization with default directory."""
        loader = WorkflowLoader()
        assert loader.workflows_dir is not None
        assert loader._workflows == {}

    def test_initialization_custom_dir(self, temp_workflows_dir):
        """Test initialization with custom directory."""
        loader = WorkflowLoader(workflows_dir=str(temp_workflows_dir))
        assert loader.workflows_dir == temp_workflows_dir

    def test_load_workflow_yaml(self, temp_workflows_dir, sample_workflow_data):
        """Test loading workflow from YAML file."""
        workflow_file = temp_workflows_dir / "test.yaml"
        with open(workflow_file, "w") as f:
            yaml.dump(sample_workflow_data, f)

        loader = WorkflowLoader(workflows_dir=str(temp_workflows_dir))
        workflow = loader.get_workflow("test_workflow")

        assert workflow is not None
        assert workflow.workflow_id == "test_workflow"

    def test_load_workflow_yml(self, temp_workflows_dir, sample_workflow_data):
        """Test loading workflow from .yml file."""
        workflow_file = temp_workflows_dir / "test.yml"
        with open(workflow_file, "w") as f:
            yaml.dump(sample_workflow_data, f)

        loader = WorkflowLoader(workflows_dir=str(temp_workflows_dir))
        workflow = loader.get_workflow("test_workflow")

        assert workflow is not None

    def test_load_workflow_json(self, temp_workflows_dir, sample_workflow_data):
        """Test loading workflow from JSON file."""
        workflow_file = temp_workflows_dir / "test.json"
        with open(workflow_file, "w") as f:
            json.dump(sample_workflow_data, f)

        loader = WorkflowLoader(workflows_dir=str(temp_workflows_dir))
        workflow = loader.get_workflow("test_workflow")

        assert workflow is not None

    def test_load_workflow_nonexistent_dir(self):
        """Test loading from non-existent directory."""
        loader = WorkflowLoader(workflows_dir="/nonexistent/path")
        workflows = loader.list_workflows()

        assert workflows == {}

    def test_get_workflow_exists(self, temp_workflows_dir, sample_workflow_data):
        """Test getting existing workflow."""
        workflow_file = temp_workflows_dir / "test.yaml"
        with open(workflow_file, "w") as f:
            yaml.dump(sample_workflow_data, f)

        loader = WorkflowLoader(workflows_dir=str(temp_workflows_dir))
        workflow = loader.get_workflow("test_workflow")

        assert workflow is not None
        assert workflow.workflow_id == "test_workflow"

    def test_get_workflow_not_exists(self, temp_workflows_dir):
        """Test getting non-existent workflow."""
        loader = WorkflowLoader(workflows_dir=str(temp_workflows_dir))
        workflow = loader.get_workflow("nonexistent")

        assert workflow is None

    def test_list_workflows(self, temp_workflows_dir, sample_workflow_data):
        """Test listing all workflows."""
        workflow_file = temp_workflows_dir / "test.yaml"
        with open(workflow_file, "w") as f:
            yaml.dump(sample_workflow_data, f)

        loader = WorkflowLoader(workflows_dir=str(temp_workflows_dir))
        workflows = loader.list_workflows()

        assert len(workflows) == 1
        assert "test_workflow" in workflows

    def test_list_workflows_empty(self, temp_workflows_dir):
        """Test listing workflows when none exist."""
        loader = WorkflowLoader(workflows_dir=str(temp_workflows_dir))
        workflows = loader.list_workflows()

        assert workflows == {}

    def test_reload_workflows(self, temp_workflows_dir, sample_workflow_data):
        """Test reloading workflows."""
        workflow_file = temp_workflows_dir / "test.yaml"
        with open(workflow_file, "w") as f:
            yaml.dump(sample_workflow_data, f)

        loader = WorkflowLoader(workflows_dir=str(temp_workflows_dir))
        assert len(loader.list_workflows()) == 1

        # Clear and reload
        loader.reload()
        assert len(loader.list_workflows()) == 1

    def test_load_workflow_invalid_file(self, temp_workflows_dir):
        """Test loading invalid workflow file."""
        invalid_file = temp_workflows_dir / "invalid.yaml"
        invalid_file.write_text("invalid: yaml: content: [")

        loader = WorkflowLoader(workflows_dir=str(temp_workflows_dir))
        workflow = loader.get_workflow("invalid")

        # Should handle error gracefully
        assert workflow is None or len(loader.list_workflows()) == 0

    def test_load_workflow_unsupported_format(self, temp_workflows_dir):
        """Test loading unsupported file format."""
        invalid_file = temp_workflows_dir / "test.xml"
        invalid_file.write_text("<workflow></workflow>")

        loader = WorkflowLoader(workflows_dir=str(temp_workflows_dir))
        workflows = loader.list_workflows()

        # XML files should be ignored
        assert len(workflows) == 0

    def test_get_workflow_loader_singleton(self):
        """Test that get_workflow_loader returns singleton."""
        loader1 = get_workflow_loader()
        loader2 = get_workflow_loader()

        assert loader1 is loader2
