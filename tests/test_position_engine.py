# -*- coding: utf-8 -*-
"""PositionEngine 测试。"""

from __future__ import annotations

import unittest
from typing import Any

from event_bus import event_bus
from events import POSITION_CALCULATED
from position_engine import PositionEngine, PositionAction, PositionResult, position_engine


class TestPositionAction(unittest.TestCase):
    def test_action_values(self) -> None:
        self.assertEqual(PositionAction.HOLD.value, "HOLD")
        self.assertEqual(PositionAction.REDUCE.value, "REDUCE")
        self.assertEqual(PositionAction.CLOSE.value, "CLOSE")


class TestPositionResult(unittest.TestCase):
    def test_minimal(self) -> None:
        r = PositionResult(symbol="AAPL", position_size_pct=0.5)
        self.assertEqual(r.symbol, "AAPL")
        self.assertEqual(r.position_size_pct, 0.5)
        self.assertFalse(r.action_override)

    def test_to_dict(self) -> None:
        r = PositionResult(symbol="AAPL", position_size_pct=0.8, regime="BULL")
        d = r.to_dict()
        self.assertEqual(d["symbol"], "AAPL")
        self.assertEqual(d["position_size_pct"], 0.8)
        self.assertEqual(d["regime"], "BULL")


class TestPositionEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = PositionEngine()
        event_bus.clear_log()

    def test_bull_high_conf(self) -> None:
        r = self.engine.calculate("AAPL", confidence=0.9, market_regime="BULL")
        self.assertAlmostEqual(r.position_size_pct, 0.8)
        self.assertEqual(r.regime, "BULL")

    def test_bull_med_conf(self) -> None:
        r = self.engine.calculate("AAPL", confidence=0.6, market_regime="BULL")
        self.assertAlmostEqual(r.position_size_pct, 0.5)

    def test_bull_low_conf(self) -> None:
        r = self.engine.calculate("AAPL", confidence=0.3, market_regime="BULL")
        self.assertAlmostEqual(r.position_size_pct, 0.2)

    def test_bear_max_30pct(self) -> None:
        r = self.engine.calculate("AAPL", confidence=0.9, market_regime="BEAR")
        self.assertLessEqual(r.position_size_pct, 0.3)

    def test_bear_low_conf(self) -> None:
        r = self.engine.calculate("AAPL", confidence=0.2, market_regime="BEAR")
        self.assertLessEqual(r.position_size_pct, 0.3)

    def test_choppy_max_30pct(self) -> None:
        r = self.engine.calculate("AAPL", confidence=0.9, market_regime="CHOPPY")
        self.assertLessEqual(r.position_size_pct, 0.3)

    def test_high_risk_max_10pct(self) -> None:
        r = self.engine.calculate("AAPL", confidence=0.9, market_regime="HIGH_RISK")
        self.assertLessEqual(r.position_size_pct, 0.1)

    def test_risk_level_high(self) -> None:
        r1 = self.engine.calculate("AAPL", confidence=0.8, risk_level="LOW", market_regime="BULL")
        r2 = self.engine.calculate("AAPL", confidence=0.8, risk_level="HIGH", market_regime="BULL")
        self.assertGreater(r1.position_size_pct, r2.position_size_pct)

    def test_risk_level_blocked(self) -> None:
        r = self.engine.calculate("AAPL", confidence=0.8, risk_level="BLOCKED", market_regime="BULL")
        self.assertEqual(r.position_size_pct, 0.0)
        self.assertEqual(r.action_override, "CLOSE")

    def test_action_override_reduce(self) -> None:
        r = self.engine.calculate("AAPL", confidence=0.8, market_regime="BULL", current_position_pct=0.9)
        self.assertEqual(r.action_override, "REDUCE")

    def test_no_regime_default(self) -> None:
        r = self.engine.calculate("AAPL", confidence=0.8)
        self.assertLessEqual(r.position_size_pct, 0.5)

    def test_event_published(self) -> None:
        received: list[dict] = []
        def listener(data: Any) -> None:
            received.append(data)
        event_bus.subscribe(POSITION_CALCULATED, listener)
        self.engine.calculate("AAPL", confidence=0.8, market_regime="BULL")
        self.assertTrue(len(received) > 0)
        self.assertIn("position_result", received[0])


class TestGlobalSingleton(unittest.TestCase):
    def test_position_engine_is_singleton(self) -> None:
        pe1 = position_engine
        pe2 = position_engine
        self.assertIs(pe1, pe2)


if __name__ == "__main__":
    unittest.main()