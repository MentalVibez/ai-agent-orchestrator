"""Infrastructure Agent — read-only infrastructure inspection (services, Docker, optional AWS)."""

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.agents.base import BaseAgent
from app.llm.base import LLMProvider
from app.models.agent import AgentResult

logger = logging.getLogger(__name__)

# Security: only allow safe service names for systemctl
_SAFE_SERVICE_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-@.]+$")

SUBPROCESS_TIMEOUT = 15  # seconds for systemctl / docker commands


async def _run_command_safe(args: List[str], timeout: int = SUBPROCESS_TIMEOUT) -> Dict[str, Any]:
    """Run a subprocess command (no shell=True) with timeout. Returns stdout/stderr/returncode."""
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=timeout,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "stdout": stdout.decode(errors="replace").strip() if stdout else "",
            "stderr": stderr.decode(errors="replace").strip() if stderr else "",
            "returncode": proc.returncode,
            "timed_out": False,
        }
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return {"stdout": "", "stderr": f"Command timed out after {timeout}s", "returncode": -1, "timed_out": True}
    except FileNotFoundError as e:
        return {"stdout": "", "stderr": str(e), "returncode": -1, "timed_out": False, "not_found": True}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "returncode": -1, "timed_out": False}


async def _get_service_status(service_name: str) -> Dict[str, Any]:
    """Get systemd service status using systemctl."""
    if not _SAFE_SERVICE_NAME_RE.match(service_name):
        return {"error": f"Invalid service name: '{service_name}'"}

    result = await _run_command_safe(
        ["systemctl", "status", service_name, "--no-pager", "-l"],
        timeout=SUBPROCESS_TIMEOUT,
    )

    if result.get("not_found"):
        return {"service": service_name, "available": False, "error": "systemctl not found"}

    data: Dict[str, Any] = {
        "service": service_name,
        "raw_output": result["stdout"] or result["stderr"],
    }

    # Parse active state from output: "Active: active (running) since ..."
    active_match = re.search(r"Active:\s+(\S+)\s+\((\w+)\)", result["stdout"])
    if active_match:
        data["active_state"] = active_match.group(1)
        data["sub_state"] = active_match.group(2)
        data["running"] = active_match.group(1) == "active" and active_match.group(2) == "running"
    else:
        data["running"] = result["returncode"] == 0

    # Extract PID if present
    pid_match = re.search(r"Main PID:\s+(\d+)", result["stdout"])
    if pid_match:
        data["main_pid"] = int(pid_match.group(1))

    return data


async def _get_all_services() -> Dict[str, Any]:
    """List all running systemd services."""
    result = await _run_command_safe(
        ["systemctl", "list-units", "--type=service", "--state=running", "--no-pager", "--plain"],
        timeout=SUBPROCESS_TIMEOUT,
    )
    if result.get("not_found"):
        return {"available": False, "error": "systemctl not found"}

    services = []
    for line in result["stdout"].splitlines():
        # Lines look like: "nginx.service   loaded active running   A high performance web server"
        parts = line.split()
        if len(parts) >= 4 and parts[0].endswith(".service"):
            services.append({
                "name": parts[0],
                "load": parts[1] if len(parts) > 1 else "",
                "active": parts[2] if len(parts) > 2 else "",
                "sub": parts[3] if len(parts) > 3 else "",
                "description": " ".join(parts[4:]) if len(parts) > 4 else "",
            })
    return {"running_services": services, "count": len(services)}


async def _get_docker_containers() -> Dict[str, Any]:
    """List Docker containers using docker ps --format json."""
    result = await _run_command_safe(
        ["docker", "ps", "--format", "{{json .}}"],
        timeout=SUBPROCESS_TIMEOUT,
    )
    if result.get("not_found"):
        return {"available": False, "error": "docker not found"}
    if result["returncode"] != 0:
        return {"available": True, "error": result["stderr"] or f"exit code {result['returncode']}"}

    containers = []
    for line in result["stdout"].splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            containers.append(json.loads(line))
        except json.JSONDecodeError:
            pass

    return {"containers": containers, "count": len(containers), "available": True}


