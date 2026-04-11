"""Unit tests for the SSE EventBus."""
import sys
import os
import time
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '.backend'))

from event_bus import EventBus, format_sse


class TestEventBus(unittest.TestCase):
    """Tests for EventBus emit, get_since, wait_for_events, and format_sse."""

    def setUp(self):
        self.bus = EventBus(max_history=10)

    def test_emit_returns_incrementing_ids(self):
        id1 = self.bus.emit("test", {"msg": "hello"})
        id2 = self.bus.emit("test", {"msg": "world"})
        self.assertEqual(id1, 1)
        self.assertEqual(id2, 2)

    def test_get_since_returns_new_events(self):
        self.bus.emit("a", {"v": 1})
        self.bus.emit("b", {"v": 2})
        self.bus.emit("c", {"v": 3})

        events = self.bus.get_since(last_id=1)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["type"], "b")
        self.assertEqual(events[1]["type"], "c")

    def test_get_since_zero_returns_all(self):
        self.bus.emit("x", {})
        self.bus.emit("y", {})
        events = self.bus.get_since(0)
        self.assertEqual(len(events), 2)

    def test_get_since_future_id_returns_empty(self):
        self.bus.emit("x", {})
        events = self.bus.get_since(last_id=999)
        self.assertEqual(len(events), 0)

    def test_max_history_evicts_old(self):
        for i in range(15):
            self.bus.emit("event", {"i": i})
        # max_history=10, so only 10 events should remain
        self.assertEqual(self.bus.size, 10)
        events = self.bus.get_since(0)
        # Should have events 6-15 (IDs 6-15)
        self.assertEqual(events[0]["id"], 6)

    def test_latest_id(self):
        self.assertEqual(self.bus.latest_id(), 0)
        self.bus.emit("test", {})
        self.assertEqual(self.bus.latest_id(), 1)
        self.bus.emit("test", {})
        self.assertEqual(self.bus.latest_id(), 2)

    def test_wait_for_events_returns_immediately_if_available(self):
        self.bus.emit("test", {"ready": True})
        events = self.bus.wait_for_events(last_id=0, timeout=1.0)
        self.assertEqual(len(events), 1)

    def test_wait_for_events_blocks_until_event(self):
        """Verify that wait_for_events blocks and returns when a new event is emitted."""
        results = []

        def waiter():
            events = self.bus.wait_for_events(last_id=0, timeout=5.0)
            results.extend(events)

        t = threading.Thread(target=waiter)
        t.start()

        # Small delay to ensure waiter is blocking
        time.sleep(0.1)
        self.bus.emit("async_event", {"from_thread": True})

        t.join(timeout=3.0)
        self.assertFalse(t.is_alive(), "Waiter thread should have returned")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["type"], "async_event")

    def test_wait_for_events_timeout_returns_empty(self):
        start = time.time()
        events = self.bus.wait_for_events(last_id=0, timeout=0.3)
        elapsed = time.time() - start
        self.assertEqual(len(events), 0)
        self.assertGreater(elapsed, 0.2, "Should have waited near timeout")

    def test_thread_safety_concurrent_emits(self):
        """Multiple threads emitting simultaneously should not corrupt state."""
        def emitter(prefix, count):
            for i in range(count):
                self.bus.emit(f"{prefix}_{i}", {"i": i})

        bus = EventBus(max_history=500)
        self.bus = bus

        threads = [threading.Thread(target=emitter, args=(f"t{n}", 50)) for n in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 5 threads × 50 events = 250 total
        self.assertEqual(bus.latest_id(), 250)
        events = bus.get_since(0)
        self.assertEqual(len(events), 250)

    def test_event_structure(self):
        self.bus.emit("download_progress", {"percent": 42})
        events = self.bus.get_since(0)
        event = events[0]
        self.assertIn("id", event)
        self.assertIn("type", event)
        self.assertIn("data", event)
        self.assertIn("time", event)
        self.assertEqual(event["type"], "download_progress")
        self.assertEqual(event["data"]["percent"], 42)


class TestFormatSSE(unittest.TestCase):
    """Tests for SSE text formatting."""

    def test_basic_format(self):
        event = {
            "id": 42,
            "type": "test_event",
            "data": {"msg": "hello"}
        }
        result = format_sse(event)
        self.assertIsInstance(result, bytes)
        text = result.decode("utf-8")
        self.assertIn("id: 42", text)
        self.assertIn("event: test_event", text)
        self.assertIn('data: {"msg": "hello"}', text)
        # Must end with double newline (SSE spec)
        self.assertTrue(text.endswith("\n\n"))

    def test_format_with_special_chars(self):
        event = {
            "id": 1,
            "type": "status",
            "data": {"message": "file: test.safetensors (42 GB)"}
        }
        result = format_sse(event)
        text = result.decode("utf-8")
        self.assertIn("test.safetensors", text)


if __name__ == "__main__":
    unittest.main()
