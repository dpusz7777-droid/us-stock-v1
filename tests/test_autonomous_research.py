# -*- coding: utf-8 -*-
"""自动研究闭环测试 — run_autonomous_strategy_research / build_research_report 的只读测试。"""

from __future__ import annotations
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.data.recommendation_review import run_autonomous_strategy_research, build_research_report


class TestAutonomousResearch(unittest.TestCase):
    def test_empty_no_crash(self):
        """空数据不崩溃"""
        r = run_autonomous_strategy_research([])
        self.assertIn("insights", r)
        self.assertIn("generated_conclusions", r)
        self.assertIn("recommended_focus", r)
        self.assertIn("confidence", r)

    def test_report_empty_no_crash(self):
        """报告空数据不崩溃"""
        r = build_research_report([])
        self.assertIn("key_findings", r)
        self.assertIn("actionable_insights", r)
        self.assertIn("confidence", r)

    def test_hypothesis_generated(self):
        """给定足够数据应生成假设"""
        rows = [
            {"action": "buy", "price": 100, "current_price": 105, "change_pct": 5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 106, "change_pct": 6.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 95, "change_pct": -5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 108, "change_pct": 8.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 92, "change_pct": -8.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 103, "change_pct": 3.0, "review_grade": "有效"},
        ]
        r = run_autonomous_strategy_research(rows)
        self.assertGreater(len(r["insights"]), 0)

    def test_evidence_non_empty(self):
        """假设应该附带证据"""
        rows = [
            {"action": "buy", "price": 100, "current_price": 105, "change_pct": 5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 106, "change_pct": 6.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 95, "change_pct": -5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 108, "change_pct": 8.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 92, "change_pct": -8.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 103, "change_pct": 3.0, "review_grade": "有效"},
        ]
        r = run_autonomous_strategy_research(rows)
        for h in r["insights"]:
            self.assertGreater(len(h["evidence"]), 0)

    def test_conclusion_generated(self):
        """应该生成结论"""
        rows = [
            {"action": "buy", "price": 100, "current_price": 105, "change_pct": 5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 106, "change_pct": 6.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 95, "change_pct": -5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 108, "change_pct": 8.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 92, "change_pct": -8.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 103, "change_pct": 3.0, "review_grade": "有效"},
        ]
        r = run_autonomous_strategy_research(rows)
        self.assertGreater(len(r["generated_conclusions"]), 0)

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
        r = run_autonomous_strategy_research(rows)
        self.assertGreaterEqual(r["confidence"], 0.0)
        self.assertLessEqual(r["confidence"], 1.0)

    def test_missing_field_no_crash(self):
        """缺失字段不崩溃"""
        rows = [{} for _ in range(6)]
        r = run_autonomous_strategy_research(rows)
        self.assertIn("insights", r)

    def test_report_actionable_insights(self):
        """报告应生成 actionable_insights"""
        rows = [
            {"action": "buy", "price": 100, "current_price": 105, "change_pct": 5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 106, "change_pct": 6.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 95, "change_pct": -5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 108, "change_pct": 8.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 92, "change_pct": -8.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 103, "change_pct": 3.0, "review_grade": "有效"},
        ]
        r = build_research_report(rows)
        self.assertGreater(len(r["actionable_insights"]), 0)


if __name__ == "__main__":
    unittest.main()