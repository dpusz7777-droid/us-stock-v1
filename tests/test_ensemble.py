# -*- coding: utf-8 -*-
"""策略组合与Walk-Forward测试 — StrategyEnsemble / run_walkforward_test 的只读测试。"""

from __future__ import annotations
import sys, unittest, os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.ensemble.strategy_ensemble import StrategyEnsemble
from northstar.ensemble.walkforward_engine import run_walkforward_test


class TestStrategyEnsemble(unittest.TestCase):
    def setUp(self):
        self.ensemble = StrategyEnsemble()
        self.signals_a = [
            {"symbol": "NVDA", "signal": "BUY", "confidence": 0.85},
            {"symbol": "MSFT", "signal": "WATCH", "confidence": 0.50},
        ]
        self.signals_b = [
            {"symbol": "NVDA", "signal": "WATCH", "confidence": 0.60},
            {"symbol": "MSFT", "signal": "BUY", "confidence": 0.70},
        ]

    def test_add_strategy(self):
        """添加策略增加计数"""
        self.ensemble.add_strategy("baseline", self.signals_a)
        self.assertEqual(self.ensemble.get_strategy_count(), 1)

    def test_combine_signals_returns_list(self):
        """combine_signals 返回列表"""
        self.ensemble.add_strategy("a", self.signals_a)
        self.ensemble.add_strategy("b", self.signals_b)
        result = self.ensemble.combine_signals()
        self.assertIsInstance(result, list)

    def test_combine_signals_has_fields(self):
        """组合信号包含所需字段"""
        self.ensemble.add_strategy("a", self.signals_a)
        result = self.ensemble.combine_signals()
        for r in result:
            self.assertIn("symbol", r)
            self.assertIn("final_signal", r)
            self.assertIn("confidence", r)
            self.assertIn("vote_distribution", r)

    def test_vote_priority(self):
        """BUY 优先级高于 WATCH"""
        self.ensemble.add_strategy("a", self.signals_a)  # NVDA: BUY + WATCH
        self.ensemble.add_strategy("b", self.signals_b)
        result = self.ensemble.combine_signals()
        nvda = [r for r in result if r["symbol"] == "NVDA"]
        if nvda:
            self.assertEqual(nvda[0]["final_signal"], "BUY")
        msft = [r for r in result if r["symbol"] == "MSFT"]
        if msft:
            self.assertEqual(msft[0]["final_signal"], "BUY")

    def test_empty_no_crash(self):
        """空策略不崩溃"""
        result = self.ensemble.combine_signals()
        self.assertEqual(result, [])

    def test_clear(self):
        """clear 清空所有策略"""
        self.ensemble.add_strategy("a", self.signals_a)
        self.ensemble.clear()
        self.assertEqual(self.ensemble.get_strategy_count(), 0)

    def test_get_active_strategies(self):
        """获取活跃策略列表"""
        self.ensemble.add_strategy("a", self.signals_a)
        self.ensemble.add_strategy("b", self.signals_b)
        active = self.ensemble.get_active_strategies()
        self.assertIn("a", active)
        self.assertIn("b", active)


class TestWalkForwardEngine(unittest.TestCase):
    def test_basic_run(self):
        """基本运行应返回结果"""
        r = run_walkforward_test()
        self.assertIn("windows", r)
        self.assertIn("overall_return", r)
        self.assertIn("time_consistency_score", r)
        self.assertIn("performance_decay", r)
        self.assertIn("regime_dependency", r)

    def test_windows_has_fields(self):
        """每个窗口应包含所需字段"""
        r = run_walkforward_test()
        for w in r.get("windows", []):
            self.assertIn("train_return_pct", w)
            self.assertIn("test_return_pct", w)
            self.assertIn("test_win_rate", w)
            self.assertIn("test_max_drawdown", w)

    def test_time_consistency_in_range(self):
        """时间一致性评分应在 0~100"""
        r = run_walkforward_test()
        self.assertGreaterEqual(r["time_consistency_score"], 0.0)
        self.assertLessEqual(r["time_consistency_score"], 100.0)

    def test_performance_decay_not_none(self):
        """performance_decay 应计算"""
        r = run_walkforward_test()
        self.assertIsInstance(r["performance_decay"], float)

    def test_regime_dependency_valid(self):
        """市场依赖判断应有效"""
        r = run_walkforward_test()
        valid = ["all-weather", "bear-resistant", "bull-only dependent", "insufficient_data"]
        self.assertIn(r["regime_dependency"], valid)

    def test_best_worst_window(self):
        """最佳和最差窗口应正确"""
        r = run_walkforward_test()
        self.assertGreater(r["best_window"], 0)
        self.assertGreater(r["worst_window"], 0)

    def test_file_output(self):
        """应生成 JSON 文件"""
        today = __import__("datetime").date.today().isoformat().replace("-", "")
        report_file = Path(__file__).parent.parent / "reports" / f"walkforward_report_{today}.json"
        if report_file.exists():
            os.unlink(report_file)
        r = run_walkforward_test()
        self.assertTrue(report_file.exists())

    def test_multiple_windows(self):
        """应生成多个时间窗口"""
        r = run_walkforward_test()
        self.assertGreater(len(r.get("windows", [])), 1)


if __name__ == "__main__":
    unittest.main()