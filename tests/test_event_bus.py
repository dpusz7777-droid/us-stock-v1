# -*- coding: utf-8 -*-
"""EventBus 测试。"""

from __future__ import annotations

import unittest
from typing import Any

from event_bus import EventBus, EventLogEntry, event_bus, dashboard_listener, _DashboardEventListener
from events import (
    MARKET_DATA_UPDATED,
    PORTFOLIO_UPDATED,
    BROKER_SNAPSHOT_UPDATED,
    BRIEFING_GENERATED,
    DASHBOARD_REFRESH,
    SYSTEM_HEALTH_CHECK,
    ERROR_OCCURRED,
    ALL_EVENTS,
)


class TestEventBusCore(unittest.TestCase):
    def setUp(self) -> None:
        self.bus = EventBus()

    def test_subscribe_and_publish(self) -> None:
        results: list[str] = []
        def handler(data: Any) -> None:
            results.append(data)
        self.bus.subscribe("TEST_EVENT", handler)
        self.bus.publish("TEST_EVENT", "hello")
        self.assertEqual(results, ["hello"])

    def test_multiple_handlers(self) -> None:
        results: list[int] = []
        def add1(data: Any) -> None:
            results.append(1)
        def add2(data: Any) -> None:
            results.append(2)
        self.bus.subscribe("TEST", add1)
        self.bus.subscribe("TEST", add2)
        self.bus.publish("TEST")
        self.assertEqual(results, [1, 2])

    def test_handler_exception_does_not_affect_others(self) -> None:
        results: list[str] = []
        def failing(data: Any) -> None:
            raise ValueError("handler failure")
        def good(data: Any) -> None:
            results.append("ok")
        self.bus.subscribe("TEST", failing)
        self.bus.subscribe("TEST", good)
        self.bus.publish("TEST")
        # good handler must have executed
        self.assertEqual(results, ["ok"])
        # event_log should record the failure
        self.assertEqual(len(self.bus.event_log), 1)
        entry = self.bus.event_log[0]
        self.assertEqual(entry.fail_count, 1)
        self.assertEqual(entry.success_count, 1)

    def test_unsubscribe(self) -> None:
        results: list[str] = []
        def handler(data: Any) -> None:
            results.append("called")
        self.bus.subscribe("TEST", handler)
        self.bus.unsubscribe("TEST", handler)
        self.bus.publish("TEST")
        self.assertEqual(results, [])

    def test_unsubscribe_nonexistent(self) -> None:
        """Unsubscribe non-existent handler should not raise."""
        def handler(data: Any) -> None:
            pass
        # Should not raise
        self.bus.unsubscribe("NONEXISTENT", handler)

    def test_unsubscribe_nonexistent_handler(self) -> None:
        def h1(data: Any) -> None:
            pass
        def h2(data: Any) -> None:
            pass
        self.bus.subscribe("TEST", h1)
        # Removing h2 when only h1 is registered
        self.bus.unsubscribe("TEST", h2)
        self.assertEqual(len(self.bus.list_events()), 1)

    def test_clear_event(self) -> None:
        def handler(data: Any) -> None:
            pass
        self.bus.subscribe("TEST", handler)
        self.bus.clear("TEST")
        self.assertNotIn("TEST", self.bus.list_events())

    def test_clear_all(self) -> None:
        def handler(data: Any) -> None:
            pass
        self.bus.subscribe("A", handler)
        self.bus.subscribe("B", handler)
        self.bus.clear()
        self.assertEqual(self.bus.list_events(), [])

    def test_list_events(self) -> None:
        def handler(data: Any) -> None:
            pass
        self.bus.subscribe("ALPHA", handler)
        self.bus.subscribe("BETA", handler)
        self.assertEqual(self.bus.list_events(), ["ALPHA", "BETA"])

    def test_publish_no_handlers(self) -> None:
        """Publishing with no subscribers should not raise."""
        self.bus.publish("NONEXISTENT", {"data": 1})
        self.assertEqual(len(self.bus.event_log), 1)

    def test_subscribe_non_callable_raises(self) -> None:
        with self.assertRaises(TypeError):
            self.bus.subscribe("TEST", "not_callable")

    def test_handler_exception_type_error(self) -> None:
        results: list[str] = []
        def handler(data: Any) -> None:
            raise TypeError("wrong type")
        def good(data: Any) -> None:
            results.append("ok")
        self.bus.subscribe("TEST", handler)
        self.bus.subscribe("TEST", good)
        self.bus.publish("TEST", "data")
        self.assertEqual(results, ["ok"])
        entry = self.bus.event_log[-1]
        self.assertGreater(entry.fail_count, 0)

    def test_publish_with_none_data(self) -> None:
        results: list[str] = []
        def handler(data: Any) -> None:
            results.append(str(data))
        self.bus.subscribe("TEST", handler)
        self.bus.publish("TEST")
        self.assertEqual(results, ["None"])

    def test_publish_with_dict_data(self) -> None:
        results: list[dict] = []
        def handler(data: Any) -> None:
            results.append(data)
        self.bus.subscribe("TEST", handler)
        self.bus.publish("TEST", {"key": "value", "num": 42})
        self.assertEqual(results, [{"key": "value", "num": 42}])


