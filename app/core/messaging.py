"""Message bus for agent coordination and communication."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional


@dataclass
class Message:
    """Message structure for agent communication."""

    sender: str
    recipient: str
    message_type: str
    payload: Dict[str, Any]
    timestamp: datetime
    message_id: Optional[str] = None


class MessageBus:
    """Message bus for agent-to-agent communication."""

    def __init__(self):
        """Initialize the message bus."""
        self._subscribers: Dict[str, List[Callable]] = {}
        self._message_history: List[Message] = []

    def subscribe(self, message_type: str, callback: Callable) -> None:
        """
        Subscribe to a message type.

        Args:
            message_type: Type of message to subscribe to
            callback: Callback function to invoke when message is received
        """
        if message_type not in self._subscribers:
            self._subscribers[message_type] = []
        self._subscribers[message_type].append(callback)

    def publish(self, message: Message) -> None:
        """
        Publish a message to subscribers.

        Args:
            message: Message to publish
        """
        self._message_history.append(message)
        for callback in self._subscribers.get(message.message_type, []):
            callback(message)

    def get_history(self, limit: Optional[int] = None) -> List[Message]:
        """
        Get message history.

        Args:
            limit: Optional limit on number of messages to return

        Returns:
            List of messages
        """
        if limit is None:
            return list(self._message_history)
        return list(self._message_history[-limit:])
