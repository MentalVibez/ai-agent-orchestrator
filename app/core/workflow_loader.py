"""Workflow loader for loading workflow definitions from files."""

import json
import logging
from pathlib import Path
from typing import Dict, Optional

import yaml

from app.models.workflow import Workflow

logger = logging.getLogger(__name__)


class WorkflowLoader:
    """Loads workflow definitions from YAML or JSON files."""

    def __init__(self, workflows_dir: Optional[str] = None):
        """
        Initialize workflow loader.

        Args:
            workflows_dir: Directory containing workflow files (default: app/workflows)
        """
        if workflows_dir is None:
            # Default to app/workflows directory
            base_dir = Path(__file__).parent.parent.parent
            self.workflows_dir = base_dir / "app" / "workflows" / "examples"
        else:
            self.workflows_dir = Path(workflows_dir)

        self._workflows: Dict[str, Workflow] = {}
        self._load_workflows()

    def _load_workflows(self):
        """Load all workflow definitions from the workflows directory."""
        if not self.workflows_dir.exists():
            logger.warning(f"Workflows directory does not exist: {self.workflows_dir}")
            return

        for file_path in self.workflows_dir.glob("*.yaml"):
            try:
                workflow = self._load_workflow_file(file_path)
                if workflow:
                    self._workflows[workflow.workflow_id] = workflow
                    logger.info(f"Loaded workflow: {workflow.workflow_id}")
            except Exception as e:
                logger.error(f"Failed to load workflow from {file_path}: {str(e)}")

        for file_path in self.workflows_dir.glob("*.yml"):
            try:
                workflow = self._load_workflow_file(file_path)
                if workflow:
                    self._workflows[workflow.workflow_id] = workflow
                    logger.info(f"Loaded workflow: {workflow.workflow_id}")
            except Exception as e:
                logger.error(f"Failed to load workflow from {file_path}: {str(e)}")

        for file_path in self.workflows_dir.glob("*.json"):
            try:
                workflow = self._load_workflow_file(file_path)
                if workflow:
                    self._workflows[workflow.workflow_id] = workflow
                    logger.info(f"Loaded workflow: {workflow.workflow_id}")
            except Exception as e:
                logger.error(f"Failed to load workflow from {file_path}: {str(e)}")

    def _load_workflow_file(self, file_path: Path) -> Optional[Workflow]:
        """
        Load a workflow from a file.

        Args:
            file_path: Path to workflow file

        Returns:
            Workflow instance if successful, None otherwise
        """
        try:
            with open(file_path, "r") as f:
                if file_path.suffix in [".yaml", ".yml"]:
                    data = yaml.safe_load(f)
                elif file_path.suffix == ".json":
                    data = json.load(f)
                else:
                    logger.warning(f"Unsupported file format: {file_path.suffix}")
                    return None

                # Convert to Workflow model
                workflow = Workflow(**data)
                return workflow
        except Exception as e:
            logger.error(f"Error loading workflow from {file_path}: {str(e)}")
            return None

    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """
        Get a workflow by ID.

        Args:
            workflow_id: Workflow identifier

        Returns:
            Workflow instance if found, None otherwise
        """
        return self._workflows.get(workflow_id)

    def list_workflows(self) -> Dict[str, Workflow]:
        """
        List all loaded workflows.

        Returns:
            Dictionary mapping workflow_id to Workflow
        """
        return self._workflows.copy()

    def reload(self):
        """Reload all workflows from disk."""
        self._workflows.clear()
        self._load_workflows()


# Global workflow loader instance
_workflow_loader: Optional[WorkflowLoader] = None


def get_workflow_loader() -> WorkflowLoader:
    """Get the global workflow loader instance."""
    global _workflow_loader
    if _workflow_loader is None:
        _workflow_loader = WorkflowLoader()
    return _workflow_loader
