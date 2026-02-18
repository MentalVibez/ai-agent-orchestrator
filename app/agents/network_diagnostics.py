"""Network Diagnostics Agent — real subprocess-based network diagnostics."""

import asyncio
import logging
import re
import socket
import time
from typing import Any, Dict, List, Optional

from app.agents.base import BaseAgent
from app.llm.base import LLMProvider
from app.models.agent import AgentResult

logger = logging.getLogger(__name__)

# Security: only allow safe hostnames/IPs — no shell metacharacters
_SAFE_HOST_RE = re.compile(r"^[a-zA-Z0-9.\-_:]+$")

# Default timeouts (seconds)
PING_TIMEOUT = 10
DNS_TIMEOUT = 5
TRACEROUTE_TIMEOUT = 30
PORT_CHECK_TIMEOUT = 5
COMMAND_TIMEOUT = 15  # General subprocess timeout


def _validate_host(host: str) -> Optional[str]:
    """
    Validate a hostname/IP for safe use in subprocess args.
    Returns an error string if invalid, None if valid.
    """
    host = host.strip()
    if not host:
        return "Host/IP is required."
    if not _SAFE_HOST_RE.match(host):
        return (
            f"Invalid host '{host}': only alphanumeric, dot, hyphen, underscore, colon allowed. "
            "Shell metacharacters are not permitted."
        )
    if len(host) > 253:
        return "Host name too long (max 253 characters)."
    return None


async def _run_command(
    args: List[str], timeout: int = COMMAND_TIMEOUT
) -> Dict[str, Any]:
    """
    Run a subprocess command safely (no shell=True) with a hard timeout.
    Returns dict with stdout, stderr, returncode, timed_out.
    """
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
        return {"stdout": "", "stderr": "", "returncode": -1, "timed_out": True}
    except FileNotFoundError as e:
        return {"stdout": "", "stderr": str(e), "returncode": -1, "timed_out": False}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "returncode": -1, "timed_out": False}


async def _run_ping(host: str, count: int = 4) -> Dict[str, Any]:
    """Run Linux ping and extract packet loss % and avg RTT."""
    result = await _run_command(
        ["ping", "-c", str(count), "-W", "2", host],
        timeout=PING_TIMEOUT,
    )
    data: Dict[str, Any] = {
        "host": host,
        "reachable": result["returncode"] == 0,
        "timed_out": result["timed_out"],
        "raw_output": result["stdout"] or result["stderr"],
    }
    if result["timed_out"]:
        data["error"] = f"ping timed out after {PING_TIMEOUT}s"
        return data

    stdout = result["stdout"]
    # Extract packet loss: "4 packets transmitted, 4 received, 0% packet loss"
    loss_match = re.search(r"(\d+)%\s+packet\s+loss", stdout)
    if loss_match:
        data["packet_loss_percent"] = int(loss_match.group(1))

    # Extract RTT: "rtt min/avg/max/mdev = 12.345/13.000/14.000/0.500 ms"
    rtt_match = re.search(r"rtt\s+min/avg/max/mdev\s*=\s*([\d.]+)/([\d.]+)/([\d.]+)", stdout)
    if rtt_match:
        data["rtt_min_ms"] = float(rtt_match.group(1))
        data["rtt_avg_ms"] = float(rtt_match.group(2))
        data["rtt_max_ms"] = float(rtt_match.group(3))

    return data


async def _run_dns(hostname: str) -> Dict[str, Any]:
    """Resolve DNS using Python's socket module (no subprocess needed, cross-platform)."""
    start = time.monotonic()
    loop = asyncio.get_event_loop()
    data: Dict[str, Any] = {"hostname": hostname}
    try:
        results = await asyncio.wait_for(
            loop.run_in_executor(None, socket.getaddrinfo, hostname, None),
            timeout=DNS_TIMEOUT,
        )
        elapsed_ms = (time.monotonic() - start) * 1000
        resolved_ips = list({r[4][0] for r in results})
        data["resolved"] = True
        data["ip_addresses"] = resolved_ips
        data["resolution_time_ms"] = round(elapsed_ms, 2)
    except asyncio.TimeoutError:
        data["resolved"] = False
        data["error"] = f"DNS resolution timed out after {DNS_TIMEOUT}s"
    except socket.gaierror as e:
        data["resolved"] = False
        data["error"] = str(e)
    return data


