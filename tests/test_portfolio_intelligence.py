# -*- coding: utf-8 -*-
"""组合智能测试 — build_portfolio_intelligence_summary 的只读测试。"""

from __future__ import annotations
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.data.recommendation_review import build_portfolio_intelligence_summary, build_portfolio_rebalance_insight


class TestPortfolioIntelligence(unittest.TestCase):
    def test_empty_no_crash(self):
        r = build_portfolio_intelligence_summary([])
        self.assertIn("portfolio_health", r)

    def test_health_structure(self):
        rows = [{"action":"buy","price":100,"current_price":105,"change_pct":5.0,"review_grade":"有效"} for _ in range(6)]
        r = build_portfolio_intelligence_summary(rows)
        h = r["portfolio_health"]
        self.assertIn("overall_score", h)
        self.assertIn("risk_level", h)
        self.assertIn("diversification_score", h)

    def test_score_in_range(self):
        rows = [{"action":"buy","price":100,"current_price":105,"change_pct":5.0,"review_grade":"有效"} for _ in range(6)]
        r = build_portfolio_intelligence_summary(rows)
        s = r["portfolio_health"]["overall_score"]
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 1.0)

    def test_weights_sum_to_one(self):
        rows = [{"action":"buy","price":100,"current_price":105,"change_pct":5.0,"review_grade":"有效"} for _ in range(6)]
        r = build_portfolio_intelligence_summary(rows)
        w = r["strategy_weights_suggestion"]
        if w:
            total = sum(w.values())
            self.assertAlmostEqual(total, 1.0, places=1)

    def test_has_lists(self):
        rows = [{"action":"buy","price":100,"current_price":105,"change_pct":5.0,"review_grade":"有效"} for _ in range(6)]
        r = build_portfolio_intelligence_summary(rows)
        self.assertIsInstance(r["over_exposed_strategies"], list)
        self.assertIsInstance(r["under_utilized_strategies"], list)

    def test_rebalance_structure(self):
        rows = [{"action":"buy","price":100,"current_price":105,"change_pct":5.0,"review_grade":"有效"} for _ in range(6)]
        ins = build_portfolio_rebalance_insight(rows)
        self.assertIn("action", ins)
        self.assertIn("top_adjustments", ins)

    def test_rebalance_empty_no_crash(self):
        ins = build_portfolio_rebalance_insight([])
        self.assertIn(ins["action"], ["rebalance", "maintain"])

    def test_missing_field_no_crash(self):
        rows = [{} for _ in range(6)]
        r = build_portfolio_intelligence_summary(rows)
        self.assertIn("portfolio_health", r)


if __name__ == "__main__":
    unittest.main()