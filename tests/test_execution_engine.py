# -*- coding: utf-8 -*-
"""ExecutionEngine 测试。"""

from __future__ import annotations

import time
import unittest
from decimal import Decimal
from typing import Any

from decision_engine import Decision, DecisionAction, DecisionEngine
from event_bus import event_bus
from events import ORDER_FILLED, ORDER_REJECTED
from execution_engine import ExecutionEngine, ExecutionResult, OrderStatus, execution_engine
from signal_engine import Signal, SignalType


def _make_decision(
    symbol: str = "AAPL",
    action: DecisionAction = DecisionAction.BUY,
    confidence: float = 0.8,
    risk_level: str = "LOW",
) -> Decision:
    return Decision(
        symbol=symbol,
        action=action,
        confidence=confidence,
        reason="test decision",
        risk_level=risk_level,
        signal_type=action.value,
        original_signal_type=action.value,
    )


class TestOrderStatus(unittest.TestCase):
    def test_status_values(self) -> None:
        self.assertEqual(OrderStatus.PENDING.value, "PENDING")
        self.assertEqual(OrderStatus.FILLED.value, "FILLED")
        self.assertEqual(OrderStatus.REJECTED.value, "REJECTED")
        self.assertEqual(OrderStatus.PARTIAL.value, "PARTIAL")


class TestExecutionResult(unittest.TestCase):
    def test_minimal_result(self) -> None:
        r = ExecutionResult(
            order_id="SIM-000001", symbol="AAPL",
            action="BUY", status=OrderStatus.FILLED,
        )
        self.assertEqual(r.order_id, "SIM-000001")
        self.assertEqual(r.status, OrderStatus.FILLED)

    def test_immutable(self) -> None:
        r = ExecutionResult(
            order_id="SIM-001", symbol="AAPL",
            action="BUY", status=OrderStatus.FILLED,
        )
        with self.assertRaises(AttributeError):
            r.status = OrderStatus.REJECTED

    def test_to_dict(self) -> None:
        r = ExecutionResult(
            order_id="SIM-001", symbol="AAPL",
            action="BUY", status=OrderStatus.FILLED,
            fill_price=Decimal("150.25"),
            slippage=Decimal("0.0005"),
            filled_qty=Decimal("100"),
        )
        d = r.to_dict()
        self.assertEqual(d["order_id"], "SIM-001")
        self.assertEqual(d["fill_price"], "150.25")
        self.assertEqual(d["slippage"], "0.0005")
        self.assertEqual(d["filled_qty"], "100")
        self.assertEqual(d["status"], "FILLED")

    def test_to_dict_none_values(self) -> None:
        r = ExecutionResult(
            order_id="SIM-002", symbol="AAPL",
            action="BLOCKED", status=OrderStatus.REJECTED,
            reject_reason="blocked",
        )
        d = r.to_dict()
        self.assertIsNone(d["fill_price"])

    def test_repr(self) -> None:
        r = ExecutionResult(
            order_id="SIM-001", symbol="AAPL",
            action="BUY", status=OrderStatus.FILLED,
        )
        rep = repr(r)
        self.assertIn("SIM-001", rep)
        self.assertIn("FILLED", rep)


class TestExecutionEngineSubmit(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = ExecutionEngine(deterministic=True, seed=42)
        self.market_price = Decimal("150.00")

    def test_buy_fill(self) -> None:
        decision = _make_decision("AAPL", DecisionAction.BUY)
        result = self.engine.submit_order(decision, self.market_price, Decimal("100"))
        self.assertIsNotNone(result)
        self.assertEqual(result.status, OrderStatus.FILLED)
        self.assertEqual(result.filled_qty, Decimal("100"))
        self.assertIsNotNone(result.fill_price)
        self.assertGreater(result.fill_price, self.market_price)  # buy + slippage

    def test_sell_fill(self) -> None:
        decision = _make_decision("AAPL", DecisionAction.SELL)
        result = self.engine.submit_order(decision, self.market_price, Decimal("100"))
        self.assertIsNotNone(result)
        self.assertEqual(result.status, OrderStatus.FILLED)
        self.assertLess(result.fill_price, self.market_price)  # sell - slippage

    def test_blocked_rejected(self) -> None:
        decision = _make_decision("AAPL", DecisionAction.BLOCKED)
        result = self.engine.submit_order(decision, self.market_price)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, OrderStatus.REJECTED)
        self.assertIn("BLOCKED", result.reject_reason)

    def test_hold_noop(self) -> None:
        decision = _make_decision("AAPL", DecisionAction.HOLD)
        result = self.engine.submit_order(decision, self.market_price)
        self.assertIsNone(result)

    def test_reduce_partial(self) -> None:
        decision = _make_decision("AAPL", DecisionAction.REDUCE)
        result = self.engine.submit_order(decision, self.market_price, Decimal("100"))
        self.assertIsNotNone(result)
        self.assertEqual(result.status, OrderStatus.PARTIAL)
        self.assertLess(result.filled_qty, Decimal("100"))
        self.assertGreater(result.filled_qty, Decimal("0"))

    def test_buy_slippage_in_range(self) -> None:
        """滑点必须在 0~0.1% 范围内。"""
        for _ in range(20):
            decision = _make_decision("AAPL", DecisionAction.BUY)
            result = self.engine.submit_order(decision, self.market_price, Decimal("100"))
            if result and result.slippage is not None:
                self.assertGreaterEqual(result.slippage, Decimal("0"))
                self.assertLessEqual(result.slippage, Decimal("0.001"))

    def test_sell_slippage_in_range(self) -> None:
        for _ in range(20):
            decision = _make_decision("AAPL", DecisionAction.SELL)
            result = self.engine.submit_order(decision, self.market_price, Decimal("100"))
            if result and result.slippage is not None:
                self.assertGreaterEqual(result.slippage, Decimal("0"))
                self.assertLessEqual(result.slippage, Decimal("0.001"))

    def test_order_id_increments(self) -> None:
        decision = _make_decision("AAPL", DecisionAction.BUY)
        r1 = self.engine.submit_order(decision, self.market_price)
        r2 = self.engine.submit_order(decision, self.market_price)
        if r1 and r2:
            self.assertNotEqual(r1.order_id, r2.order_id)
            id1 = int(r1.order_id.split("-")[1])
            id2 = int(r2.order_id.split("-")[1])
            self.assertLess(id1, id2)

    def test_latency_positive(self) -> None:
        decision = _make_decision("AAPL", DecisionAction.BUY)
        result = self.engine.submit_order(decision, self.market_price, Decimal("100"))
        if result:
            self.assertGreaterEqual(result.latency_ms, 0)