async def _run_traceroute(host: str, max_hops: int = 15) -> Dict[str, Any]:
    """Run Linux traceroute (capped at max_hops)."""
    result = await _run_command(
        ["traceroute", "-m", str(max_hops), "-w", "2", host],
        timeout=TRACEROUTE_TIMEOUT,
    )
    data: Dict[str, Any] = {
        "host": host,
        "timed_out": result["timed_out"],
        "raw_output": result["stdout"] or result["stderr"],
    }
    if result["timed_out"]:
        data["error"] = f"traceroute timed out after {TRACEROUTE_TIMEOUT}s"
        return data

    # Parse hop lines: "  1  192.168.1.1 (192.168.1.1)  0.987 ms  1.234 ms  1.001 ms"
    hops = []
    for line in result["stdout"].splitlines():
        hop_match = re.match(
            r"\s*(\d+)\s+(\S+)(?:\s+\(([^)]+)\))?\s+(.+)", line
        )
        if hop_match:
            hops.append({
                "hop": int(hop_match.group(1)),
                "host": hop_match.group(2),
                "ip": hop_match.group(3) or hop_match.group(2),
                "timing": hop_match.group(4).strip(),
            })
    data["hops"] = hops
    data["hop_count"] = len(hops)
    return data


async def _run_port_check(host: str, port: int) -> Dict[str, Any]:
    """Check if a TCP port is open using asyncio.open_connection (no subprocess)."""
    start = time.monotonic()
    data: Dict[str, Any] = {"host": host, "port": port}
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=PORT_CHECK_TIMEOUT,
        )
        elapsed_ms = (time.monotonic() - start) * 1000
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        data["open"] = True
        data["connection_time_ms"] = round(elapsed_ms, 2)
    except asyncio.TimeoutError:
        data["open"] = False
        data["state"] = "filtered or timed out"
        data["error"] = f"Connection timed out after {PORT_CHECK_TIMEOUT}s"
    except ConnectionRefusedError:
        data["open"] = False
        data["state"] = "closed (connection refused)"
    except OSError as e:
        data["open"] = False
        data["state"] = "error"
        data["error"] = str(e)
    return data


