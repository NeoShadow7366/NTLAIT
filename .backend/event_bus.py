"""Server-Sent Events (SSE) event bus — zero-dependency broadcast system.

Provides a thread-safe EventBus for publishing events from backend producers
(download manager, install jobs, batch worker, vault crawler, server status)
and streaming them to connected frontend clients via SSE.

Usage:
    # Producer (any thread):
    from event_bus import event_bus
    event_bus.emit("download_progress", {"id": "abc", "percent": 42})

    # Consumer (SSE handler in server.py):
    for event in event_bus.stream(last_id=client_last_id):
        send_sse(event)
"""
import threading
import time
import json
import collections
import logging


class EventBus:
    """Thread-safe event bus with cursor-based streaming for SSE clients.

    Events are stored in a bounded deque. Each event gets a monotonic ID.
    Clients track their last-seen ID and receive only new events.
    """

    def __init__(self, max_history: int = 500):
        self._lock = threading.Lock()
        self._events = collections.deque(maxlen=max_history)
        self._seq = 0
        self._condition = threading.Condition(self._lock)

    def emit(self, event_type: str, data: dict) -> int:
        """Publish an event. Thread-safe. Returns the event ID.

        Args:
            event_type: SSE event name (e.g. 'download_progress', 'server_status')
            data: JSON-serializable payload
        """
        with self._condition:
            self._seq += 1
            event = {
                "id": self._seq,
                "type": event_type,
                "data": data,
                "time": time.time()
            }
            self._events.append(event)
            self._condition.notify_all()
            return self._seq

    def get_since(self, last_id: int = 0) -> list:
        """Return all events with id > last_id. Non-blocking snapshot."""
        with self._lock:
            return [e for e in self._events if e["id"] > last_id]

    def wait_for_events(self, last_id: int = 0, timeout: float = 30.0) -> list:
        """Block until new events arrive or timeout. Returns events with id > last_id.

        Uses threading.Condition for efficient wake-up instead of polling.
        """
        deadline = time.time() + timeout
        with self._condition:
            while True:
                events = [e for e in self._events if e["id"] > last_id]
                if events:
                    return events
                remaining = deadline - time.time()
                if remaining <= 0:
                    return []
                self._condition.wait(timeout=min(remaining, 1.0))

    def latest_id(self) -> int:
        """Return the most recent event ID (for SSE Last-Event-ID reconnection)."""
        with self._lock:
            return self._seq

    @property
    def size(self) -> int:
        """Current number of events in the buffer."""
        with self._lock:
            return len(self._events)


# Module-level singleton — imported by producers and the SSE handler
event_bus = EventBus()


def format_sse(event: dict) -> bytes:
    """Format an event dict as an SSE text block.

    Returns bytes ready to write to wfile:
        id: 42
        event: download_progress
        data: {"id": "abc", "percent": 42}

    """
    lines = []
    lines.append(f"id: {event['id']}")
    lines.append(f"event: {event['type']}")
    lines.append(f"data: {json.dumps(event['data'])}")
    lines.append("")  # Blank line terminates the event
    lines.append("")
    return "\n".join(lines).encode("utf-8")
