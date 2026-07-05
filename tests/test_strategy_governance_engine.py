# -*- coding: utf-8 -*-
"""策略治理与系统收敛测试 — StrategyGovernanceEngine 的只读测试。"""

from __future__ import annotations
import sys, unittest, os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.governance.strategy_governance_engine import StrategyGovernanceEngine


class TestStrategyGovernanceEngine(unittest.TestCase):
    def setUp(self):
        self.engine = StrategyGovernanceEngine()
        self.metrics_a = {"return_score": 90, "stability_score": 85, "consistency_score": 80, "max_drawdown": 5}
        self.metrics_b = {"return_score": 70, "stability_score": 65, "consistency_score": 60, "max_drawdown": 8}
        self.metrics_c = {"return_score": 50, "stability_score": 45, "consistency_score": 40, "max_drawdown": 12}
        self.metrics_d = {"return_score": 20, "stability_score": 15, "consistency_score": 10, "max_drawdown": 25}

    def test_empty_no_crash(self):
        """空引擎不崩溃"""
        r = self.engine.get_report()
        self.assertIn("total_strategies", r)
        self.assertIn("grade_distribution", r)

    def test_register_strategy(self):
        """注册策略增加计数"""
        self.engine.register_strategy("test_a", self.metrics_a)
        self.assertEqual(self.engine.get_strategy_count(), 1)

    def test_evaluate_health_high(self):
        """高评分策略健康分应高"""
        self.engine.register_strategy("test_a", self.metrics_a)
        health = self.engine.evaluate_strategy_health("test_a")
        self.assertGreater(health, 80)

    def test_evaluate_health_low(self):
        """低评分策略健康分应低"""
        self.engine.register_strategy("test_d", self.metrics_d)
        health = self.engine.evaluate_strategy_health("test_d")
        self.assertLess(health, 40)

    def test_classify_a(self):
        """高评分策略应为 A 级"""
        self.engine.register_strategy("test_a", self.metrics_a)
        cls = self.engine.classify_strategies()
        self.assertEqual(cls["test_a"], "A")

    def test_classify_d(self):
        """低评分策略应为 D 级"""
        self.engine.register_strategy("test_d", self.metrics_d)
        cls = self.engine.classify_strategies()
        self.assertEqual(cls["test_d"], "D")

    def test_prune_removes_d(self):
        """prune 应移除 D 级策略"""
        self.engine.register_strategy("test_d", self.metrics_d)
        self.engine.register_strategy("test_a", self.metrics_a)
        pruned = self.engine.prune_strategies()
        self.assertIn("test_d", pruned)
        self.assertEqual(self.engine.get_strategy_count(), 1)

    def test_prune_enforces_max(self):
        """prune 应限制策略总数"""
        for i in range(15):
            self.engine.register_strategy(f"test_{i}", self.metrics_b)
        pruned = self.engine.prune_strategies()
        self.assertLessEqual(self.engine.get_strategy_count(), 10)

    def test_select_active_portfolio(self):
        """选择可运行策略组合"""
        self.engine.register_strategy("a1", self.metrics_a)
        self.engine.register_strategy("a2", self.metrics_a)
        self.engine.register_strategy("b1", self.metrics_b)
        self.engine.register_strategy("d1", self.metrics_d)
        self.engine.prune_strategies()
        portfolio = self.engine.select_active_portfolio()
        self.assertIn("strategies", portfolio)
        self.assertIn("weights", portfolio)
        self.assertGreater(len(portfolio["strategies"]), 0)

    def test_max_strategies_limit(self):
        """系统应限制最大策略数"""
        for i in range(20):
            self.engine.register_strategy(f"s{i}", self.metrics_b)
        self.engine.prune_strategies()
        self.assertLessEqual(self.engine.get_strategy_count(), 10)

    def test_complexity_score(self):
        """复杂度评分应在合理范围"""
        self.engine.register_strategy("a", self.metrics_a)
        score = self.engine.get_system_complexity_score()
        self.assertGreaterEqual(score, 0.0)

    def test_clear(self):
        """clear 清空所有"""
        self.engine.register_strategy("a", self.metrics_a)
        self.engine.clear()
        self.assertEqual(self.engine.get_strategy_count(), 0)

    def test_file_output(self):
        """应生成 JSON 文件"""
        today = __import__("datetime").date.today().isoformat().replace("-", "")
        report_file = Path(__file__).parent.parent / "reports" / f"strategy_governance_{today}.json"
        if report_file.exists():
            os.unlink(report_file)
        self.engine.register_strategy("a", self.metrics_a)
        r = self.engine.get_report()
        self.assertTrue(report_file.exists())

    def test_governance_log(self):
        """治理日志应非空"""
        self.engine.register_strategy("d1", self.metrics_d)
        self.engine.register_strategy("a1", self.metrics_a)
        self.engine.prune_strategies()
        r = self.engine.get_report()
        self.assertGreater(len(r["governance_action_log"]), 0)


if __name__ == "__main__":
    unittest.main()