class NetworkDiagnosticsAgent(BaseAgent):
    """Agent specialized in network diagnostics — runs real commands (ping, DNS, traceroute, port check)."""

    def __init__(self, llm_provider: LLMProvider):
        super().__init__(
            agent_id="network_diagnostics",
            name="Network Diagnostics Agent",
            description="Handles network connectivity, latency, routing, and DNS issues using real network commands",
            llm_provider=llm_provider,
            capabilities=[
                "network_connectivity",
                "latency_analysis",
                "routing_diagnostics",
                "dns_resolution",
                "port_scanning",
            ],
        )

    async def execute(self, task: str, context: Optional[Dict[str, Any]] = None) -> AgentResult:
        """
        Execute a network diagnostics task using real network commands.

        Context may include:
          - host: target hostname or IP address (required for most diagnostics)
          - port: TCP port number (for port check)
          - count: ping packet count (default 4)
        """
        try:
            context = context or {}
            diagnostic_type = self._identify_diagnostic_type(task)

            # Extract and validate host
            host = (context.get("host") or context.get("hostname") or "").strip()

            # Try to extract host from task text if not in context
            if not host:
                host_match = re.search(
                    r"(?:to|for|on|at|host|server|ip)\s+([a-zA-Z0-9.\-_]+)",
                    task,
                    re.IGNORECASE,
                )
                if host_match:
                    host = host_match.group(1).strip()

            # Validate host (security check)
            if host:
                host_error = _validate_host(host)
                if host_error:
                    return self._format_result(
                        success=False,
                        output={},
                        error=f"Invalid host: {host_error}",
                        metadata={"agent_id": self.agent_id, "task": task},
                    )

            # Collect real diagnostic data based on task type
            diagnostics: Dict[str, Any] = {"diagnostic_type": diagnostic_type}

            if diagnostic_type == "connectivity_check" and host:
                try:
                    count = max(1, min(int(context.get("count", 4)), 10))
                except (ValueError, TypeError):
                    count = 4
                diagnostics["ping"] = await _run_ping(host, count=count)

            elif diagnostic_type == "dns_resolution":
                dns_host = host or task  # fallback: use task text as hostname
                # Extract domain from task if still no host
                if not host:
                    domain_match = re.search(
                        r"([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})", task
                    )
                    if domain_match:
                        dns_host = domain_match.group(1)
                if dns_host and not _validate_host(dns_host):
                    diagnostics["dns"] = await _run_dns(dns_host)

            elif diagnostic_type == "latency_analysis" and host:
                # Ping with more packets for latency analysis
                diagnostics["ping"] = await _run_ping(host, count=8)

            elif diagnostic_type == "routing_analysis" and host:
                diagnostics["traceroute"] = await _run_traceroute(host)

            elif diagnostic_type == "port_analysis" and host:
                port_raw = context.get("port")
                # Try to extract port from task
                if not port_raw:
                    port_match = re.search(r"port\s+(\d+)", task, re.IGNORECASE)
                    if port_match:
                        port_raw = port_match.group(1)
                if port_raw:
                    try:
                        port = int(port_raw)
                        if 1 <= port <= 65535:
                            diagnostics["port_check"] = await _run_port_check(host, port)
                        else:
                            diagnostics["error"] = f"Port {port} is out of valid range (1-65535)"
                    except (ValueError, TypeError):
                        diagnostics["error"] = f"Invalid port value: {port_raw}"
                else:
                    # No specific port — try common ports
                    common_ports = [80, 443, 22, 3306]
                    diagnostics["port_checks"] = {}
                    for p in common_ports:
                        diagnostics["port_checks"][str(p)] = await _run_port_check(host, p)

            else:
                # General: run ping + DNS for any host
                if host:
                    diagnostics["ping"] = await _run_ping(host)
                    diagnostics["dns"] = await _run_dns(host)
                else:
                    # No host at all — return a helpful error
                    return self._format_result(
                        success=False,
                        output={},
                        error=(
                            "No target host specified. Provide 'host' in context "
                            "or include the hostname in the task description."
                        ),
                        metadata={"agent_id": self.agent_id, "task": task},
                    )

            # Pass real measurement data to LLM for interpretation and recommendations
            from app.core.prompt_generator import get_prompt_generator

            prompt_gen = get_prompt_generator()
            import json
            enhanced_context = {**context, "diagnostics": diagnostics, "host": host}
            prompts = prompt_gen.generate_agent_prompt(
                agent_id=self.agent_id, task=task, context=enhanced_context
            )

            analysis = await self._generate_response(
                prompt=(
                    f"{prompts['user_prompt']}\n\n"
                    f"Real measurement data collected:\n{json.dumps(diagnostics, indent=2, default=str)}\n\n"
                    "Based on this real data, provide: (1) interpretation of results, "
                    "(2) identified issues if any, (3) recommended actions."
                ),
                system_prompt=prompts["system_prompt"],
                temperature=0.2,
            )

            return self._format_result(
                success=True,
                output={
                    "diagnostic_type": diagnostic_type,
                    "host": host,
                    "measurements": diagnostics,
                    "analysis": analysis,
                    "summary": analysis[:200] + "..." if len(analysis) > 200 else analysis,
                },
                metadata={
                    "agent_id": self.agent_id,
                    "task": task,
                    "host": host,
                    "diagnostic_type": diagnostic_type,
                },
            )

        except Exception as e:
            logger.exception("Network diagnostics failed")
            return self._format_result(
                success=False,
                output={},
                error=f"Network diagnostics failed: {str(e)}",
                metadata={"agent_id": self.agent_id, "task": task},
            )

    def _identify_diagnostic_type(self, task: str) -> str:
        """Identify the type of network diagnostic needed."""
        task_lower = task.lower()
        if any(keyword in task_lower for keyword in ["ping", "connectivity", "reachable", "reach"]):
            return "connectivity_check"
        elif any(keyword in task_lower for keyword in ["dns", "resolve", "domain", "lookup", "nslookup"]):
            return "dns_resolution"
        elif any(keyword in task_lower for keyword in ["latency", "delay", "slow", "rtt", "round trip"]):
            return "latency_analysis"
        elif any(keyword in task_lower for keyword in ["route", "traceroute", "tracert", "path", "hop"]):
            return "routing_analysis"
        elif any(keyword in task_lower for keyword in ["port", "scan", "firewall", "open", "closed"]):
            return "port_analysis"
        else:
            return "general_diagnostics"
