"""Multi-agent peer communication via an in-process async message bus."""

import asyncio
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class AgentMessageBus:
    """
    Simple in-process pub/sub message bus for agent-to-agent communication.
    Each agent gets its own asyncio.Queue; messages are dicts.
    """

    def __init__(self) -> None:
        self._queues: Dict[str, asyncio.Queue] = {}

    def _get_or_create_queue(self, agent_id: str) -> asyncio.Queue:
        if agent_id not in self._queues:
            self._queues[agent_id] = asyncio.Queue()
        return self._queues[agent_id]

    async def publish(self, target_agent_id: str, message: dict) -> None:
        """
        Send a message to target_agent_id's queue.

        Args:
            target_agent_id: Recipient agent identifier
            message: Arbitrary dict payload
        """
        queue = self._get_or_create_queue(target_agent_id)
        await queue.put(message)
        logger.debug("AgentBus: message published to %s", target_agent_id)

    async def receive(self, agent_id: str, timeout: float = 5.0) -> Optional[dict]:
        """
        Receive the next message for agent_id, waiting up to `timeout` seconds.

        Args:
            agent_id: Consuming agent identifier
            timeout: Seconds to wait before returning None

        Returns:
            Message dict or None on timeout
        """
        queue = self._get_or_create_queue(agent_id)
        try:
            return await asyncio.wait_for(queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def subscribe(self, agent_id: str) -> asyncio.Queue:
        """
        Return the asyncio.Queue for agent_id (creating if needed).
        Callers can await queue.get() directly for more control.
        """
        return self._get_or_create_queue(agent_id)

    def clear(self, agent_id: str) -> None:
        """Drain and remove the queue for agent_id (for cleanup/testing)."""
        if agent_id in self._queues:
            del self._queues[agent_id]


# Module-level singleton
_bus = AgentMessageBus()


def get_agent_bus() -> AgentMessageBus:
    """Get the global AgentMessageBus instance."""
    return _bus
