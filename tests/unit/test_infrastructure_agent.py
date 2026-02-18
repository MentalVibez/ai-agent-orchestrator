"""Unit tests for Infrastructure Agent."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.infrastructure import (
    InfrastructureAgent,
    _get_all_services,
    _get_aws_summary,
    _get_docker_containers,
    _get_service_status,
    _run_command_safe,
)
from tests.fixtures.mock_llm import MockLLMProvider


@pytest.mark.asyncio
class TestRunCommandSafe:
    """Test _run_command_safe utility function."""

    async def test_successful_command(self):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        stdout = b"output text"
        stderr = b""

        with patch(
            "asyncio.wait_for",
            side_effect=[mock_proc, (stdout, stderr)],
        ):
            with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                result = await _run_command_safe(["echo", "hello"])

        assert isinstance(result, dict)

    async def test_command_not_found(self):
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError("not found")):
            result = await _run_command_safe(["nonexistent_command"])
        assert result["returncode"] == -1
        assert result.get("not_found") is True

    async def test_command_timeout(self):
        import asyncio

        with patch(
            "asyncio.wait_for", side_effect=asyncio.TimeoutError()
        ):
            with patch("asyncio.create_subprocess_exec", MagicMock()):
                result = await _run_command_safe(["slow_command"], timeout=1)
        assert result["returncode"] == -1
        assert result["timed_out"] is True

    async def test_generic_exception(self):
        with patch("asyncio.create_subprocess_exec", side_effect=Exception("unexpected")):
            result = await _run_command_safe(["cmd"])
        assert result["returncode"] == -1


@pytest.mark.asyncio
class TestGetServiceStatus:
    """Test _get_service_status utility function."""

    async def test_invalid_service_name(self):
        result = await _get_service_status("bad service name!")
        assert "error" in result
        assert "Invalid" in result["error"]

    async def test_systemctl_not_found(self):
        with patch(
            "app.agents.infrastructure._run_command_safe",
            AsyncMock(return_value={"stdout": "", "stderr": "", "returncode": -1, "not_found": True}),
        ):
            result = await _get_service_status("nginx")
        assert result["available"] is False

    async def test_running_service(self):
        output = "● nginx.service\n   Active: active (running) since Mon\n   Main PID: 1234\n"
        with patch(
            "app.agents.infrastructure._run_command_safe",
            AsyncMock(return_value={"stdout": output, "stderr": "", "returncode": 0}),
        ):
            result = await _get_service_status("nginx")
        assert result["running"] is True
        assert result["main_pid"] == 1234

    async def test_stopped_service(self):
        output = "● nginx.service\n   Active: inactive (dead) since Mon\n"
        with patch(
            "app.agents.infrastructure._run_command_safe",
            AsyncMock(return_value={"stdout": output, "stderr": "", "returncode": 3}),
        ):
            result = await _get_service_status("nginx")
        assert result["running"] is False


@pytest.mark.asyncio
class TestGetAllServices:
    """Test _get_all_services utility function."""

    async def test_systemctl_not_found(self):
        with patch(
            "app.agents.infrastructure._run_command_safe",
            AsyncMock(return_value={"stdout": "", "stderr": "", "returncode": -1, "not_found": True}),
        ):
            result = await _get_all_services()
        assert result["available"] is False

    async def test_parses_running_services(self):
        stdout = (
            "nginx.service   loaded active running   A high performance web server\n"
            "sshd.service    loaded active running   OpenSSH server daemon\n"
        )
        with patch(
            "app.agents.infrastructure._run_command_safe",
            AsyncMock(return_value={"stdout": stdout, "stderr": "", "returncode": 0}),
        ):
            result = await _get_all_services()
        assert result["count"] == 2
        assert any(s["name"] == "nginx.service" for s in result["running_services"])

    async def test_empty_services_list(self):
        with patch(
            "app.agents.infrastructure._run_command_safe",
            AsyncMock(return_value={"stdout": "", "stderr": "", "returncode": 0}),
        ):
            result = await _get_all_services()
        assert result["count"] == 0


@pytest.mark.asyncio
class TestGetDockerContainers:
    """Test _get_docker_containers utility function."""

    async def test_docker_not_found(self):
        with patch(
            "app.agents.infrastructure._run_command_safe",
            AsyncMock(return_value={"stdout": "", "stderr": "", "returncode": -1, "not_found": True}),
        ):
            result = await _get_docker_containers()
        assert result["available"] is False

    async def test_docker_error(self):
        with patch(
            "app.agents.infrastructure._run_command_safe",
            AsyncMock(return_value={"stdout": "", "stderr": "permission denied", "returncode": 1}),
        ):
            result = await _get_docker_containers()
        assert "error" in result

    async def test_parses_containers(self):
        import json

        container = {"ID": "abc123", "Names": "nginx", "Status": "Up 2 hours"}
        stdout = json.dumps(container) + "\n"
        with patch(
            "app.agents.infrastructure._run_command_safe",
            AsyncMock(return_value={"stdout": stdout, "stderr": "", "returncode": 0}),
        ):
            result = await _get_docker_containers()
        assert result["count"] == 1
        assert result["containers"][0]["ID"] == "abc123"

    async def test_empty_container_list(self):
        with patch(
            "app.agents.infrastructure._run_command_safe",
            AsyncMock(return_value={"stdout": "", "stderr": "", "returncode": 0}),
        ):
            result = await _get_docker_containers()
        assert result["count"] == 0
        assert result["available"] is True


@pytest.mark.asyncio
class TestGetAwsSummary:
    """Test _get_aws_summary utility function."""

    async def test_boto3_not_installed(self):
        with patch.dict("sys.modules", {"boto3": None}):
            result = await _get_aws_summary()
        # Either returns error or has available=False
        assert result.get("available") is False or "error" in result

    async def test_boto3_available(self):
        from botocore.exceptions import NoCredentialsError

        mock_ec2 = MagicMock()
        mock_ec2.describe_instances.side_effect = NoCredentialsError()
        mock_rds = MagicMock()
        mock_rds.describe_db_instances.side_effect = NoCredentialsError()

        with patch("boto3.client", side_effect=lambda svc, **kw: mock_ec2 if svc == "ec2" else mock_rds):
            result = await _get_aws_summary()

        assert result["available"] is True
        assert "ec2_error" in result


@pytest.mark.unit
class TestInfrastructureAgent:
    """Test cases for InfrastructureAgent."""

    @pytest.fixture
    def agent(self):
        return InfrastructureAgent(llm_provider=MockLLMProvider())

    def test_agent_initialization(self, agent):
        assert agent.agent_id == "infrastructure"
        assert "service_status" in agent.capabilities
        assert "container_inspection" in agent.capabilities

    @pytest.mark.asyncio
    async def test_execute_with_specific_service(self, agent):
        """Test execute checking a specific service."""
        with patch(
            "app.agents.infrastructure._get_service_status",
            AsyncMock(return_value={"service": "nginx", "running": True}),
        ):
            with patch(
                "app.agents.infrastructure._get_docker_containers",
                AsyncMock(return_value={"containers": [], "count": 0, "available": True}),
            ):
                result = await agent.execute("Check service nginx", context={"service": "nginx"})

        assert result.success is True
        assert result.agent_id == "infrastructure"

    @pytest.mark.asyncio
    async def test_execute_default_collects_services_and_docker(self, agent):
        """Test execute default behavior collects services and docker."""
        with patch(
            "app.agents.infrastructure._get_all_services",
            AsyncMock(return_value={"running_services": [], "count": 0}),
        ):
            with patch(
                "app.agents.infrastructure._get_docker_containers",
                AsyncMock(return_value={"containers": [], "count": 0, "available": True}),
            ):
                result = await agent.execute("Check infrastructure", context={})

        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_with_check_aws(self, agent):
        """Test execute with AWS check enabled."""
        with patch(
            "app.agents.infrastructure._get_all_services",
            AsyncMock(return_value={"running_services": [], "count": 0}),
        ):
            with patch(
                "app.agents.infrastructure._get_docker_containers",
                AsyncMock(return_value={"containers": [], "count": 0, "available": True}),
            ):
                with patch(
                    "app.agents.infrastructure._get_aws_summary",
                    AsyncMock(return_value={"available": True, "ec2_instances": []}),
                ):
                    result = await agent.execute(
                        "Check AWS infrastructure", context={"check_aws": True}
                    )

        assert result.success is True
        assert "aws" in result.output["infrastructure"]

    @pytest.mark.asyncio
    async def test_execute_extracts_service_from_task(self, agent):
        """Test execute extracts service name from task text."""
        with patch(
            "app.agents.infrastructure._get_service_status",
            AsyncMock(return_value={"service": "nginx", "running": True}),
        ):
            with patch(
                "app.agents.infrastructure._get_docker_containers",
                AsyncMock(return_value={"containers": [], "count": 0, "available": True}),
            ):
                result = await agent.execute("Check status of nginx service")

        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_handles_exception(self, agent):
        """Test execute handles unexpected exceptions gracefully."""
        # Use a task that won't match service-name extraction (no "check/service/status of")
        with patch(
            "app.agents.infrastructure._get_all_services",
            AsyncMock(side_effect=Exception("unexpected error")),
        ):
            with patch(
                "app.agents.infrastructure._get_docker_containers",
                AsyncMock(return_value={"containers": [], "count": 0, "available": True}),
            ):
                result = await agent.execute(
                    "List running processes", context={"check_docker": False}
                )

        assert result.success is False
        assert "Infrastructure inspection failed" in result.error

    @pytest.mark.asyncio
    async def test_execute_output_has_expected_keys(self, agent):
        """Test that execute output has expected structure."""
        with patch(
            "app.agents.infrastructure._get_all_services",
            AsyncMock(return_value={"running_services": [], "count": 0}),
        ):
            with patch(
                "app.agents.infrastructure._get_docker_containers",
                AsyncMock(return_value={"containers": [], "count": 0, "available": True}),
            ):
                result = await agent.execute("Check infrastructure", context={})

        assert "infrastructure" in result.output
        assert "analysis" in result.output
        assert "summary" in result.output
