# -*- coding: utf-8 -*-
"""策略评分测试 — evaluate_system_performance 的只读测试。"""

from __future__ import annotations
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.optimizer.strategy_evaluator import evaluate_system_performance


class TestStrategyEvaluator(unittest.TestCase):
    def setUp(self):
        self.sample_report = {
            "total_return_pct": 8.5,
            "avg_return_pct": 4.2,
            "win_rate": 0.65,
            "max_drawdown_pct": 4.5,
            "total_closed_trades": 10,
        }
        self.sample_risk = {
            "risk_level": "LOW",
            "position_utilization": 0.45,
            "can_trade_today": True,
        }

    def test_empty_no_crash(self):
        """空数据不崩溃"""
        r = evaluate_system_performance(None, None, None)
        self.assertIn("total_score", r)
        self.assertIn("grade", r)
        self.assertEqual(r["grade"], "D")

    def test_total_score_in_range(self):
        """总分应在 0~100 之间"""
        r = evaluate_system_performance(self.sample_report, None, self.sample_risk)
        self.assertGreaterEqual(r["total_score"], 0.0)
        self.assertLessEqual(r["total_score"], 100.0)

    def test_has_all_scores(self):
        """应包含所有维度评分"""
        r = evaluate_system_performance(self.sample_report, None, self.sample_risk)
        self.assertIn("return_score", r)
        self.assertIn("stability_score", r)
        self.assertIn("win_rate_score", r)
        self.assertIn("risk_score", r)
        self.assertIn("total_score", r)
        self.assertIn("grade", r)

    def test_grade_valid(self):
        """等级应有效"""
        r = evaluate_system_performance(self.sample_report, None, self.sample_risk)
        self.assertIn(r["grade"], ["A", "B", "C", "D"])

    def test_higher_return_gives_higher_score(self):
        """更高收益应获得更高评分"""
        low = evaluate_system_performance({"total_return_pct": 1.0, "avg_return_pct": 0.5, "win_rate": 0.5, "max_drawdown_pct": 5.0}, None, self.sample_risk)
        high = evaluate_system_performance({"total_return_pct": 15.0, "avg_return_pct": 7.0, "win_rate": 0.7, "max_drawdown_pct": 3.0}, None, self.sample_risk)
        self.assertGreater(high["total_score"], low["total_score"])

    def test_risk_level_affects_score(self):
        """高风险应降低评分"""
        low_risk = evaluate_system_performance(self.sample_report, None, {"risk_level": "LOW", "position_utilization": 0.45, "can_trade_today": True})
        high_risk = evaluate_system_performance(self.sample_report, None, {"risk_level": "HIGH", "position_utilization": 0.1, "can_trade_today": False})
        self.assertGreater(low_risk["total_score"], high_risk["total_score"])

    def test_file_output(self):
        """应生成 JSON 文件"""
        today = __import__("datetime").date.today().isoformat().replace("-", "")
        report_file = Path(__file__).parent.parent / "reports" / f"strategy_evaluation_{today}.json"
        if report_file.exists():
            import os
            os.unlink(report_file)
        r = evaluate_system_performance(self.sample_report, None, self.sample_risk)
        self.assertTrue(report_file.exists())


if __name__ == "__main__":
    unittest.main()