async def _get_aws_summary() -> Dict[str, Any]:
    """Collect basic AWS resource summary using boto3 (optional, fails gracefully)."""
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
    except ImportError:
        return {"available": False, "error": "boto3 not installed"}

    summary: Dict[str, Any] = {"available": True}

    # EC2 instances
    try:
        ec2 = boto3.client("ec2")
        reservations = ec2.describe_instances(
            Filters=[{"Name": "instance-state-name", "Values": ["running", "stopped"]}]
        ).get("Reservations", [])
        instances = [
            {
                "id": inst["InstanceId"],
                "state": inst["State"]["Name"],
                "type": inst["InstanceType"],
                "name": next(
                    (t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"),
                    "(unnamed)",
                ),
            }
            for r in reservations
            for inst in r.get("Instances", [])
        ]
        summary["ec2_instances"] = instances[:20]  # cap to 20
    except (BotoCoreError, ClientError, NoCredentialsError) as e:
        summary["ec2_error"] = str(e)

    # RDS instances
    try:
        rds = boto3.client("rds")
        dbs = rds.describe_db_instances().get("DBInstances", [])
        summary["rds_instances"] = [
            {
                "id": db["DBInstanceIdentifier"],
                "status": db["DBInstanceStatus"],
                "engine": db["Engine"],
                "class": db["DBInstanceClass"],
            }
            for db in dbs[:10]
        ]
    except (BotoCoreError, ClientError, NoCredentialsError) as e:
        summary["rds_error"] = str(e)

    return summary


class InfrastructureAgent(BaseAgent):
    """Agent for read-only infrastructure inspection: services, Docker, optional AWS."""

    def __init__(self, llm_provider: LLMProvider):
        super().__init__(
            agent_id="infrastructure",
            name="Infrastructure Agent",
            description=(
                "Read-only infrastructure inspection: systemd service status, Docker containers, "
                "and optional AWS resource summary (EC2, RDS)"
            ),
            llm_provider=llm_provider,
            capabilities=[
                "service_status",
                "container_inspection",
                "cloud_resource_inspection",
                "infrastructure_health",
                "resource_management",
            ],
        )

    async def execute(self, task: str, context: Optional[Dict[str, Any]] = None) -> AgentResult:
        """
        Execute an infrastructure inspection task (read-only).

        Context may include:
          - service: specific service name to check (e.g. "nginx", "postgresql")
          - check_docker: bool — include Docker container status (default: True)
          - check_aws: bool — include AWS resource summary (default: False, requires boto3 + creds)
          - check_services: bool — list all running services (default: True)
        """
        try:
            context = context or {}
            task_lower = task.lower()
            infrastructure_data: Dict[str, Any] = {}

            # Determine what to collect based on context and task keywords
            check_services = context.get("check_services", True)
            check_docker = context.get(
                "check_docker",
                any(kw in task_lower for kw in ["docker", "container", "all", "overview"])
                or context.get("check_docker", True),
            )
            check_aws = context.get(
                "check_aws",
                any(kw in task_lower for kw in ["aws", "ec2", "rds", "cloud"]),
            )

            # Specific service check
            service_name = context.get("service", "").strip()
            if not service_name:
                # Try to extract service name from task
                svc_match = re.search(
                    r"(?:service|status\s+of|check)\s+([a-zA-Z0-9_\-@.]+)",
                    task,
                    re.IGNORECASE,
                )
                if svc_match:
                    candidate = svc_match.group(1)
                    if _SAFE_SERVICE_NAME_RE.match(candidate):
                        service_name = candidate

            if service_name:
                infrastructure_data["service_status"] = await _get_service_status(service_name)

            if check_services and not service_name:
                infrastructure_data["running_services"] = await _get_all_services()

            if check_docker:
                infrastructure_data["docker"] = await _get_docker_containers()

            if check_aws:
                infrastructure_data["aws"] = await _get_aws_summary()

            if not infrastructure_data:
                # Default: get all services + docker
                infrastructure_data["running_services"] = await _get_all_services()
                infrastructure_data["docker"] = await _get_docker_containers()

            # LLM analysis of collected infrastructure data
            analysis = await self._generate_response(
                prompt=(
                    f"Task: {task}\n\n"
                    f"Infrastructure data collected:\n"
                    f"{json.dumps(infrastructure_data, indent=2, default=str)}\n\n"
                    "Provide: (1) infrastructure health summary, "
                    "(2) any services that are down or in a failed state, "
                    "(3) recommended actions if any issues found."
                ),
                system_prompt=(
                    "You are an expert infrastructure engineer. Analyze infrastructure status data "
                    "and provide clear, actionable assessments. Report exactly what the data shows — "
                    "do not speculate about services or resources not present in the data."
                ),
                temperature=0.2,
            )

            return self._format_result(
                success=True,
                output={
                    "infrastructure": infrastructure_data,
                    "analysis": analysis,
                    "summary": analysis[:200] + "..." if len(analysis) > 200 else analysis,
                },
                metadata={
                    "agent_id": self.agent_id,
                    "task": task,
                    "checks_performed": list(infrastructure_data.keys()),
                },
            )

        except Exception as e:
            logger.exception("Infrastructure inspection failed")
            return self._format_result(
                success=False,
                output={},
                error=f"Infrastructure inspection failed: {str(e)}",
                metadata={"agent_id": self.agent_id, "task": task},
            )
