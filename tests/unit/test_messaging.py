"""Unit tests for MessageBus (messaging module)."""

from datetime import datetime

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
            timestamp=datetime.utcnow(),
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
            timestamp=datetime.utcnow(),
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

    def test_subscribe_not_implemented(self):
        bus = MessageBus()
        with pytest.raises(NotImplementedError):
            bus.subscribe("task", lambda msg: None)

    def test_publish_not_implemented(self):
        bus = MessageBus()
        msg = Message(
            sender="a", recipient="b", message_type="t",
            payload={}, timestamp=datetime.utcnow()
        )
        with pytest.raises(NotImplementedError):
            bus.publish(msg)

    def test_get_history_not_implemented(self):
        bus = MessageBus()
        with pytest.raises(NotImplementedError):
            bus.get_history()
