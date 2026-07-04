# -*- coding: utf-8 -*-
"""ExecutionEngine 测试 — V4 Phase 0 (Paper Execution Layer)."""

from __future__ import annotations

import time
import unittest
from decimal import Decimal
from typing import Any

from decision_engine import Decision, DecisionAction, DecisionEngine
from event_bus import event_bus
from events import ORDER_SUBMITTED, ORDER_FILLED, ORDER_REJECTED
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


# ======================================================================
# OrderStatus
# ======================================================================


class TestOrderStatus(unittest.TestCase):
    def test_status_values(self) -> None:
        self.assertEqual(OrderStatus.PENDING.value, "PENDING")
        self.assertEqual(OrderStatus.FILLED.value, "FILLED")
        self.assertEqual(OrderStatus.REJECTED.value, "REJECTED")
        self.assertEqual(OrderStatus.PARTIAL.value, "PARTIAL")
        self.assertEqual(OrderStatus.NO_OP.value, "NO_OP")

    def test_no_op_in_enum(self) -> None:
        """验证 NO_OP 是 OrderStatus 合法成员。"""
        self.assertIn(OrderStatus.NO_OP, OrderStatus)


# ======================================================================
# ExecutionResult
# ======================================================================


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

    def test_to_dict_filled(self) -> None:
        r = ExecutionResult(
            order_id="SIM-001", symbol="AAPL",
            action="BUY", status=OrderStatus.FILLED,
            fill_price=Decimal("150.25"),
            slippage=Decimal("0.002"),
            filled_qty=Decimal("100"),
        )
        d = r.to_dict()
        self.assertEqual(d["order_id"], "SIM-001")
        self.assertEqual(d["fill_price"], "150.25")
        self.assertEqual(d["slippage"], "0.002")
        self.assertEqual(d["filled_qty"], "100")
        self.assertEqual(d["status"], "FILLED")

    def test_to_dict_rejected(self) -> None:
        r = ExecutionResult(
            order_id="SIM-002", symbol="AAPL",
            action="BLOCKED", status=OrderStatus.REJECTED,
            reject_reason="blocked by risk",
        )
        d = r.to_dict()
        self.assertIsNone(d["fill_price"])
        self.assertEqual(d["status"], "REJECTED")
        self.assertEqual(d["reject_reason"], "blocked by risk")

    def test_to_dict_no_op(self) -> None:
        r = ExecutionResult(
            order_id="SIM-003", symbol="AAPL",
            action="HOLD", status=OrderStatus.NO_OP,
        )
        d = r.to_dict()
        self.assertEqual(d["status"], "NO_OP")
        self.assertIsNone(d["fill_price"])

    def test_to_dict_partial(self) -> None:
        r = ExecutionResult(
            order_id="SIM-004", symbol="AAPL",
            action="REDUCE", status=OrderStatus.PARTIAL,
            fill_price=Decimal("149.80"),
            filled_qty=Decimal("50"),
            requested_qty=Decimal("100"),
        )
        d = r.to_dict()
        self.assertEqual(d["status"], "PARTIAL")
        self.assertEqual(d["filled_qty"], "50")

    def test_repr(self) -> None:
        r = ExecutionResult(
            order_id="SIM-001", symbol="AAPL",
            action="BUY", status=OrderStatus.FILLED,
        )
        rep = repr(r)
        self.assertIn("SIM-001", rep)
        self.assertIn("FILLED", rep)

    def test_no_op_repr(self) -> None:
        r = ExecutionResult(
            order_id="SIM-005", symbol="AAPL",
            action="HOLD", status=OrderStatus.NO_OP,
        )
        rep = repr(r)
        self.assertIn("NO_OP", rep)


# ======================================================================
# submit_order — 核心交易场景
# ======================================================================


