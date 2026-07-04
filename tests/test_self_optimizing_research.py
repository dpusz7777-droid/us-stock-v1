# -*- coding: utf-8 -*-
"""自优化研究系统测试 — run_self_optimizing_research_system / build_self_optimizing_report 的只读测试。"""

from __future__ import annotations
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.data.recommendation_review import (
    run_self_optimizing_research_system,
    build_self_optimizing_report,
    _compute_rule_optimizations,
    _compute_scoring_adjustments,
    _compute_hypothesis_refinements,
)


class TestSelfOptimizingResearch(unittest.TestCase):
    def test_empty_no_crash(self):
        """空数据不崩溃"""
        r = run_self_optimizing_research_system([])
        self.assertIn("rule_optimizations", r)
        self.assertIn("scoring_adjustments", r)
        self.assertIn("hypothesis_refinements", r)
        self.assertIn("system_health", r)

    def test_report_empty_no_crash(self):
        """报告空数据不崩溃"""
        r = build_self_optimizing_report([])
        self.assertIn("optimization_summary", r)
        self.assertIn("recommended_system_changes", r)
        self.assertIn("system_state", r)

    def test_rule_optimizations_generated(self):
        """rule_optimizations 应生成"""
        rows = [
            {"action": "buy", "price": 100, "current_price": 105, "change_pct": 5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 106, "change_pct": 6.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 95, "change_pct": -5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 108, "change_pct": 8.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 92, "change_pct": -8.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 103, "change_pct": 3.0, "review_grade": "有效"},
        ]
        opts = _compute_rule_optimizations(rows)
        self.assertIsInstance(opts, list)
        for o in opts:
            self.assertIn("rule", o)
            self.assertIn("before", o)
            self.assertIn("after", o)
            self.assertIn("reason", o)

    def test_scoring_adjustments_generated(self):
        """scoring_adjustments 应生成"""
        rows = [
            {"action": "buy", "price": 100, "current_price": 105, "change_pct": 5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 106, "change_pct": 6.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 95, "change_pct": -5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 108, "change_pct": 8.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 92, "change_pct": -8.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 103, "change_pct": 3.0, "review_grade": "有效"},
        ]
        adj = _compute_scoring_adjustments(rows)
        self.assertIsInstance(adj, list)
        for a in adj:
            self.assertIn("component", a)
            self.assertIn("change", a)
            self.assertIn("reason", a)

    def test_hypothesis_refinements_generated(self):
        """hypothesis_refinements 应生成"""
        rows = [
            {"action": "buy", "price": 100, "current_price": 105, "change_pct": 5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 106, "change_pct": 6.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 95, "change_pct": -5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 108, "change_pct": 8.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 92, "change_pct": -8.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 103, "change_pct": 3.0, "review_grade": "有效"},
        ]
        refs = _compute_hypothesis_refinements(rows)
        self.assertIsInstance(refs, list)

    def test_system_health_correct(self):
        """system_health 结构应正确"""
        rows = [
            {"action": "buy", "price": 100, "current_price": 105, "change_pct": 5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 106, "change_pct": 6.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 95, "change_pct": -5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 108, "change_pct": 8.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 92, "change_pct": -8.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 103, "change_pct": 3.0, "review_grade": "有效"},
        ]
        r = run_self_optimizing_research_system(rows)
        sh = r["system_health"]
        self.assertIn("stability", sh)
        self.assertIn("confidence", sh)
        self.assertIn("bias_level", sh)

    def test_confidence_in_range(self):
        """confidence 应在 0~1 之间"""
        rows = [
            {"action": "buy", "price": 100, "current_price": 105, "change_pct": 5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 106, "change_pct": 6.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 95, "change_pct": -5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 108, "change_pct": 8.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 92, "change_pct": -8.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 103, "change_pct": 3.0, "review_grade": "有效"},
        ]
        r = run_self_optimizing_research_system(rows)
        conf = r["system_health"]["confidence"]
        self.assertGreaterEqual(conf, 0.0)
        self.assertLessEqual(conf, 1.0)


if __name__ == "__main__":
    unittest.main()