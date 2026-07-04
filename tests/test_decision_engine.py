# -*- coding: utf-8 -*-
"""DecisionEngine 测试。"""

from __future__ import annotations

import unittest
from decimal import Decimal
from typing import Any

from event_bus import event_bus
from events import DECISION_CREATED
from risk_engine import RiskDecision, RiskLevel
from signal_engine import Signal, SignalType
from decision_engine import DecisionEngine, DecisionAction, Decision, decision_engine


def _make_signal(
    symbol: str = "AAPL",
    signal_type: SignalType = SignalType.BUY,
    strength: int = 80,
    confidence: float = 0.8,
    source: str = "price",
) -> Signal:
    return Signal(
        symbol=symbol,
        signal_type=signal_type,
        strength=strength,
        confidence=confidence,
        reason="test signal",
        source=source,
    )


def _make_risk_decision(
    symbol: str = "AAPL",
    risk_level: RiskLevel = RiskLevel.LOW,
    blocked: bool = False,
    adjusted: Signal | None = None,
    penalty: float = 0.0,
) -> RiskDecision:
    signal = _make_signal(symbol, SignalType.BUY)
    return RiskDecision(
        symbol=symbol,
        original_signal=signal,
        risk_level=risk_level,
        adjusted_signal=adjusted,
        blocked=blocked,
        confidence_penalty=penalty,
        reason="test risk",
    )


class TestDecisionAction(unittest.TestCase):
    def test_action_values(self) -> None:
        self.assertEqual(DecisionAction.BUY.value, "BUY")
        self.assertEqual(DecisionAction.SELL.value, "SELL")
        self.assertEqual(DecisionAction.HOLD.value, "HOLD")
        self.assertEqual(DecisionAction.BLOCKED.value, "BLOCKED")
        self.assertEqual(DecisionAction.REDUCE.value, "REDUCE")

    def test_action_is_enum(self) -> None:
        from enum import Enum
        self.assertTrue(issubclass(DecisionAction, Enum))


class TestDecisionDataclass(unittest.TestCase):
    def test_minimal_decision(self) -> None:
        d = Decision(
            symbol="AAPL", action=DecisionAction.BUY,
            confidence=0.8, reason="test",
            risk_level="LOW", signal_type="BUY",
            original_signal_type="BUY",
        )
        self.assertEqual(d.symbol, "AAPL")
        self.assertEqual(d.action, DecisionAction.BUY)
        self.assertEqual(d.confidence, 0.8)

    def test_immutable(self) -> None:
        d = Decision(
            symbol="AAPL", action=DecisionAction.HOLD,
            confidence=0.3, reason="test",
            risk_level="LOW", signal_type="BUY",
            original_signal_type="BUY",
        )
        with self.assertRaises(AttributeError):
            d.action = DecisionAction.BUY

    def test_to_dict(self) -> None:
        d = Decision(
            symbol="AAPL", action=DecisionAction.BUY,
            confidence=0.85, reason="momentum",
            risk_level="LOW", signal_type="BUY",
            original_signal_type="BUY",
        )
        dc = d.to_dict()
        self.assertEqual(dc["symbol"], "AAPL")
        self.assertEqual(dc["action"], "BUY")
        self.assertEqual(dc["risk_level"], "LOW")

    def test_repr(self) -> None:
        d = Decision(
            symbol="AAPL", action=DecisionAction.BLOCKED,
            confidence=0.0, reason="blocked",
            risk_level="BLOCKED", signal_type="BUY",
            original_signal_type="BUY",
        )
        r = repr(d)
        self.assertIn("AAPL", r)
        self.assertIn("BLOCKED", r)


class TestDecisionEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = DecisionEngine()
        event_bus.clear_log()

    def test_buy_low_risk(self) -> None:
        signal = _make_signal("AAPL", SignalType.BUY, confidence=0.8)
        risk = _make_risk_decision("AAPL", RiskLevel.LOW)
        decision = self.engine.evaluate(signal, risk)
        self.assertEqual(decision.action, DecisionAction.BUY)
        self.assertGreater(decision.confidence, 0.5)
        self.assertIn("confirmed", decision.reason.lower())

    def test_buy_medium_risk(self) -> None:
        signal = _make_signal("AAPL", SignalType.BUY, confidence=0.8)
        risk = _make_risk_decision("AAPL", RiskLevel.MEDIUM)
        decision = self.engine.evaluate(signal, risk)
        self.assertEqual(decision.action, DecisionAction.BUY)

    def test_buy_high_risk_downgraded_to_hold(self) -> None:
        signal = _make_signal("AAPL", SignalType.BUY, confidence=0.8)
        risk = _make_risk_decision("AAPL", RiskLevel.HIGH)
        decision = self.engine.evaluate(signal, risk)
        self.assertEqual(decision.action, DecisionAction.HOLD)
        self.assertIn("downgraded", decision.reason.lower())

    def test_blocked_override(self) -> None:
        signal = _make_signal("AAPL", SignalType.BUY)
        risk = _make_risk_decision("AAPL", RiskLevel.BLOCKED, blocked=True)
        decision = self.engine.evaluate(signal, risk)
        self.assertEqual(decision.action, DecisionAction.BLOCKED)
        self.assertAlmostEqual(decision.confidence, 0.0)

    def test_risk_off_override(self) -> None:
        signal = _make_signal("AAPL", SignalType.BUY)
        risk = _make_risk_decision("AAPL", RiskLevel.CRITICAL)
        # Create a scenario that triggers RISK_OFF: the engine must detect CRITICAL
        decision = self.engine.evaluate(signal, risk)
        self.assertEqual(decision.action, DecisionAction.HOLD)

    def test_sell_allowed(self) -> None:
        signal = _make_signal("AAPL", SignalType.SELL, confidence=0.8)
        risk = _make_risk_decision("AAPL", RiskLevel.LOW)
        decision = self.engine.evaluate(signal, risk)
        self.assertEqual(decision.action, DecisionAction.SELL)

    def test_sell_with_high_risk_preserved(self) -> None:
        signal = _make_signal("AAPL", SignalType.SELL, confidence=0.8)
        risk = _make_risk_decision("AAPL", RiskLevel.HIGH)
        decision = self.engine.evaluate(signal, risk)
        self.assertEqual(decision.action, DecisionAction.SELL)

    def test_hold_propagation(self) -> None:
        signal = _make_signal("AAPL", SignalType.HOLD, confidence=0.5)
        risk = _make_risk_decision("AAPL", RiskLevel.LOW)
        decision = self.engine.evaluate(signal, risk)
        self.assertEqual(decision.action, DecisionAction.HOLD)

    def test_position_reduce(self) -> None:
        signal = _make_signal("AAPL", SignalType.HOLD)
        risk = _make_risk_decision("AAPL", RiskLevel.LOW)
        decision = self.engine.evaluate(signal, risk, position_pct=25.0)
        self.assertEqual(decision.action, DecisionAction.REDUCE)
        self.assertIn("25.0%", decision.reason)

    def test_position_within_threshold_no_reduce(self) -> None:
        signal = _make_signal("AAPL", SignalType.BUY)
        risk = _make_risk_decision("AAPL", RiskLevel.LOW)
        decision = self.engine.evaluate(signal, risk, position_pct=15.0)
        self.assertEqual(decision.action, DecisionAction.BUY)

    def test_blocked_override_position_reduce(self) -> None:
        """BLOCKED risk must override position REDUCE."""
        signal = _make_signal("AAPL", SignalType.HOLD)
        risk = _make_risk_decision("AAPL", RiskLevel.BLOCKED, blocked=True)
        decision = self.engine.evaluate(signal, risk, position_pct=45.0)
        self.assertEqual(decision.action, DecisionAction.BLOCKED)

    def test_no_risk_decision_default(self) -> None:
        signal = _make_signal("AAPL", SignalType.BUY, confidence=0.8)
        decision = self.engine.evaluate(signal, None)
        self.assertEqual(decision.action, DecisionAction.BUY)

    def test_confidence_penalty_applied(self) -> None:
        signal = _make_signal("AAPL", SignalType.BUY, confidence=0.8)
        risk = _make_risk_decision("AAPL", RiskLevel.LOW, penalty=0.3)
        decision = self.engine.evaluate(signal, risk)
        self.assertAlmostEqual(decision.confidence, 0.8 * 0.7)

    def test_reduce_signal(self) -> None:
        signal = _make_signal("AAPL", SignalType.REDUCE)
        risk = _make_risk_decision("AAPL", RiskLevel.LOW)
        decision = self.engine.evaluate(signal, risk)
        self.assertEqual(decision.action, DecisionAction.REDUCE)

    def test_original_signal_type_preserved(self) -> None:
        signal = _make_signal("AAPL", SignalType.BUY)
        risk = _make_risk_decision("AAPL", RiskLevel.BLOCKED, blocked=True)
        decision = self.engine.evaluate(signal, risk)
        self.assertEqual(decision.original_signal_type, "BUY")

    def test_event_published(self) -> None:
        received: list[dict] = []
        def listener(data: Any) -> None:
            received.append(data)
        event_bus.subscribe(DECISION_CREATED, listener)
        signal = _make_signal("AAPL", SignalType.BUY)
        risk = _make_risk_decision("AAPL", RiskLevel.LOW)
        self.engine.evaluate(signal, risk)
        self.assertTrue(len(received) > 0)
        self.assertIn("decision", received[0])
        self.assertEqual(received[0]["decision"]["action"], "BUY")


class TestDecisionEngineNoRisk(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = DecisionEngine()

    def test_buy_without_risk(self) -> None:
        signal = _make_signal("AAPL", SignalType.BUY, confidence=0.8)
        decision = self.engine.evaluate(signal)
        self.assertEqual(decision.action, DecisionAction.BUY)
        self.assertAlmostEqual(decision.confidence, 0.8)

    def test_hold_without_risk(self) -> None:
        signal = _make_signal("AAPL", SignalType.HOLD)
        decision = self.engine.evaluate(signal)
        self.assertEqual(decision.action, DecisionAction.HOLD)

    def test_sell_without_risk(self) -> None:
        signal = _make_signal("AAPL", SignalType.SELL, confidence=0.8)
        decision = self.engine.evaluate(signal)
        self.assertEqual(decision.action, DecisionAction.SELL)


class TestNoNetworkOrExecution(unittest.TestCase):
    def test_no_network_imports(self) -> None:
        with open("decision_engine.py", "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        import_lines = [l.strip() for l in lines if l.strip().startswith("import ") or l.strip().startswith("from ")]
        import_text = "\n".join(import_lines).lower()
        for lib in ["socket", "http", "requests", "yfinance"]:
            with self.subTest(lib=lib):
                self.assertNotIn(lib, import_text)

    def test_no_trade_methods(self) -> None:
        for name in dir(DecisionEngine):
            lower = name.lower()
            if "order" in lower or "trade" in lower or "place" in lower:
                self.fail(f"DecisionEngine has forbidden method: {name}")

    def test_no_file_write(self) -> None:
        with open("decision_engine.py", "r", encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn(".write(", source)
        self.assertNotIn('open(', source)


class TestGlobalSingleton(unittest.TestCase):
    def test_decision_engine_is_singleton(self) -> None:
        from decision_engine import decision_engine as de1
        from decision_engine import decision_engine as de2
        self.assertIs(de1, de2)


if __name__ == "__main__":
    unittest.main()