class TestExecutionEngineSubmit(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = ExecutionEngine(deterministic=True, seed=42)
        self.market_price = Decimal("150.00")

    def test_buy_fill(self) -> None:
        """BUY 必须返回 FILLED，成交价 > 市价（含滑点）。"""
        decision = _make_decision("AAPL", DecisionAction.BUY)
        result = self.engine.submit_order(decision, self.market_price, Decimal("100"))
        self.assertIsNotNone(result)
        self.assertEqual(result.status, OrderStatus.FILLED)
        self.assertEqual(result.filled_qty, Decimal("100"))
        self.assertIsNotNone(result.fill_price)
        self.assertGreater(result.fill_price, self.market_price)  # buy + slippage

    def test_sell_fill(self) -> None:
        """SELL 必须返回 FILLED，成交价 < 市价（含滑点）。"""
        decision = _make_decision("AAPL", DecisionAction.SELL)
        result = self.engine.submit_order(decision, self.market_price, Decimal("100"))
        self.assertIsNotNone(result)
        self.assertEqual(result.status, OrderStatus.FILLED)
        self.assertLess(result.fill_price, self.market_price)  # sell - slippage

    def test_buy_fill_price_in_range(self) -> None:
        """BUY 成交价必须在 market_price * 1.001 ~ market_price * 1.003 之间。"""
        for _ in range(50):
            decision = _make_decision("AAPL", DecisionAction.BUY)
            result = self.engine.submit_order(decision, self.market_price, Decimal("100"))
            self.assertEqual(result.status, OrderStatus.FILLED)
            lower = self.market_price * Decimal("1.001")
            upper = self.market_price * Decimal("1.003")
            self.assertGreaterEqual(result.fill_price, lower)
            self.assertLessEqual(result.fill_price, upper)

    def test_sell_fill_price_in_range(self) -> None:
        """SELL 成交价必须在 market_price * 0.997 ~ market_price * 0.999 之间。"""
        for _ in range(50):
            decision = _make_decision("AAPL", DecisionAction.SELL)
            result = self.engine.submit_order(decision, self.market_price, Decimal("100"))
            self.assertEqual(result.status, OrderStatus.FILLED)
            lower = self.market_price * Decimal("0.997")
            upper = self.market_price * Decimal("0.999")
            self.assertGreaterEqual(result.fill_price, lower)
            self.assertLessEqual(result.fill_price, upper)

    def test_buy_slippage_in_range(self) -> None:
        """滑点必须在 0.1%~0.3% 范围内。"""
        for _ in range(50):
            decision = _make_decision("AAPL", DecisionAction.BUY)
            result = self.engine.submit_order(decision, self.market_price, Decimal("100"))
            self.assertIsNotNone(result.slippage)
            self.assertGreaterEqual(result.slippage, Decimal("0.001"))
            self.assertLessEqual(result.slippage, Decimal("0.003"))

    def test_sell_slippage_in_range(self) -> None:
        for _ in range(50):
            decision = _make_decision("AAPL", DecisionAction.SELL)
            result = self.engine.submit_order(decision, self.market_price, Decimal("100"))
            self.assertIsNotNone(result.slippage)
            self.assertGreaterEqual(result.slippage, Decimal("0.001"))
            self.assertLessEqual(result.slippage, Decimal("0.003"))

    def test_blocked_rejected(self) -> None:
        """BLOCKED 必须返回 REJECTED。"""
        decision = _make_decision("AAPL", DecisionAction.BLOCKED)
        result = self.engine.submit_order(decision, self.market_price)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, OrderStatus.REJECTED)
        self.assertIn("BLOCKED", result.reject_reason)

    def test_hold_no_op(self) -> None:
        """HOLD 必须返回 NO_OP（不再是 None）。"""
        decision = _make_decision("AAPL", DecisionAction.HOLD)
        result = self.engine.submit_order(decision, self.market_price)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, OrderStatus.NO_OP)
        self.assertIsNone(result.fill_price)
        self.assertIsNone(result.filled_qty)

    def test_reduce_partial(self) -> None:
        """REDUCE 必须返回 PARTIAL 且 filled_qty = 50% requested_qty。"""
        decision = _make_decision("AAPL", DecisionAction.REDUCE)
        result = self.engine.submit_order(decision, self.market_price, Decimal("100"))
        self.assertIsNotNone(result)
        self.assertEqual(result.status, OrderStatus.PARTIAL)
        self.assertEqual(result.filled_qty, Decimal("50"))
        self.assertEqual(result.requested_qty, Decimal("100"))

    def test_reduce_default_qty(self) -> None:
        """REDUCE 默认 qty=100，filled=50。"""
        decision = _make_decision("AAPL", DecisionAction.REDUCE)
        result = self.engine.submit_order(decision, self.market_price)
        self.assertEqual(result.status, OrderStatus.PARTIAL)
        self.assertEqual(result.filled_qty, Decimal("50"))
        self.assertEqual(result.requested_qty, Decimal("100"))

    def test_order_id_increments(self) -> None:
        decision = _make_decision("AAPL", DecisionAction.BUY)
        r1 = self.engine.submit_order(decision, self.market_price)
        r2 = self.engine.submit_order(decision, self.market_price)
        self.assertNotEqual(r1.order_id, r2.order_id)
        id1 = int(r1.order_id.split("-")[1])
        id2 = int(r2.order_id.split("-")[1])
        self.assertLess(id1, id2)

    def test_latency_positive(self) -> None:
        decision = _make_decision("AAPL", DecisionAction.BUY)
        result = self.engine.submit_order(decision, self.market_price, Decimal("100"))
        self.assertGreaterEqual(result.latency_ms, 0)

    def test_submit_returns_execution_result(self) -> None:
        """submit_order 总是返回 ExecutionResult（HOLD 也不例外）。"""
        for action in DecisionAction:
            decision = _make_decision("AAPL", action)
            result = self.engine.submit_order(decision, self.market_price)
            self.assertIsInstance(result, ExecutionResult)

    def test_default_qty_100(self) -> None:
        """不传 qty 时默认为 100。"""
        decision = _make_decision("AAPL", DecisionAction.BUY)
        result = self.engine.submit_order(decision, self.market_price)
        self.assertEqual(result.requested_qty, Decimal("100"))
        self.assertEqual(result.filled_qty, Decimal("100"))


