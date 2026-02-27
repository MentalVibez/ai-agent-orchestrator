"""System Monitoring Agent — real system metrics via psutil."""

import logging
import os
import platform
import time
from typing import Any, Dict, Optional

from app.agents.base import BaseAgent
from app.llm.base import LLMProvider
from app.models.agent import AgentResult

logger = logging.getLogger(__name__)

# Import psutil with graceful fallback for environments where it's not installed
try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None  # type: ignore[assignment]
    _PSUTIL_AVAILABLE = False
    logger.warning(
        "psutil is not installed — system metrics will be limited to static OS information. "
        "Install psutil: pip install psutil"
    )


def _collect_psutil_metrics() -> Dict[str, Any]:
    """Collect real-time system metrics using psutil."""
    metrics: Dict[str, Any] = {}

    # CPU usage (blocks 1 second for accurate reading)
    try:
        metrics["cpu_percent"] = psutil.cpu_percent(interval=1)
        metrics["cpu_count_logical"] = psutil.cpu_count(logical=True)
        metrics["cpu_count_physical"] = psutil.cpu_count(logical=False)
        try:
            load = psutil.getloadavg()
            metrics["load_avg_1m"] = round(load[0], 2)
            metrics["load_avg_5m"] = round(load[1], 2)
            metrics["load_avg_15m"] = round(load[2], 2)
        except AttributeError:
            pass  # getloadavg not available on all platforms
    except OSError as e:
        logger.warning("Could not collect CPU metrics: %s", e)

    # Memory
    try:
        mem = psutil.virtual_memory()
        metrics["memory"] = {
            "total_gb": round(mem.total / (1024 ** 3), 2),
            "used_gb": round(mem.used / (1024 ** 3), 2),
            "available_gb": round(mem.available / (1024 ** 3), 2),
            "percent_used": mem.percent,
        }
        swap = psutil.swap_memory()
        metrics["swap"] = {
            "total_gb": round(swap.total / (1024 ** 3), 2),
            "used_gb": round(swap.used / (1024 ** 3), 2),
            "percent_used": swap.percent,
        }
    except OSError as e:
        logger.warning("Could not collect memory metrics: %s", e)

    # Disk usage per mounted partition
    try:
        partitions = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                partitions.append({
                    "mountpoint": part.mountpoint,
                    "device": part.device,
                    "fstype": part.fstype,
                    "total_gb": round(usage.total / (1024 ** 3), 2),
                    "used_gb": round(usage.used / (1024 ** 3), 2),
                    "free_gb": round(usage.free / (1024 ** 3), 2),
                    "percent_used": usage.percent,
                })
            except (PermissionError, OSError):
                continue
        metrics["disks"] = partitions
    except OSError as e:
        logger.warning("Could not collect disk metrics: %s", e)

    # Top processes by CPU usage (top 15)
    try:
        processes = []
        for proc in psutil.process_iter(
            ["pid", "name", "cpu_percent", "memory_percent", "status"]
        ):
            try:
                info = proc.info
                processes.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        # Sort by cpu_percent descending, take top 15
        processes.sort(key=lambda p: p.get("cpu_percent") or 0, reverse=True)
        metrics["top_processes"] = processes[:15]
    except Exception as e:
        logger.warning("Could not collect process list: %s", e)

    # System uptime
    try:
        boot_time = psutil.boot_time()
        uptime_seconds = time.time() - boot_time
        uptime_hours = round(uptime_seconds / 3600, 1)
        metrics["uptime_hours"] = uptime_hours
        metrics["uptime_human"] = (
            f"{int(uptime_hours // 24)}d {int(uptime_hours % 24)}h"
            if uptime_hours >= 24
            else f"{uptime_hours}h"
        )
    except OSError as e:
        logger.debug("Could not get boot time: %s", e)

    return metrics


def _collect_static_metrics(context: Dict[str, Any]) -> Dict[str, Any]:
    """Fallback: collect basic static OS info when psutil is unavailable."""
    metrics: Dict[str, Any] = {
        "platform": platform.system(),
        "platform_version": platform.version(),
        "cpu_count": os.cpu_count() or "unknown",
        "hostname": platform.node(),
        "psutil_available": False,
        "note": "Install psutil for real-time CPU, memory, disk, and process metrics.",
    }
    # Honour context-provided metrics if caller supplies them
    if "cpu_usage" in context:
        metrics["cpu_usage_percent"] = context["cpu_usage"]
    if "memory_usage" in context:
        metrics["memory_usage_percent"] = context["memory_usage"]
    if "disk_usage" in context:
        metrics["disk_usage_percent"] = context["disk_usage"]
    return metrics


