"""Unit tests for app/core/agent_bus.py."""

import pytest

from app.core.agent_bus import AgentMessageBus, get_agent_bus


@pytest.mark.unit
class TestAgentMessageBus:
    """Tests for AgentMessageBus."""

    @pytest.mark.asyncio
    async def test_publish_and_receive(self):
        """publish() enqueues a message that receive() returns."""
        bus = AgentMessageBus()
        msg = {"type": "alert", "host": "server1"}
        await bus.publish("agent-a", msg)
        received = await bus.receive("agent-a", timeout=1.0)
        assert received == msg

    @pytest.mark.asyncio
    async def test_receive_timeout_returns_none(self):
        """receive() returns None when no message arrives within timeout."""
        bus = AgentMessageBus()
        result = await bus.receive("agent-b", timeout=0.05)
        assert result is None

    @pytest.mark.asyncio
    async def test_publish_to_multiple_agents_isolates_queues(self):
        """Messages are delivered only to the target agent's queue."""
        bus = AgentMessageBus()
        await bus.publish("agent-x", {"data": "for-x"})
        await bus.publish("agent-y", {"data": "for-y"})
        msg_x = await bus.receive("agent-x", timeout=1.0)
        msg_y = await bus.receive("agent-y", timeout=1.0)
        assert msg_x == {"data": "for-x"}
        assert msg_y == {"data": "for-y"}

    def test_subscribe_returns_queue(self):
        """subscribe() returns the asyncio.Queue for the agent."""
        import asyncio
        bus = AgentMessageBus()
        q = bus.subscribe("agent-z")
        assert isinstance(q, asyncio.Queue)

    def test_subscribe_same_agent_returns_same_queue(self):
        """subscribe() called twice for the same agent returns the same queue object."""
        bus = AgentMessageBus()
        q1 = bus.subscribe("agent-z")
        q2 = bus.subscribe("agent-z")
        assert q1 is q2

    def test_clear_removes_queue(self):
        """clear() removes the agent's queue so a fresh one is created next time."""
        bus = AgentMessageBus()
        q1 = bus.subscribe("agent-c")
        bus.clear("agent-c")
        q2 = bus.subscribe("agent-c")
        assert q1 is not q2  # Fresh queue after clear

    def test_clear_nonexistent_agent_is_safe(self):
        """clear() on an unknown agent_id does not raise."""
        bus = AgentMessageBus()
        bus.clear("does-not-exist")  # Should not raise

    def test_get_agent_bus_returns_singleton(self):
        """get_agent_bus() returns the module-level singleton."""
        bus1 = get_agent_bus()
        bus2 = get_agent_bus()
        assert bus1 is bus2
