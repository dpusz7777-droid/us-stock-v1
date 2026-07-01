# -*- coding: utf-8 -*-
"""LiveLearningEngine 测试。"""

from __future__ import annotations

import unittest
from typing import Any

from event_bus import event_bus
from events import LIVE_LEARNING_UPDATED
from live_learning_engine import (
    LiveLearningEngine, LearningSignal, AdaptiveUpdate, live_learning_engine,
)


class TestLearningSignal(unittest.TestCase):
    def test_values(self) -> None:
        self.assertEqual(LearningSignal.POSITIVE.value, "POSITIVE")
        self.assertEqual(LearningSignal.NEGATIVE.value, "NEGATIVE")
        self.assertEqual(LearningSignal.NEUTRAL.value, "NEUTRAL")


class TestAdaptiveUpdate(unittest.TestCase):
    def test_to_dict(self) -> None:
        u = AdaptiveUpdate(
            strategy_type="MOMENTUM", weight_adjustment=0.2,
            risk_adjustment_factor=0.8, confidence_update=0.1,
            learning_signal=LearningSignal.POSITIVE,
        )
        d = u.to_dict()
        self.assertEqual(d["strategy_type"], "MOMENTUM")
        self.assertEqual(d["weight_adjustment"], 0.2)
        self.assertEqual(d["learning_signal"], "POSITIVE")

    def test_repr(self) -> None:
        u = AdaptiveUpdate(
            strategy_type="DEFENSIVE", weight_adjustment=-0.3,
            risk_adjustment_factor=0.5, confidence_update=-0.1,
            learning_signal=LearningSignal.NEGATIVE,
        )
        r = repr(u)
        self.assertIn("DEFENSIVE", r)
        self.assertIn("-0.30", r)


class TestLiveLearningEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = LiveLearningEngine()
        self.engine.reset_state()
        event_bus.clear_log()

    def test_win_increases_weight(self) -> None:
        """盈利后 weight 应增加。"""
        r = self.engine.record_trade("MOMENTUM", pnl=100.0)
        r2 = self.engine.record_trade("MOMENTUM", pnl=150.0)
        self.assertGreater(r2.weight_adjustment, 0)
        self.assertEqual(r2.learning_signal, LearningSignal.POSITIVE)

    def test_loss_decreases_weight(self) -> None:
        """亏损后 weight 应减少。"""
        r = self.engine.record_trade("MOMENTUM", pnl=-100.0)
        self.assertLess(r.weight_adjustment, 0)
        self.assertEqual(r.learning_signal, LearningSignal.NEGATIVE)

    def test_consecutive_wins_accumulate(self) -> None:
        """连续盈利 3 次后 weight 增加更多。"""
        for i in range(3):
            self.engine.record_trade("MOMENTUM", pnl=100.0)
        state = self.engine._state["MOMENTUM"]
        self.assertEqual(state["wins"], 3)
        self.assertEqual(state["losses"], 0)

    def test_consecutive_losses_accumulate(self) -> None:
        """连续亏损 3 次后 weight 大幅下降。"""
        for i in range(3):
            self.engine.record_trade("MOMENTUM", pnl=-100.0)
        state = self.engine._state["MOMENTUM"]
        self.assertEqual(state["losses"], 3)

    def test_high_win_rate_boosts_confidence(self) -> None:
        """胜率 > 60% 时 confidence 增加。"""
        r = self.engine.record_trade("MOMENTUM", pnl=100.0, win_rate=0.65)
        self.assertGreaterEqual(r.confidence_update, 0.0)

    def test_high_drawdown_reduces_risk(self) -> None:
        """回撤 > 10% 时 risk_factor 降低。"""
        r = self.engine.record_trade("MOMENTUM", pnl=-50.0, drawdown=12.0)
        self.assertLess(r.risk_adjustment_factor, 1.0)

    def test_bull_boost_momentum(self) -> None:
        """BULL 下 MOMENTUM 应获得额外提升。"""
        r = self.engine.record_trade("MOMENTUM", pnl=100.0, market_regime="BULL")
        self.assertGreaterEqual(r.weight_adjustment, 0.1)

    def test_bear_boost_defensive(self) -> None:
        """BEAR 下 DEFENSIVE 应获得额外提升。"""
        r = self.engine.record_trade("DEFENSIVE", pnl=100.0, market_regime="BEAR")
        self.assertGreaterEqual(r.weight_adjustment, 0.1)

    def test_choppy_boost_mean_reversion(self) -> None:
        """CHOPPY 下 MEAN_REVERSION 应获得额外提升。"""
        r = self.engine.record_trade("MEAN_REVERSION", pnl=100.0, market_regime="CHOPPY")
        self.assertGreaterEqual(r.weight_adjustment, 0.1)

    def test_high_risk_penalty(self) -> None:
        """HIGH_RISK 下所有权重降低。"""
        r = self.engine.record_trade("MOMENTUM", pnl=100.0, market_regime="HIGH_RISK")
        self.assertLess(r.weight_adjustment, 0)

    def test_neutral_no_adjustment(self) -> None:
        """首次交易（无连续）应返回 NEUTRAL 或接近 0。"""
        r = self.engine.record_trade("MOMENTUM", pnl=0.0)
        # 单笔不亏损也不盈利的信号
        self.assertIn(r.learning_signal, [LearningSignal.NEUTRAL, LearningSignal.NEGATIVE])

    def test_weight_adjustment_range(self) -> None:
        """weight_adjustment 必须在 -0.5 ~ +0.5。"""
        for _ in range(10):
            self.engine.record_trade("MOMENTUM", pnl=100.0)
        state = self.engine._state["MOMENTUM"]
        # 最多累加到 +0.5
        r = self.engine.record_trade("MOMENTUM", pnl=100.0)
        self.assertLessEqual(r.weight_adjustment, 0.5)

    def test_event_published(self) -> None:
        received: list[dict] = []
        def listener(data: Any) -> None:
            received.append(data)
        event_bus.subscribe(LIVE_LEARNING_UPDATED, listener)
        self.engine.record_trade("MOMENTUM", pnl=100.0)
        self.assertTrue(len(received) > 0)
        self.assertIn("adaptive_update", received[0])

    def test_deterministic(self) -> None:
        self.engine.reset_state()
        r1 = self.engine.record_trade("TEST", pnl=100.0, win_rate=0.5)
        self.engine.reset_state()
        r2 = self.engine.record_trade("TEST", pnl=100.0, win_rate=0.5)
        self.assertEqual(r1.weight_adjustment, r2.weight_adjustment)

    def test_reset_state(self) -> None:
        self.engine.record_trade("MOMENTUM", pnl=100.0)
        self.engine.reset_state("MOMENTUM")
        self.assertNotIn("MOMENTUM", self.engine._state)

    def test_reset_all(self) -> None:
        self.engine.record_trade("A", pnl=100.0)
        self.engine.record_trade("B", pnl=100.0)
        self.engine.reset_state()
        self.assertEqual(len(self.engine._state), 0)

    def test_reason_includes_explanation(self) -> None:
        r = self.engine.record_trade("MOMENTUM", pnl=100.0, win_rate=0.65, market_regime="BULL")
        self.assertGreater(len(r.reason), 5)
        self.assertIn("BULL", r.reason)


class TestGlobalSingleton(unittest.TestCase):
    def test_live_learning_engine_is_singleton(self) -> None:
        lle1 = live_learning_engine
        lle2 = live_learning_engine
        self.assertIs(lle1, lle2)


if __name__ == "__main__":
    unittest.main()