# -*- coding: utf-8 -*-
"""策略优化测试 — optimize_parameters 的只读测试。"""

from __future__ import annotations
import sys, unittest, os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.optimizer.strategy_optimizer import optimize_parameters


class TestStrategyOptimizer(unittest.TestCase):
    def test_basic_run(self):
        """基本运行应返回结果"""
        r = optimize_parameters(None)
        self.assertIn("best_params", r)
        self.assertIn("best_score", r)
        self.assertIn("baseline_score", r)
        self.assertIn("all_results", r)

    def test_best_params_has_keys(self):
        """最优参数应包含所需字段"""
        r = optimize_parameters(None)
        bp = r["best_params"]
        for key in ("sector_strength_buy_threshold", "take_profit_pct", "stop_loss_pct", "holding_days"):
            self.assertIn(key, bp)

    def test_delta_return_calculated(self):
        """delta_return 应计算"""
        r = optimize_parameters(None)
        self.assertIsInstance(r["delta_return"], float)

    def test_parameter_suggestions(self):
        """应生成参数建议"""
        r = optimize_parameters(None)
        self.assertGreater(len(r["parameter_suggestions"]), 0)

    def test_file_output(self):
        """应生成 JSON 文件"""
        today = __import__("datetime").date.today().isoformat().replace("-", "")
        report_file = Path(__file__).parent.parent / "reports" / f"strategy_optimization_{today}.json"
        if report_file.exists():
            os.unlink(report_file)
        r = optimize_parameters(None)
        self.assertTrue(report_file.exists())


if __name__ == "__main__":
    unittest.main()