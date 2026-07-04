# -*- coding: utf-8 -*-
"""StrategyEngine 测试。"""

from __future__ import annotations

import unittest
from decimal import Decimal
from typing import Any

from event_bus import event_bus
from events import STRATEGY_SELECTED
from strategy_engine import StrategyEngine, StrategyType, StrategySignal, strategy_engine


BULL_PRICES = [Decimal("100") + Decimal(str(i * 2)) for i in range(100)]
BEAR_PRICES = [Decimal("200") - Decimal(str(i * 1.5)) for i in range(100)]
CHOPPY_PRICES = [Decimal("100") + (Decimal(str(i % 10 - 5))) for i in range(100)]


class TestStrategyType(unittest.TestCase):
    def test_type_values(self) -> None:
        self.assertEqual(StrategyType.MOMENTUM.value, "MOMENTUM")
        self.assertEqual(StrategyType.MEAN_REVERSION.value, "MEAN_REVERSION")
        self.assertEqual(StrategyType.DEFENSIVE.value, "DEFENSIVE")
        self.assertEqual(StrategyType.BREAKOUT.value, "BREAKOUT")


class TestStrategySignal(unittest.TestCase):
    def test_to_dict(self) -> None:
        s = StrategySignal(strategy_type=StrategyType.MOMENTUM, signal_strength=0.7, confidence=0.8, reason="test")
        d = s.to_dict()
        self.assertEqual(d["strategy_type"], "MOMENTUM")
        self.assertEqual(d["signal_strength"], 0.7)
        self.assertEqual(d["confidence"], 0.8)

    def test_repr(self) -> None:
        s = StrategySignal(strategy_type=StrategyType.DEFENSIVE, signal_strength=0.5, confidence=0.9, reason="def")
        r = repr(s)
        self.assertIn("DEFENSIVE", r)
        self.assertIn("0.50", r)


class TestStrategyEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = StrategyEngine()
        event_bus.clear_log()

    def test_bull_momentum(self) -> None:
        signal = self.engine.select(market_regime="BULL", price_series=BULL_PRICES)
        self.assertEqual(signal.strategy_type, StrategyType.MOMENTUM)

    def test_bull_trend_following_condition(self) -> None:
        self.assertTrue(self.engine._trend_following_condition(BULL_PRICES))

    def test_bull_no_price_series(self) -> None:
        signal = self.engine.select(market_regime="BULL")
        self.assertEqual(signal.strategy_type, StrategyType.BREAKOUT)

    def test_bear_defensive(self) -> None:
        signal = self.engine.select(market_regime="BEAR")
        self.assertEqual(signal.strategy_type, StrategyType.DEFENSIVE)

    def test_bear_lockdown_forced_defensive(self) -> None:
        signal = self.engine.select(market_regime="BEAR", capital_mode="LOCKDOWN")
        self.assertEqual(signal.strategy_type, StrategyType.DEFENSIVE)
        self.assertAlmostEqual(signal.signal_strength, 0.0)

    def test_bear_defensive_reason(self) -> None:
        signal = self.engine.select(market_regime="BEAR", capital_mode="NORMAL")
        self.assertIn("BEAR", signal.reason)

    def test_choppy_mean_reversion(self) -> None:
        signal = self.engine.select(market_regime="CHOPPY", price_series=CHOPPY_PRICES)
        self.assertEqual(signal.strategy_type, StrategyType.MEAN_REVERSION)

    def test_choppy_no_price_default(self) -> None:
        signal = self.engine.select(market_regime="CHOPPY")
        self.assertEqual(signal.strategy_type, StrategyType.DEFENSIVE)

    def test_high_risk_defensive(self) -> None:
        signal = self.engine.select(market_regime="HIGH_RISK")
        self.assertEqual(signal.strategy_type, StrategyType.DEFENSIVE)
        self.assertLess(signal.signal_strength, 0.5)

    def test_capital_mode_caution_reduces_strength(self) -> None:
        s1 = self.engine.select(market_regime="BULL", capital_mode="NORMAL", price_series=BULL_PRICES)
        s2 = self.engine.select(market_regime="BULL", capital_mode="CAUTION", price_series=BULL_PRICES)
        self.assertGreater(s1.signal_strength, s2.signal_strength)

    def test_capital_mode_lockdown_zero_strength(self) -> None:
        signal = self.engine.select(market_regime="BULL", capital_mode="LOCKDOWN", price_series=BULL_PRICES)
        self.assertAlmostEqual(signal.signal_strength, 0.0)

    def test_signal_strength_range(self) -> None:
        for regime in ["BULL", "BEAR", "CHOPPY", "HIGH_RISK"]:
            for cap in ["NORMAL", "CAUTION", "DEFENSIVE", "LOCKDOWN"]:
                s = self.engine.select(market_regime=regime, capital_mode=cap, price_series=BULL_PRICES)
                self.assertGreaterEqual(s.signal_strength, 0.0)
                self.assertLessEqual(s.signal_strength, 1.0)

    def test_signal_confidence_range(self) -> None:
        for regime in ["BULL", "BEAR", "CHOPPY", "HIGH_RISK"]:
            s = self.engine.select(market_regime=regime)
            self.assertGreaterEqual(s.confidence, 0.0)
            self.assertLessEqual(s.confidence, 1.0)

    def test_event_published(self) -> None:
        received: list[dict] = []
        def listener(data: Any) -> None:
            received.append(data)
        event_bus.subscribe(STRATEGY_SELECTED, listener)
        self.engine.select(market_regime="BULL")
        self.assertTrue(len(received) > 0)
        self.assertIn("strategy_signal", received[0])

    def test_deterministic(self) -> None:
        s1 = self.engine.select(market_regime="BULL", price_series=BULL_PRICES)
        s2 = self.engine.select(market_regime="BULL", price_series=BULL_PRICES)
        self.assertEqual(s1.strategy_type, s2.strategy_type)

    def test_reason_includes_explanation(self) -> None:
        signal = self.engine.select(market_regime="CHOPPY", price_series=CHOPPY_PRICES)
        self.assertGreater(len(signal.reason), 5)

    def test_unknown_regime_defaults_defensive(self) -> None:
        signal = self.engine.select(market_regime="UNKNOWN")
        self.assertEqual(signal.strategy_type, StrategyType.DEFENSIVE)

    def test_mean_reversion_condition_false_for_trend(self) -> None:
        self.assertFalse(self.engine._mean_reversion_condition(BULL_PRICES))

    def test_mean_reversion_condition_true_for_choppy(self) -> None:
        self.assertTrue(self.engine._mean_reversion_condition(CHOPPY_PRICES))


class TestGlobalSingleton(unittest.TestCase):
    def test_strategy_engine_is_singleton(self) -> None:
        se1 = strategy_engine
        se2 = strategy_engine
        self.assertIs(se1, se2)


if __name__ == "__main__":
    unittest.main()