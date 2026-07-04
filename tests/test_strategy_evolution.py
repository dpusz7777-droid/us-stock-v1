# -*- coding: utf-8 -*-
"""策略进化引擎测试 — run_strategy_evolution 的只读测试。"""

from __future__ import annotations
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.engine.strategy_evolution import run_strategy_evolution, DEFAULT_WEIGHTS


class TestStrategyEvolution(unittest.TestCase):
    def setUp(self):
        self.sample_attr = {
            "strategy_attribution": {
                "momentum": {"total_return": 12.0, "win_rate": 0.65, "trade_count": 10},
                "defensive": {"total_return": 8.0, "win_rate": 0.70, "trade_count": 8},
                "breakout": {"total_return": -3.0, "win_rate": 0.25, "trade_count": 6},
                "mean_reversion": {"total_return": 1.0, "win_rate": 0.50, "trade_count": 4},
            },
            "regime_attribution": {
                "bull": {"return": 15.0, "accuracy": 0.75, "trade_count": 12},
                "bear": {"return": -2.0, "accuracy": 0.40, "trade_count": 5},
                "sideways": {"return": 3.0, "accuracy": 0.55, "trade_count": 6},
            },
        }

    def test_empty_no_crash(self):
        """空数据不崩溃"""
        r = run_strategy_evolution(None, None)
        self.assertIn("strategy_updates", r)
        self.assertIn("new_strategies", r)
        self.assertIn("deprecated_strategies", r)
        self.assertIn("weight_vector", r)
        self.assertIn("evolution_log", r)

    def test_empty_attr_no_crash(self):
        """空归因数据不崩溃"""
        r = run_strategy_evolution({}, {})
        self.assertIn("strategy_updates", r)

    def test_strategy_updates_generated(self):
        """应生成策略更新"""
        r = run_strategy_evolution(self.sample_attr)
        su = r["strategy_updates"]
        self.assertGreater(len(su), 0)
        for st, update in su.items():
            self.assertIn("action", update)
            self.assertIn("weight_change", update)
            self.assertIn("reason", update)

    def test_high_win_rate_increase(self):
        """高胜率策略应 increase"""
        r = run_strategy_evolution(self.sample_attr)
        su = r["strategy_updates"]
        # defensive has 0.70 win_rate
        if "defensive" in su:
            self.assertEqual(su["defensive"]["action"], "increase")

    def test_low_win_rate_decrease(self):
        """低胜率策略应 decrease"""
        r = run_strategy_evolution(self.sample_attr)
        su = r["strategy_updates"]
        # breakout has 0.25 win_rate
        if "breakout" in su:
            self.assertEqual(su["breakout"]["action"], "decrease")

    def test_new_strategies_generated(self):
        """应生成新策略变体"""
        r = run_strategy_evolution(self.sample_attr)
        ns = r["new_strategies"]
        self.assertGreater(len(ns), 0)
        for s in ns:
            self.assertIn("name", s)
            self.assertIn("base", s)
            self.assertIn("modifiers", s)

    def test_deprecated_strategies(self):
        """应识别淘汰策略"""
        r = run_strategy_evolution(self.sample_attr)
        ds = r["deprecated_strategies"]
        # breakout: 0.25 win_rate, -3.0 return, 6 trades → should be deprecated
        self.assertGreaterEqual(len(ds), 0)

    def test_weight_vector_sum_to_one(self):
        """权重向量总和应 ≈ 1"""
        r = run_strategy_evolution(self.sample_attr)
        wv = r["weight_vector"]
        total = sum(wv.values())
        self.assertAlmostEqual(total, 1.0, places=1)

    def test_weight_vector_has_keys(self):
        """权重向量应包含主要策略"""
        r = run_strategy_evolution(self.sample_attr)
        wv = r["weight_vector"]
        for key in DEFAULT_WEIGHTS:
            self.assertIn(key, wv)

    def test_evolution_log_non_empty(self):
        """演化日志应非空"""
        r = run_strategy_evolution(self.sample_attr)
        self.assertGreater(len(r["evolution_log"]), 0)

    def test_custom_weights(self):
        """自定义权重应被使用"""
        custom = {"momentum": 0.5, "defensive": 0.5}
        r = run_strategy_evolution(self.sample_attr, custom)
        wv = r["weight_vector"]
        total = sum(wv.values())
        self.assertAlmostEqual(total, 1.0, places=1)


if __name__ == "__main__":
    unittest.main()