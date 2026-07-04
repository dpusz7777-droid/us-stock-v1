# -*- coding: utf-8 -*-
"""自主研究决策系统测试 — run_self_directed_research_system / build_self_directed_research_report 的只读测试。"""

from __future__ import annotations
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.data.recommendation_review import (
    run_self_directed_research_system,
    build_self_directed_research_report,
    _compute_priority_score,
)


class TestSelfDirectedResearch(unittest.TestCase):
    def test_empty_no_crash(self):
        """空数据不崩溃"""
        r = run_self_directed_research_system([])
        self.assertIn("research_priorities", r)
        self.assertIn("research_roadmap", r)
        self.assertIn("weekly_plan", r)
        self.assertIn("confidence", r)

    def test_report_empty_no_crash(self):
        """报告空数据不崩溃"""
        r = build_self_directed_research_report([])
        self.assertIn("executive_summary", r)
        self.assertIn("strategic_focus", r)
        self.assertIn("system_maturity", r)

    def test_priorities_sorted(self):
        """priorities 应排序正确"""
        rows = [
            {"action": "buy", "price": 100, "current_price": 105, "change_pct": 5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 106, "change_pct": 6.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 95, "change_pct": -5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 108, "change_pct": 8.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 92, "change_pct": -8.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 103, "change_pct": 3.0, "review_grade": "有效"},
        ]
        r = run_self_directed_research_system(rows)
        self.assertGreater(len(r["research_priorities"]), 0)
        for i, p in enumerate(r["research_priorities"]):
            self.assertEqual(p["priority"], i + 1)

    def test_priority_score_calculated(self):
        """priority score 应正确计算"""
        scores = _compute_priority_score("momentum", {"strategy_failure_risk": {"momentum": {"risk_score": 0.5}}}, {"strategy_stability": {"momentum": {"stability_score": 20}}}, "bear")
        self.assertGreater(scores, 0)

    def test_roadmap_phase_assigned(self):
        """roadmap phase 应正确分配"""
        rows = [
            {"action": "buy", "price": 100, "current_price": 105, "change_pct": 5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 106, "change_pct": 6.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 95, "change_pct": -5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 108, "change_pct": 8.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 92, "change_pct": -8.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 103, "change_pct": 3.0, "review_grade": "有效"},
        ]
        r = run_self_directed_research_system(rows)
        for phase in r["research_roadmap"]:
            self.assertIn("phase", phase)
            self.assertIn("focus", phase)
            self.assertIn("cycles", phase)

    def test_weekly_plan_non_empty(self):
        """weekly_plan 应非空"""
        rows = [
            {"action": "buy", "price": 100, "current_price": 105, "change_pct": 5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 106, "change_pct": 6.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 95, "change_pct": -5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 108, "change_pct": 8.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 92, "change_pct": -8.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 103, "change_pct": 3.0, "review_grade": "有效"},
        ]
        r = run_self_directed_research_system(rows)
        self.assertGreater(len(r["weekly_plan"]), 0)

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
        r = run_self_directed_research_system(rows)
        self.assertGreaterEqual(r["confidence"], 0.0)
        self.assertLessEqual(r["confidence"], 1.0)

    def test_missing_field_no_crash(self):
        """缺失字段不崩溃"""
        rows = [{} for _ in range(6)]
        r = run_self_directed_research_system(rows)
        self.assertIn("research_priorities", r)


if __name__ == "__main__":
    unittest.main()