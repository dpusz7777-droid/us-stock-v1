# -*- coding: utf-8 -*-
"""Research Agent Core 测试 — run_research_agent_core / build_research_agent_report 的只读测试。"""

from __future__ import annotations
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.data.recommendation_review import (
    run_research_agent_core,
    build_research_agent_report,
    _generate_research_questions,
)


class TestResearchAgentCore(unittest.TestCase):
    def test_empty_no_crash(self):
        """空数据不崩溃"""
        r = run_research_agent_core([])
        self.assertIn("research_questions", r)
        self.assertIn("analysis_chains", r)
        self.assertIn("final_report", r)
        self.assertIn("confidence", r)

    def test_report_empty_no_crash(self):
        """报告空数据不崩溃"""
        r = build_research_agent_report([])
        self.assertIn("core_findings", r)
        self.assertIn("actionable_recommendations", r)
        self.assertIn("system_confidence", r)

    def test_questions_generated(self):
        """给定足够数据应生成研究问题"""
        rows = [
            {"action": "buy", "price": 100, "current_price": 105, "change_pct": 5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 106, "change_pct": 6.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 95, "change_pct": -5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 108, "change_pct": 8.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 92, "change_pct": -8.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 103, "change_pct": 3.0, "review_grade": "有效"},
        ]
        qs = _generate_research_questions(rows)
        self.assertGreater(len(qs), 0)

    def test_analysis_chain_structure(self):
        """analysis_chain 结构应完整"""
        rows = [
            {"action": "buy", "price": 100, "current_price": 105, "change_pct": 5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 106, "change_pct": 6.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 95, "change_pct": -5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 108, "change_pct": 8.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 92, "change_pct": -8.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 103, "change_pct": 3.0, "review_grade": "有效"},
        ]
        r = run_research_agent_core(rows)
        for chain in r["analysis_chains"]:
            self.assertIn("question", chain)
            self.assertIn("steps", chain)
            self.assertIn("evidence", chain)
            self.assertIn("conclusion", chain)
            self.assertGreater(len(chain["steps"]), 0)

    def test_final_report_merged(self):
        """final_report 应正确合并"""
        rows = [
            {"action": "buy", "price": 100, "current_price": 105, "change_pct": 5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 106, "change_pct": 6.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 95, "change_pct": -5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 108, "change_pct": 8.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 92, "change_pct": -8.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 103, "change_pct": 3.0, "review_grade": "有效"},
        ]
        r = run_research_agent_core(rows)
        fr = r["final_report"]
        self.assertIn("summary", fr)
        self.assertIn("recommendations", fr)

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
        r = run_research_agent_core(rows)
        self.assertGreaterEqual(r["confidence"], 0.0)
        self.assertLessEqual(r["confidence"], 1.0)

    def test_missing_field_no_crash(self):
        """缺失字段不崩溃"""
        rows = [{} for _ in range(6)]
        r = run_research_agent_core(rows)
        self.assertIn("research_questions", r)

    def test_conclusion_correct(self):
        """conclusion 应基于证据合成"""
        rows = [
            {"action": "buy", "price": 100, "current_price": 105, "change_pct": 5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 106, "change_pct": 6.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 95, "change_pct": -5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 108, "change_pct": 8.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 92, "change_pct": -8.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 103, "change_pct": 3.0, "review_grade": "有效"},
        ]
        r = run_research_agent_core(rows)
        for chain in r["analysis_chains"]:
            self.assertIsNotNone(chain["conclusion"])


if __name__ == "__main__":
    unittest.main()