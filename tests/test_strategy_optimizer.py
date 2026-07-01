# -*- coding: utf-8 -*-
"""StrategyOptimizer 测试。"""

from __future__ import annotations

import unittest
from typing import Any

from event_bus import event_bus
from events import STRATEGY_WEIGHT_UPDATED
from strategy_optimizer import StrategyOptimizer, StrategyWeight, strategy_optimizer


class TestStrategyWeight(unittest.TestCase):
    def test_to_dict(self) -> None:
        w = StrategyWeight(strategy_type="MOMENTUM", weight=0.7)
        d = w.to_dict()
        self.assertEqual(d["strategy_type"], "MOMENTUM")
        self.assertEqual(d["weight"], 0.7)

    def test_repr(self) -> None:
        w = StrategyWeight(strategy_type="DEFENSIVE", weight=0.5, confidence_score=0.8)
        r = repr(w)
        self.assertIn("DEFENSIVE", r)
        self.assertIn("0.50", r)


class TestStrategyOptimizer(unittest.TestCase):
    def setUp(self) -> None:
        self.opt = StrategyOptimizer()
        event_bus.clear_log()

    def test_good_performance_high_weight(self) -> None:
        """高收益低回撤 → score > 0.7 → weight = 1.0"""
        w = self.opt.evaluate("MOMENTUM", "BULL",
                              total_return_pct=40.0, max_drawdown_pct=5.0,
                              trade_count=30, win_rate=0.6, profit_loss_ratio=2.0)
        self.assertGreaterEqual(w.weight, 0.7)

    def test_bad_performance_low_weight(self) -> None:
        """亏损策略 → weight 应该很低 (<0.3)。"""
        w = self.opt.evaluate("MOMENTUM", "BULL",
                              total_return_pct=-10.0, max_drawdown_pct=25.0,
                              trade_count=200, win_rate=0.3, profit_loss_ratio=0.5)
        self.assertLess(w.weight, 0.3)

    def test_bull_boost_momentum(self) -> None:
        """BULL 下 Momentum 权重大于 BREAKOUT。"""
        mom = self.opt.evaluate("MOMENTUM", "BULL",
                              total_return_pct=20.0, max_drawdown_pct=10.0,
                              trade_count=50, win_rate=0.5, profit_loss_ratio=1.5)
        brk = self.opt.evaluate("BREAKOUT", "BULL",
                              total_return_pct=20.0, max_drawdown_pct=10.0,
                              trade_count=50, win_rate=0.5, profit_loss_ratio=1.5)
        self.assertGreater(mom.weight, brk.weight)

    def test_bull_reduces_mean_reversion(self) -> None:
        """BULL 下 MeanReversion 权重降低。"""
        w = self.opt.evaluate("MEAN_REVERSION", "BULL",
                              total_return_pct=20.0, max_drawdown_pct=10.0,
                              trade_count=50, win_rate=0.5, profit_loss_ratio=1.5)
        self.assertLessEqual(w.weight, 0.7)

    def test_bear_boost_defensive(self) -> None:
        """BEAR 下 Defensive 权重大于 MOMENTUM。"""
        dfn = self.opt.evaluate("DEFENSIVE", "BEAR",
                              total_return_pct=10.0, max_drawdown_pct=5.0,
                              trade_count=20, win_rate=0.6, profit_loss_ratio=2.0)
        mom = self.opt.evaluate("MOMENTUM", "BEAR",
                              total_return_pct=10.0, max_drawdown_pct=5.0,
                              trade_count=20, win_rate=0.6, profit_loss_ratio=2.0)
        self.assertGreater(dfn.weight, mom.weight)

    def test_bear_reduces_momentum(self) -> None:
        """BEAR 下 Momentum 权重降低。"""
        w = self.opt.evaluate("MOMENTUM", "BEAR",
                              total_return_pct=20.0, max_drawdown_pct=10.0,
                              trade_count=50, win_rate=0.5, profit_loss_ratio=1.5)
        self.assertLessEqual(w.weight, 0.5)

    def test_choppy_boost_mean_reversion(self) -> None:
        """CHOPPY 下 MeanReversion 权重大于 MOMENTUM。"""
        mr = self.opt.evaluate("MEAN_REVERSION", "CHOPPY",
                              total_return_pct=15.0, max_drawdown_pct=8.0,
                              trade_count=30, win_rate=0.55, profit_loss_ratio=1.8)
        mom = self.opt.evaluate("MOMENTUM", "CHOPPY",
                              total_return_pct=15.0, max_drawdown_pct=8.0,
                              trade_count=30, win_rate=0.55, profit_loss_ratio=1.8)
        self.assertGreater(mr.weight, mom.weight)

    def test_high_risk_penalty(self) -> None:
        """HIGH_RISK 所有策略 ×0.5。"""
        w = self.opt.evaluate("MOMENTUM", "HIGH_RISK",
                              total_return_pct=20.0, max_drawdown_pct=10.0,
                              trade_count=50, win_rate=0.5, profit_loss_ratio=1.5)
        # score 约 0.35→weight=0.4, ×0.5→0.2
        self.assertLessEqual(w.weight, 0.3)

    def test_weight_range(self) -> None:
        """权重必须在 0~1。"""
        for regime in ["BULL", "BEAR", "CHOPPY", "HIGH_RISK"]:
            for strat in ["MOMENTUM", "MEAN_REVERSION", "DEFENSIVE", "BREAKOUT"]:
                w = self.opt.evaluate(strat, regime,
                                      total_return_pct=15.0, max_drawdown_pct=10.0,
                                      trade_count=40, win_rate=0.5, profit_loss_ratio=1.5)
                self.assertGreaterEqual(w.weight, 0.0)
                self.assertLessEqual(w.weight, 1.0)

    def test_confidence_range(self) -> None:
        w = self.opt.evaluate("MOMENTUM", "BULL",
                              total_return_pct=30.0, max_drawdown_pct=8.0,
                              trade_count=30, win_rate=0.6, profit_loss_ratio=2.0)
        self.assertGreaterEqual(w.confidence_score, 0.0)
        self.assertLessEqual(w.confidence_score, 1.0)

    def test_event_published(self) -> None:
        received: list[dict] = []
        def listener(data: Any) -> None:
            received.append(data)
        event_bus.subscribe(STRATEGY_WEIGHT_UPDATED, listener)
        self.opt.evaluate("MOMENTUM", "BULL", total_return_pct=20.0,
                          max_drawdown_pct=10.0, trade_count=50,
                          win_rate=0.5, profit_loss_ratio=1.5)
        self.assertTrue(len(received) > 0)
        self.assertIn("strategy_weight", received[0])

    def test_deterministic(self) -> None:
        w1 = self.opt.evaluate("MOMENTUM", "BULL",
                               total_return_pct=25.0, max_drawdown_pct=8.0,
                               trade_count=40, win_rate=0.55, profit_loss_ratio=1.8)
        w2 = self.opt.evaluate("MOMENTUM", "BULL",
                               total_return_pct=25.0, max_drawdown_pct=8.0,
                               trade_count=40, win_rate=0.55, profit_loss_ratio=1.8)
        self.assertEqual(w1.weight, w2.weight)

    def test_score_calculation(self) -> None:
        score = self.opt._calculate_score(return_pct=30.0, dd_pct=5.0, trades=30, win_rate=0.6, pl_ratio=2.0)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_overtrade_penalty(self) -> None:
        s1 = self.opt._calculate_score(return_pct=20.0, dd_pct=10.0, trades=20, win_rate=0.5, pl_ratio=1.0)
        s2 = self.opt._calculate_score(return_pct=20.0, dd_pct=10.0, trades=400, win_rate=0.5, pl_ratio=1.0)
        self.assertGreater(s1, s2)

    def test_score_to_weight_mapping(self) -> None:
        self.assertEqual(StrategyOptimizer._score_to_weight(0.8), 1.0)
        self.assertEqual(StrategyOptimizer._score_to_weight(0.6), 0.7)
        self.assertEqual(StrategyOptimizer._score_to_weight(0.4), 0.4)
        self.assertEqual(StrategyOptimizer._score_to_weight(0.2), 0.1)


class TestGlobalSingleton(unittest.TestCase):
    def test_strategy_optimizer_is_singleton(self) -> None:
        so1 = strategy_optimizer
        so2 = strategy_optimizer
        self.assertIs(so1, so2)


if __name__ == "__main__":
    unittest.main()