class TestEventLog(unittest.TestCase):
    def setUp(self) -> None:
        self.bus = EventBus()

    def test_log_created_on_publish(self) -> None:
        def handler(data: Any) -> None:
            pass
        self.bus.subscribe("TEST", handler)
        self.bus.publish("TEST", "payload")
        self.assertEqual(len(self.bus.event_log), 1)

    def test_log_contains_entry_fields(self) -> None:
        def handler(data: Any) -> None:
            pass
        self.bus.subscribe("TEST", handler)
        self.bus.publish("TEST", "data")
        entry = self.bus.event_log[0]
        self.assertTrue(entry.timestamp.startswith("202"))
        self.assertEqual(entry.event_name, "TEST")
        self.assertEqual(entry.payload_summary, "data")
        self.assertEqual(entry.handler_count, 1)
        self.assertEqual(entry.success_count, 1)
        self.assertEqual(entry.fail_count, 0)

    def test_log_limits_size(self) -> None:
        def handler(data: Any) -> None:
            pass
        self.bus.subscribe("TEST", handler)
        # Publish many times to overflow
        for i in range(1500):
            self.bus.publish("TEST", i)
        self.assertLessEqual(len(self.bus.event_log), 1000)

    def test_clear_log(self) -> None:
        def handler(data: Any) -> None:
            pass
        self.bus.subscribe("TEST", handler)
        self.bus.publish("TEST")
        self.bus.clear_log()
        self.assertEqual(self.bus.event_log, [])

    def test_log_entry_to_dict(self) -> None:
        entry = EventLogEntry(
            timestamp="2026-06-30T12:00:00",
            event_name="TEST",
            payload_summary="data",
            handler_count=2,
            success_count=1,
            fail_count=1,
            error_messages=["err1"],
        )
        d = entry.to_dict()
        self.assertEqual(d["event_name"], "TEST")
        self.assertEqual(d["success_count"], 1)
        self.assertEqual(d["fail_count"], 1)
        self.assertEqual(d["error_messages"], ["err1"])

    def test_log_repr(self) -> None:
        entry = EventLogEntry("ts", "TEST", "data", 2, 1, 1, [])
        r = repr(entry)
        self.assertIn("TEST", r)
        self.assertIn("handlers=2", r)


class TestDashboardListener(unittest.TestCase):
    def setUp(self) -> None:
        self.listener = _DashboardEventListener()
        self.bus = EventBus()

    def test_subscribe_all_events(self) -> None:
        self.listener.subscribe_all(self.bus)
        events = self.bus.list_events()
        for event_name in ALL_EVENTS:
            self.assertIn(event_name, events)

    def test_record_event_time(self) -> None:
        self.listener.subscribe_all(self.bus)
        self.bus.publish(MARKET_DATA_UPDATED, {"symbols": ["AAPL"]})
        time_str = self.listener.last_event_time(MARKET_DATA_UPDATED)
        self.assertIsNotNone(time_str)
        self.assertTrue(time_str.startswith("202"))

    def test_all_times_property(self) -> None:
        self.listener.subscribe_all(self.bus)
        self.bus.publish(PORTFOLIO_UPDATED)
        self.bus.publish(DASHBOARD_REFRESH)
        times = self.listener.all_times
        self.assertIn(PORTFOLIO_UPDATED, times)
        self.assertIn(DASHBOARD_REFRESH, times)

    def test_no_crash_on_unknown_event(self) -> None:
        """Dashboard listener should not crash on events it didn't subscribe to."""
        # Just call without subscribing
        self.bus.publish("UNKNOWN_EVENT", {"data": 1})
        # Should not raise


