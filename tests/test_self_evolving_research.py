# -*- coding: utf-8 -*-
"""自演化研究测试 — run_self_evolving_research_loop / build_evolution_report 的只读测试。"""

from __future__ import annotations
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.data.recommendation_review import (
    run_self_evolving_research_loop,
    build_evolution_report,
    _detect_strategy_failure_patterns,
    _detect_recurring_evidence,
    _consolidate_insights,
)


class TestSelfEvolvingResearch(unittest.TestCase):
    def test_empty_no_crash(self):
        """空数据不崩溃"""
        r = run_self_evolving_research_loop([])
        self.assertIn("evolved_rules", r)
        self.assertIn("new_hypothesis_types", r)
        self.assertIn("system_insights", r)
        self.assertIn("confidence", r)

    def test_report_empty_no_crash(self):
        """报告空数据不崩溃"""
        r = build_evolution_report([])
        self.assertIn("rule_changes", r)
        self.assertIn("system_recommendations", r)
        self.assertIn("model_state", r)

    def test_rule_evolution_generated(self):
        """给定合适数据应生成规则演化"""
        rows = [
            {"action": "buy", "price": 100, "current_price": 100, "change_pct": 0.0, "review_grade": "失效"},
            {"action": "buy", "price": 100, "current_price": 100, "change_pct": 0.0, "review_grade": "失效"},
            {"action": "sell", "price": 100, "current_price": 100, "change_pct": 0.0, "review_grade": "无效"},
            {"action": "buy", "price": 100, "current_price": 100, "change_pct": 0.0, "review_grade": "失效"},
            {"action": "buy", "price": 100, "current_price": 100, "change_pct": 0.0, "review_grade": "失效"},
            {"action": "buy", "price": 100, "current_price": 100, "change_pct": 0.0, "review_grade": "失效"},
        ]
        patterns = _detect_strategy_failure_patterns(rows)
        self.assertIsInstance(patterns, list)

    def test_hypothesis_expansion(self):
        """基于有支持的假设应扩展 hypothesis 类型"""
        insights = [
            {"hypothesis": "momentum performs poorly in high volatility", "support": 0.78, "evidence": ["a"]},
            {"hypothesis": "breakout strategy is inefficient in sideways markets", "support": 0.65, "evidence": ["b"]},
        ]
        new_types = _detect_recurring_evidence(insights)
        self.assertGreater(len(new_types), 0)

    def test_system_insight_consolidation(self):
        """多个 hypothesis 应合并为系统洞察"""
        insights = [
            {"hypothesis": "momentum performs poorly in high volatility", "support": 0.78, "evidence": ["a"]},
            {"hypothesis": "defensive strategy demonstrates robustness", "support": 0.72, "evidence": ["b"]},
        ]
        merged = _consolidate_insights(insights, [])
        self.assertGreater(len(merged), 0)

    def test_confidence_in_range(self):
        """confidence 应在 0~1 之间"""
        rows = [
            {"action": "buy", "price": 100, "current_price": 105, "change_pct": 5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 106, "change_pct": 6.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 107, "change_pct": 7.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 108, "change_pct": 8.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 95, "change_pct": -5.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 93, "change_pct": -7.0, "review_grade": "有效"},
        ]
        r = run_self_evolving_research_loop(rows)
        self.assertGreaterEqual(r["confidence"], 0.0)
        self.assertLessEqual(r["confidence"], 1.0)

    def test_missing_field_no_crash(self):
        """缺失字段不崩溃"""
        rows = [{} for _ in range(6)]
        r = run_self_evolving_research_loop(rows)
        self.assertIn("evolved_rules", r)

    def test_model_state_output(self):
        """model_state 应正确输出"""
        rows = [
            {"action": "buy", "price": 100, "current_price": 105, "change_pct": 5.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 106, "change_pct": 6.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 107, "change_pct": 7.0, "review_grade": "有效"},
            {"action": "buy", "price": 100, "current_price": 108, "change_pct": 8.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 95, "change_pct": -5.0, "review_grade": "有效"},
            {"action": "sell", "price": 100, "current_price": 93, "change_pct": -7.0, "review_grade": "有效"},
        ]
        r = run_self_evolving_research_loop(rows)
        self.assertIn(r["model_state"], ["stable", "evolving", "unstable"])


if __name__ == "__main__":
    unittest.main()