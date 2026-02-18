"""Unit tests for Ansible Remediation Agent."""

import tempfile
from pathlib import Path

import pytest

from app.agents.ansible_agent import AnsibleAgent, _default_playbooks_dir
from tests.fixtures.mock_llm import MockLLMProvider


@pytest.mark.unit
class TestAnsibleAgent:
    """Test cases for AnsibleAgent."""

    @pytest.fixture
    def temp_playbooks_dir(self):
        """Create a temporary playbooks directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def agent(self, temp_playbooks_dir):
        return AnsibleAgent(
            llm_provider=MockLLMProvider(),
            playbooks_dir=temp_playbooks_dir,
            ansible_path="ansible-playbook",
        )

    def test_agent_initialization(self, agent):
        assert agent.agent_id == "ansible"
        assert "remediation" in agent.capabilities
        assert "playbook_execution" in agent.capabilities

    def test_default_playbooks_dir(self):
        path = _default_playbooks_dir()
        assert isinstance(path, Path)
        assert "playbooks" in str(path)

    @pytest.mark.asyncio
    async def test_execute_no_playbook_returns_error(self, agent):
        """Test execute without playbook in context."""
        result = await agent.execute("Run remediation", context={})
        assert result.success is False
        assert "playbook" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_invalid_playbook_name(self, agent):
        """Test execute with path-traversal playbook name."""
        result = await agent.execute("Run", context={"playbook": "../../../etc/passwd"})
        assert result.success is False
        assert "Invalid playbook name" in result.error

    @pytest.mark.asyncio
    async def test_execute_invalid_playbook_name_shell_chars(self, agent):
        """Test execute with shell metacharacter in playbook name."""
        result = await agent.execute("Run", context={"playbook": "evil; rm -rf /.yml"})
        assert result.success is False
        assert "Invalid playbook name" in result.error

    @pytest.mark.asyncio
    async def test_execute_playbook_not_found(self, agent):
        """Test execute with valid name but playbook not in dir."""
        result = await agent.execute(
            "Run remediation", context={"playbook": "nonexistent.yml"}
        )
        assert result.success is False
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_execute_with_invalid_inventory(self, agent, temp_playbooks_dir):
        """Test execute with invalid inventory path."""
        playbook = temp_playbooks_dir / "test.yml"
        playbook.write_text("---\n- hosts: all\n  tasks: []\n")

        result = await agent.execute(
            "Run", context={"playbook": "test.yml", "inventory": "bad path; ls"}
        )
        assert result.success is False
        assert "Invalid inventory" in result.error

    @pytest.mark.asyncio
    async def test_execute_with_invalid_limit(self, agent, temp_playbooks_dir):
        """Test execute with invalid limit argument."""
        playbook = temp_playbooks_dir / "test.yml"
        playbook.write_text("---\n- hosts: all\n  tasks: []\n")

        result = await agent.execute(
            "Run", context={"playbook": "test.yml", "limit": "bad limit!"}
        )
        assert result.success is False
        assert "Invalid limit" in result.error

    @pytest.mark.asyncio
    async def test_execute_with_invalid_extra_vars(self, agent, temp_playbooks_dir):
        """Test execute with extra_vars as a non-dict string."""
        playbook = temp_playbooks_dir / "test.yml"
        playbook.write_text("---\n- hosts: all\n  tasks: []\n")

        result = await agent.execute(
            "Run", context={"playbook": "test.yml", "extra_vars": "service_name=nginx"}
        )
        assert result.success is False
        assert "extra_vars must be a dict" in result.error

    @pytest.mark.asyncio
    async def test_execute_ansible_not_found(self, agent, temp_playbooks_dir):
        """Test execute when ansible-playbook binary is not installed."""
        playbook = temp_playbooks_dir / "test.yml"
        playbook.write_text("---\n- hosts: all\n  tasks: []\n")

        # Use a path that definitely doesn't exist as ansible binary
        agent._ansible_path = "/nonexistent/ansible-playbook"

        result = await agent.execute(
            "Run remediation", context={"playbook": "test.yml"}
        )
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_with_valid_extra_vars(self, agent, temp_playbooks_dir):
        """Test execute with valid extra_vars dict but missing ansible binary."""
        playbook = temp_playbooks_dir / "test.yml"
        playbook.write_text("---\n- hosts: all\n  tasks: []\n")

        agent._ansible_path = "/nonexistent/ansible-playbook"

        result = await agent.execute(
            "Run",
            context={"playbook": "test.yml", "extra_vars": {"service_name": "nginx"}},
        )
        # The playbook exists and extra_vars is valid — failure is from missing binary
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_with_valid_limit(self, agent, temp_playbooks_dir):
        """Test execute with a valid limit value but missing ansible binary."""
        playbook = temp_playbooks_dir / "test.yml"
        playbook.write_text("---\n- hosts: all\n  tasks: []\n")

        agent._ansible_path = "/nonexistent/ansible-playbook"

        result = await agent.execute(
            "Run", context={"playbook": "test.yml", "limit": "webservers"}
        )
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_empty_extra_vars_dict(self, agent, temp_playbooks_dir):
        """Test execute with an empty extra_vars dict (no -e flag added)."""
        playbook = temp_playbooks_dir / "test.yml"
        playbook.write_text("---\n- hosts: all\n  tasks: []\n")

        agent._ansible_path = "/nonexistent/ansible-playbook"

        result = await agent.execute(
            "Run", context={"playbook": "test.yml", "extra_vars": {}}
        )
        assert result.success is False
        assert "not found" in result.error.lower()