class TestExecutionEngineDirect(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = ExecutionEngine(deterministic=True)

    def test_simulate_fill(self) -> None:
        decision = _make_decision("AAPL", DecisionAction.BUY)
        result = self.engine.simulate_fill(decision, Decimal("150.00"), Decimal("100"))
        self.assertEqual(result.status, OrderStatus.FILLED)
        self.assertEqual(result.fill_price, Decimal("150.00"))
        self.assertEqual(result.slippage, Decimal("0"))
        self.assertEqual(result.filled_qty, Decimal("100"))

    def test_reject_order(self) -> None:
        decision = _make_decision("AAPL", DecisionAction.BUY)
        result = self.engine.reject_order(decision, "Manual test reject")
        self.assertEqual(result.status, OrderStatus.REJECTED)
        self.assertIn("Manual test", result.reject_reason)

    def test_partial_fill(self) -> None:
        decision = _make_decision("AAPL", DecisionAction.BUY)
        result = self.engine.partial_fill(decision, Decimal("150.00"), Decimal("0.5"))
        self.assertEqual(result.status, OrderStatus.PARTIAL)
        self.assertEqual(result.filled_qty, Decimal("50"))

    def test_partial_fill_custom_ratio(self) -> None:
        decision = _make_decision("AAPL", DecisionAction.BUY)
        result = self.engine.partial_fill(decision, Decimal("150.00"), Decimal("0.75"))
        self.assertEqual(result.status, OrderStatus.PARTIAL)
        self.assertEqual(result.filled_qty, Decimal("75"))


class TestExecutionDeterministic(unittest.TestCase):
    def test_deterministic_mode_consistent(self) -> None:
        e1 = ExecutionEngine(deterministic=True, seed=42)
        e2 = ExecutionEngine(deterministic=True, seed=42)
        market = Decimal("150.00")
        decision = _make_decision("AAPL", DecisionAction.BUY)
        r1 = e1.submit_order(decision, market, Decimal("100"))
        r2 = e2.submit_order(decision, market, Decimal("100"))
        if r1 and r2:
            self.assertEqual(r1.fill_price, r2.fill_price)
            self.assertEqual(r1.slippage, r2.slippage)

    def test_deterministic_flag(self) -> None:
        eng = ExecutionEngine(deterministic=True)
        self.assertTrue(eng.deterministic)

    def test_set_seed(self) -> None:
        eng = ExecutionEngine(deterministic=True, seed=42)
        eng.set_seed(99)
        self.assertTrue(eng.deterministic)


class TestEventBusIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = ExecutionEngine(deterministic=True)
        event_bus.clear()
        event_bus.clear_log()

    def test_order_filled_event(self) -> None:
        received: list[dict] = []
        def listener(data: Any) -> None:
            received.append(data)
        event_bus.subscribe(ORDER_FILLED, listener)
        decision = _make_decision("AAPL", DecisionAction.BUY)
        self.engine.submit_order(decision, Decimal("150.00"), Decimal("100"))
        self.assertTrue(len(received) > 0)
        self.assertIn("execution_result", received[0])
        self.assertEqual(received[0]["execution_result"]["status"], "FILLED")

    def test_order_rejected_event(self) -> None:
        received: list[dict] = []
        def listener(data: Any) -> None:
            received.append(data)
        event_bus.subscribe(ORDER_REJECTED, listener)
        decision = _make_decision("AAPL", DecisionAction.BLOCKED)
        self.engine.submit_order(decision, Decimal("150.00"))
        self.assertTrue(len(received) > 0)
        self.assertEqual(received[0]["execution_result"]["status"], "REJECTED")


class TestNoBrokerOrAPI(unittest.TestCase):
    def test_no_network_imports(self) -> None:
        with open("execution_engine.py", "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        import_lines = [l.strip() for l in lines if l.strip().startswith("import ") or l.strip().startswith("from ")]
        import_text = "\n".join(import_lines).lower()
        for lib in ["socket", "http", "requests", "yfinance"]:
            with self.subTest(lib=lib):
                self.assertNotIn(lib, import_text)

    def test_no_trade_methods(self) -> None:
        """Must not have order execution methods to real brokers."""
        for name in dir(ExecutionEngine):
            lower = name.lower()
            if "connect" in lower or "login" in lower or "api" in lower:
                self.fail(f"ExecutionEngine has forbidden method: {name}")


class TestGlobalSingleton(unittest.TestCase):
    def test_execution_engine_is_singleton(self) -> None:
        from execution_engine import execution_engine as ee1
        from execution_engine import execution_engine as ee2
        self.assertIs(ee1, ee2)


if __name__ == "__main__":
    unittest.main()