# ======================================================================
# Direct fill / reject / partial 方法
# ======================================================================


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


# ======================================================================
# 确定性模式
# ======================================================================


class TestExecutionDeterministic(unittest.TestCase):
    def test_deterministic_mode_consistent(self) -> None:
        e1 = ExecutionEngine(deterministic=True, seed=42)
        e2 = ExecutionEngine(deterministic=True, seed=42)
        market = Decimal("150.00")
        decision = _make_decision("AAPL", DecisionAction.BUY)
        r1 = e1.submit_order(decision, market, Decimal("100"))
        r2 = e2.submit_order(decision, market, Decimal("100"))
        self.assertEqual(r1.fill_price, r2.fill_price)
        self.assertEqual(r1.slippage, r2.slippage)

    def test_deterministic_flag(self) -> None:
        eng = ExecutionEngine(deterministic=True)
        self.assertTrue(eng.deterministic)

    def test_set_seed(self) -> None:
        eng = ExecutionEngine(deterministic=True, seed=42)
        eng.set_seed(99)
        self.assertTrue(eng.deterministic)


# ======================================================================
# EventBus 集成测试
# ======================================================================


class TestEventBusIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = ExecutionEngine(deterministic=True)
        event_bus.clear()
        event_bus.clear_log()

    def test_order_submitted_event_buy(self) -> None:
        """BUY 必须触发 ORDER_SUBMITTED 事件。"""
        received: list[dict] = []
        def listener(data: Any) -> None:
            received.append(data)
        event_bus.subscribe(ORDER_SUBMITTED, listener)
        decision = _make_decision("AAPL", DecisionAction.BUY)
        self.engine.submit_order(decision, Decimal("150.00"), Decimal("100"))
        self.assertTrue(len(received) > 0)
        self.assertIn("execution_order", received[0])
        self.assertEqual(received[0]["execution_order"]["action"], "BUY")

    def test_order_submitted_event_sell(self) -> None:
        """SELL 必须触发 ORDER_SUBMITTED 事件。"""
        received: list[dict] = []
        def listener(data: Any) -> None:
            received.append(data)
        event_bus.subscribe(ORDER_SUBMITTED, listener)
        decision = _make_decision("AAPL", DecisionAction.SELL)
        self.engine.submit_order(decision, Decimal("150.00"), Decimal("100"))
        self.assertTrue(len(received) > 0)
        self.assertEqual(received[0]["execution_order"]["action"], "SELL")

    def test_order_submitted_event_hold(self) -> None:
        """HOLD 也必须触发 ORDER_SUBMITTED 事件。"""
        received: list[dict] = []
        def listener(data: Any) -> None:
            received.append(data)
        event_bus.subscribe(ORDER_SUBMITTED, listener)
        decision = _make_decision("AAPL", DecisionAction.HOLD)
        self.engine.submit_order(decision, Decimal("150.00"))
        self.assertTrue(len(received) > 0)
        self.assertEqual(received[0]["execution_order"]["action"], "HOLD")

    def test_order_submitted_event_blocked(self) -> None:
        """BLOCKED 必须触发 ORDER_SUBMITTED 事件。"""
        received: list[dict] = []
        def listener(data: Any) -> None:
            received.append(data)
        event_bus.subscribe(ORDER_SUBMITTED, listener)
        decision = _make_decision("AAPL", DecisionAction.BLOCKED)
        self.engine.submit_order(decision, Decimal("150.00"))
        self.assertTrue(len(received) > 0)
        self.assertEqual(received[0]["execution_order"]["action"], "BLOCKED")

    def test_order_submitted_event_reduce(self) -> None:
        """REDUCE 必须触发 ORDER_SUBMITTED 事件。"""
        received: list[dict] = []
        def listener(data: Any) -> None:
            received.append(data)
        event_bus.subscribe(ORDER_SUBMITTED, listener)
        decision = _make_decision("AAPL", DecisionAction.REDUCE)
        self.engine.submit_order(decision, Decimal("150.00"), Decimal("100"))
        self.assertTrue(len(received) > 0)
        self.assertEqual(received[0]["execution_order"]["action"], "REDUCE")

    def test_order_filled_event_buy(self) -> None:
        """BUY 必须触发 ORDER_FILLED 事件。"""
        received: list[dict] = []
        def listener(data: Any) -> None:
            received.append(data)
        event_bus.subscribe(ORDER_FILLED, listener)
        decision = _make_decision("AAPL", DecisionAction.BUY)
        self.engine.submit_order(decision, Decimal("150.00"), Decimal("100"))
        self.assertTrue(len(received) > 0)
        self.assertIn("execution_result", received[0])
        self.assertEqual(received[0]["execution_result"]["status"], "FILLED")

    def test_order_filled_event_sell(self) -> None:
        """SELL 必须触发 ORDER_FILLED 事件。"""
        received: list[dict] = []
        def listener(data: Any) -> None:
            received.append(data)
        event_bus.subscribe(ORDER_FILLED, listener)
        decision = _make_decision("AAPL", DecisionAction.SELL)
        self.engine.submit_order(decision, Decimal("150.00"), Decimal("100"))
        self.assertTrue(len(received) > 0)
        self.assertEqual(received[0]["execution_result"]["status"], "FILLED")

    def test_order_rejected_event_blocked(self) -> None:
        """BLOCKED 必须触发 ORDER_REJECTED 事件。"""
        received: list[dict] = []
        def listener(data: Any) -> None:
            received.append(data)
        event_bus.subscribe(ORDER_REJECTED, listener)
        decision = _make_decision("AAPL", DecisionAction.BLOCKED)
        self.engine.submit_order(decision, Decimal("150.00"))
        self.assertTrue(len(received) > 0)
        self.assertEqual(received[0]["execution_result"]["status"], "REJECTED")

    def test_order_filled_event_reduce(self) -> None:
        """REDUCE 必须触发 ORDER_FILLED 事件（PARTIAL 也算 FILLED 类事件）。"""
        received: list[dict] = []
        def listener(data: Any) -> None:
            received.append(data)
        event_bus.subscribe(ORDER_FILLED, listener)
        decision = _make_decision("AAPL", DecisionAction.REDUCE)
        self.engine.submit_order(decision, Decimal("150.00"), Decimal("100"))
        self.assertTrue(len(received) > 0)
        self.assertEqual(received[0]["execution_result"]["status"], "PARTIAL")

    def test_hold_does_not_trigger_filled_or_rejected(self) -> None:
        """HOLD 只触发 ORDER_SUBMITTED，不应触发 ORDER_FILLED 或 ORDER_REJECTED。"""
        filled_events: list[dict] = []
        rejected_events: list[dict] = []
        def on_fill(data: Any) -> None:
            filled_events.append(data)
        def on_reject(data: Any) -> None:
            rejected_events.append(data)
        event_bus.subscribe(ORDER_FILLED, on_fill)
        event_bus.subscribe(ORDER_REJECTED, on_reject)
        decision = _make_decision("AAPL", DecisionAction.HOLD)
        self.engine.submit_order(decision, Decimal("150.00"))
        self.assertEqual(len(filled_events), 0)
        self.assertEqual(len(rejected_events), 0)

    def test_simulate_fill_triggers_events(self) -> None:
        """simulate_fill 必须同时触发 ORDER_SUBMITTED 和 ORDER_FILLED。"""
        submitted: list[dict] = []
        filled: list[dict] = []
        def on_sub(data: Any) -> None:
            submitted.append(data)
        def on_fill(data: Any) -> None:
            filled.append(data)
        event_bus.subscribe(ORDER_SUBMITTED, on_sub)
        event_bus.subscribe(ORDER_FILLED, on_fill)
        decision = _make_decision("AAPL", DecisionAction.BUY)
        self.engine.simulate_fill(decision, Decimal("150.00"), Decimal("100"))
        self.assertEqual(len(submitted), 1)
        self.assertEqual(len(filled), 1)

    def test_reject_triggers_events(self) -> None:
        """reject_order 必须同时触发 ORDER_SUBMITTED 和 ORDER_REJECTED。"""
        submitted: list[dict] = []
        rejected: list[dict] = []
        def on_sub(data: Any) -> None:
            submitted.append(data)
        def on_rej(data: Any) -> None:
            rejected.append(data)
        event_bus.subscribe(ORDER_SUBMITTED, on_sub)
        event_bus.subscribe(ORDER_REJECTED, on_rej)
        decision = _make_decision("AAPL", DecisionAction.BUY)
        self.engine.reject_order(decision, "test reject")
        self.assertEqual(len(submitted), 1)
        self.assertEqual(len(rejected), 1)