class SystemMonitoringAgent(BaseAgent):
    """Agent specialized in system resource monitoring using real psutil metrics."""

    def __init__(self, llm_provider: LLMProvider):
        super().__init__(
            agent_id="system_monitoring",
            name="System Monitoring Agent",
            description="Monitors system resources including CPU, memory, disk usage, and processes using real metrics",
            llm_provider=llm_provider,
            capabilities=[
                "cpu_monitoring",
                "memory_monitoring",
                "disk_usage",
                "process_management",
                "system_health",
            ],
        )

    async def execute(self, task: str, context: Optional[Dict[str, Any]] = None) -> AgentResult:
        """
        Execute a system monitoring task using real psutil metrics.

        Context may include:
          - (no required fields — runs local system metrics collection automatically)
          - cpu_usage / memory_usage / disk_usage: override values if caller provides them
        """
        try:
            context = context or {}

            # Collect real metrics
            if _PSUTIL_AVAILABLE:
                import asyncio
                loop = asyncio.get_event_loop()
                # Run blocking psutil calls in executor to avoid blocking the event loop
                metrics = await loop.run_in_executor(None, _collect_psutil_metrics)
                metrics["psutil_available"] = True
            else:
                metrics = _collect_static_metrics(context)

            # Add static platform info alongside real metrics
            metrics["hostname"] = platform.node()
            metrics["platform"] = platform.system()
            metrics["platform_version"] = platform.version()

            # Generate LLM interpretation of real data
            import json

            from app.core.prompt_generator import get_prompt_generator

            prompt_gen = get_prompt_generator()
            enhanced_context = {**context, "metrics": metrics}
            prompts = prompt_gen.generate_agent_prompt(
                agent_id=self.agent_id, task=task, context=enhanced_context
            )

            analysis = await self._generate_response(
                prompt=(
                    f"{prompts['user_prompt']}\n\n"
                    f"Real system metrics collected:\n{json.dumps(metrics, indent=2, default=str)}\n\n"
                    "Based on this real data, provide: (1) current system health assessment, "
                    "(2) any concerning metrics or anomalies (high CPU, low disk, memory pressure), "
                    "(3) recommended actions if needed."
                ),
                system_prompt=prompts["system_prompt"],
                temperature=0.2,
            )

            monitoring_type = self._identify_monitoring_type(task)
            return self._format_result(
                success=True,
                output={
                    "summary": analysis[:200] + "..." if len(analysis) > 200 else analysis,
                    "analysis": analysis,
                    "monitoring_type": monitoring_type,
                    "metrics": metrics,
                    "psutil_available": _PSUTIL_AVAILABLE,
                },
                metadata={
                    "agent_id": self.agent_id,
                    "task": task,
                    "metrics_count": len(metrics),
                    "psutil_available": _PSUTIL_AVAILABLE,
                },
            )

        except Exception as e:
            logger.exception("System monitoring failed")
            return self._format_result(
                success=False,
                output={},
                error=f"System monitoring failed: {str(e)}",
                metadata={"agent_id": self.agent_id, "task": task},
            )

    def _identify_monitoring_type(self, task: str) -> str:
        """Identify the type of system monitoring needed."""
        task_lower = task.lower()
        if any(keyword in task_lower for keyword in ["cpu", "processor", "load"]):
            return "cpu_monitoring"
        elif any(keyword in task_lower for keyword in ["memory", "ram", "swap", "oom"]):
            return "memory_monitoring"
        elif any(keyword in task_lower for keyword in ["disk", "storage", "space", "inode"]):
            return "disk_monitoring"
        elif any(keyword in task_lower for keyword in ["process", "service", "application", "pid"]):
            return "process_monitoring"
        elif any(keyword in task_lower for keyword in ["health", "status", "overall"]):
            return "system_health"
        else:
            return "general_monitoring"
