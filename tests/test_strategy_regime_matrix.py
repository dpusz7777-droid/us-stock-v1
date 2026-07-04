# -*- coding: utf-8 -*-
"""Strategy × Market Regime 矩阵测试。"""

from __future__ import annotations
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.data.recommendation_review import build_strategy_regime_matrix, build_strategy_regime_insight


class TestStrategyRegimeMatrix(unittest.TestCase):
    def setUp(self):
        # 构造足以推导 market regime 的数据（至少 3 条）
        self.rows = [
            {"action":"buy","price":100,"current_price":105,"change_pct":5.0,"review_grade":"有效"},
            {"action":"buy","price":100,"current_price":104,"change_pct":4.0,"review_grade":"有效"},
            {"action":"sell","price":100,"current_price":95,"change_pct":-5.0,"review_grade":"有效"},
        ]

    def test_matrix_returns_dict(self):
        m = build_strategy_regime_matrix(self.rows)
        self.assertIsInstance(m, dict)

    def test_matrix_contains_regime_keys(self):
        m = build_strategy_regime_matrix(self.rows)
        self.assertGreater(len(m), 0)

    def test_matrix_cell_has_count(self):
        m = build_strategy_regime_matrix(self.rows)
        for rg, strategies in m.items():
            for st, stats in strategies.items():
                self.assertIn("count", stats)
                self.assertIn("win_rate", stats)

    def test_empty_returns_empty(self):
        m = build_strategy_regime_matrix([])
        self.assertEqual(m, {})

    def test_insight_returns_dict(self):
        ins = build_strategy_regime_insight(self.rows)
        self.assertIn("best_pairs", ins)
        self.assertIn("worst_pairs", ins)
        self.assertIn("global_best_strategy", ins)
        self.assertIn("global_worst_strategy", ins)

    def test_insight_empty_no_crash(self):
        ins = build_strategy_regime_insight([])
        self.assertEqual(ins["global_best_strategy"], "unknown")


if __name__ == "__main__":
    unittest.main()