class TestStandardEvents(unittest.TestCase):
    def test_all_events_is_frozenset(self) -> None:
        self.assertIsInstance(ALL_EVENTS, frozenset)

    def test_all_events_contains_standard_names(self) -> None:
        standard = [
            "MARKET_DATA_UPDATED",
            "BROKER_SNAPSHOT_UPDATED",
            "BRIEFING_GENERATED",
            "PORTFOLIO_UPDATED",
            "DASHBOARD_REFRESH",
            "SYSTEM_HEALTH_CHECK",
            "ERROR_OCCURRED",
        ]
        for name in standard:
            self.assertIn(name, ALL_EVENTS)

    def test_event_constants_match(self) -> None:
        self.assertEqual(MARKET_DATA_UPDATED, "MARKET_DATA_UPDATED")
        self.assertEqual(BRIEFING_GENERATED, "BRIEFING_GENERATED")


class TestGlobalSingleton(unittest.TestCase):
    def tearDown(self) -> None:
        event_bus.clear()
        event_bus.clear_log()

    def test_event_bus_is_singleton(self) -> None:
        from event_bus import event_bus as eb1
        from event_bus import event_bus as eb2
        self.assertIs(eb1, eb2)

    def test_dashboard_listener_is_singleton(self) -> None:
        from event_bus import dashboard_listener as dl1
        from event_bus import dashboard_listener as dl2
        self.assertIs(dl1, dl2)

    def test_event_bus_has_no_network(self) -> None:
        """Verify EventBus source has no network imports."""
        with open("event_bus.py", "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        import_lines = [l.strip() for l in lines if l.strip().startswith("import ") or l.strip().startswith("from ")]
        import_text = "\n".join(import_lines).lower()
        for lib in ["socket", "http", "requests", "threading", "thread"]:
            with self.subTest(lib=lib):
                self.assertNotIn(lib, import_text)

    def test_event_bus_has_no_file_write(self) -> None:
        """Verify EventBus doesn't write files."""
        with open("event_bus.py", "r", encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn(".write(", source)
        self.assertNotIn("open(", source)

    def test_dashboard_listener_no_side_effects(self) -> None:
        """Dashboard listener should not modify EventBus's core behavior."""
        results: list[str] = []
        def handler(data: Any) -> None:
            results.append("original")
        event_bus.subscribe(MARKET_DATA_UPDATED, handler)
        dashboard_listener.subscribe_all(event_bus)
        event_bus.publish(MARKET_DATA_UPDATED)
        self.assertIn("original", results)
        # Dashboard listener should have recorded the time
        self.assertIsNotNone(dashboard_listener.last_event_time(MARKET_DATA_UPDATED))


class TestPayloadSummary(unittest.TestCase):
    def test_none_summary(self) -> None:
        summary = EventBus._summarize_payload(None)
        self.assertEqual(summary, "None")

    def test_dict_summary(self) -> None:
        summary = EventBus._summarize_payload({"a": 1, "b": 2})
        self.assertEqual(summary, "dict(keys=['a', 'b'])")

    def test_list_summary(self) -> None:
        summary = EventBus._summarize_payload([1, 2, 3])
        self.assertEqual(summary, "list(len=3)")

    def test_long_string_truncated(self) -> None:
        long_str = "x" * 200
        summary = EventBus._summarize_payload(long_str)
        self.assertLessEqual(len(summary), 80)


if __name__ == "__main__":
    unittest.main()