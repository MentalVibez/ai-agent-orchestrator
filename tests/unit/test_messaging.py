"""Unit tests for MessageBus (messaging module)."""

from datetime import datetime, timezone

import pytest

from app.core.messaging import Message, MessageBus


@pytest.mark.unit
class TestMessage:
    """Test Message dataclass."""

    def test_create_message(self):
        msg = Message(
            sender="agent1",
            recipient="agent2",
            message_type="task",
            payload={"data": "value"},
            timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        assert msg.sender == "agent1"
        assert msg.recipient == "agent2"
        assert msg.message_id is None

    def test_create_message_with_id(self):
        msg = Message(
            sender="a",
            recipient="b",
            message_type="result",
            payload={},
            timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
            message_id="msg-123",
        )
        assert msg.message_id == "msg-123"


@pytest.mark.unit
class TestMessageBus:
    """Test MessageBus class."""

    def test_init(self):
        bus = MessageBus()
        assert bus._subscribers == {}
        assert bus._message_history == []

    def test_subscribe_registers_callback(self):
        bus = MessageBus()
        cb = lambda msg: None
        bus.subscribe("task", cb)
        assert "task" in bus._subscribers
        assert cb in bus._subscribers["task"]

    def test_publish_stores_in_history(self):
        bus = MessageBus()
        msg = Message(
            sender="a", recipient="b", message_type="t",
            payload={}, timestamp=datetime.now(timezone.utc).replace(tzinfo=None)
        )
        bus.publish(msg)
        assert msg in bus._message_history

    def test_publish_invokes_subscriber(self):
        bus = MessageBus()
        received = []
        bus.subscribe("task", lambda m: received.append(m))
        msg = Message(
            sender="a", recipient="b", message_type="task",
            payload={"x": 1}, timestamp=datetime.now(timezone.utc).replace(tzinfo=None)
        )
        bus.publish(msg)
        assert received == [msg]

    def test_publish_no_subscriber_does_not_raise(self):
        bus = MessageBus()
        msg = Message(
            sender="a", recipient="b", message_type="unknown",
            payload={}, timestamp=datetime.now(timezone.utc).replace(tzinfo=None)
        )
        bus.publish(msg)  # should not raise

    def test_get_history_returns_all(self):
        bus = MessageBus()
        for i in range(5):
            bus.publish(Message("a", "b", "t", {"i": i}, datetime.now(timezone.utc).replace(tzinfo=None)))
        assert len(bus.get_history()) == 5

    def test_get_history_with_limit(self):
        bus = MessageBus()
        for i in range(10):
            bus.publish(Message("a", "b", "t", {"i": i}, datetime.now(timezone.utc).replace(tzinfo=None)))
        result = bus.get_history(limit=3)
        assert len(result) == 3
        assert result[-1].payload["i"] == 9
