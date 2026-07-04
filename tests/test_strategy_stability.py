# -*- coding: utf-8 -*-
"""策略稳定性测试 — build_strategy_stability_summary 的只读测试。"""

from __future__ import annotations
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.data.recommendation_review import build_strategy_stability_summary, build_strategy_stability_insight


class TestStrategyStability(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"action":"buy","price":100,"current_price":105,"change_pct":5.0,"review_grade":"有效"},
            {"action":"buy","price":100,"current_price":104,"change_pct":4.0,"review_grade":"有效"},
            {"action":"sell","price":100,"current_price":95,"change_pct":-5.0,"review_grade":"有效"},
        ]

    def test_summary_returns_dict(self):
        s = build_strategy_stability_summary(self.rows)
        self.assertIn("strategy_stability", s)
        self.assertIn("most_stable_strategy", s)
        self.assertIn("least_stable_strategy", s)

    def test_strategy_has_fields(self):
        s = build_strategy_stability_summary(self.rows)
        for st, data in s["strategy_stability"].items():
            self.assertIn("avg_win_rate", data)
            self.assertIn("regime_variance", data)
            self.assertIn("stability_score", data)

    def test_empty_no_crash(self):
        s = build_strategy_stability_summary([])
        self.assertEqual(s["most_stable_strategy"], "unknown")

    def test_insight_returns_ranking(self):
        ins = build_strategy_stability_insight(self.rows)
        self.assertIn("ranking", ins)
        self.assertIn("most_robust", ins)
        self.assertIn("least_robust", ins)

    def test_insight_ranking_sorted(self):
        ins = build_strategy_stability_insight(self.rows)
        if len(ins["ranking"]) >= 2:
            self.assertGreaterEqual(ins["ranking"][0]["score"], ins["ranking"][-1]["score"])

    def test_insight_empty_no_crash(self):
        ins = build_strategy_stability_insight([])
        self.assertEqual(ins["most_robust"], "unknown")


if __name__ == "__main__":
    unittest.main()