# ======================================================================
# 安全约束：禁止 broker / API
# ======================================================================


class TestNoBrokerOrAPI(unittest.TestCase):
    def test_no_network_imports(self) -> None:
        with open("execution_engine.py", "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        import_lines = [l.strip() for l in lines if l.strip().startswith("import ") or l.strip().startswith("from ")]
        import_text = "\n".join(import_lines).lower()
        for lib in ["socket", "http", "requests", "yfinance", "urllib"]:
            with self.subTest(lib=lib):
                self.assertNotIn(lib, import_text)

    def test_no_trade_methods(self) -> None:
        """Must not have order execution methods to real brokers."""
        for name in dir(ExecutionEngine):
            lower = name.lower()
            if "connect" in lower or "login" in lower or "api" in lower:
                self.fail(f"ExecutionEngine has forbidden method: {name}")


# ======================================================================
# 全局单例
# ======================================================================


class TestGlobalSingleton(unittest.TestCase):
    def test_execution_engine_is_singleton(self) -> None:
        from execution_engine import execution_engine as ee1
        from execution_engine import execution_engine as ee2
        self.assertIs(ee1, ee2)


# ======================================================================
# 输出结构统一性
# ======================================================================


class TestExecutionResultStructure(unittest.TestCase):
    """验证 ExecutionResult 字段符合规范。"""

    def setUp(self) -> None:
        self.engine = ExecutionEngine(deterministic=True)

    def test_buy_has_all_fields(self) -> None:
        decision = _make_decision("AAPL", DecisionAction.BUY)
        result = self.engine.submit_order(decision, Decimal("150.00"), Decimal("100"))
        self.assertEqual(result.status, OrderStatus.FILLED)
        self.assertIsNotNone(result.fill_price)
        self.assertIsNotNone(result.filled_qty)
        self.assertIsNotNone(result.slippage)

    def test_blocked_has_reject_reason(self) -> None:
        decision = _make_decision("AAPL", DecisionAction.BLOCKED)
        result = self.engine.submit_order(decision, Decimal("150.00"))
        self.assertEqual(result.status, OrderStatus.REJECTED)
        self.assertTrue(len(result.reject_reason) > 0)

    def test_no_op_no_price_or_qty(self) -> None:
        decision = _make_decision("AAPL", DecisionAction.HOLD)
        result = self.engine.submit_order(decision, Decimal("150.00"))
        self.assertEqual(result.status, OrderStatus.NO_OP)
        self.assertIsNone(result.fill_price)
        self.assertIsNone(result.filled_qty)

    def test_partial_has_both_qty(self) -> None:
        decision = _make_decision("AAPL", DecisionAction.REDUCE)
        result = self.engine.submit_order(decision, Decimal("150.00"), Decimal("100"))
        self.assertEqual(result.status, OrderStatus.PARTIAL)
        self.assertIsNotNone(result.filled_qty)
        self.assertIsNotNone(result.requested_qty)
        self.assertEqual(result.filled_qty, result.requested_qty * Decimal("0.5"))


if __name__ == "__main__":
    unittest.main()