# -*- coding: utf-8 -*-
"""市场状态识别测试 — classify_market_regime 的只读测试。"""

from __future__ import annotations
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.data.recommendation_review import classify_market_regime, build_market_regime_summary


class TestClassifyMarketRegime(unittest.TestCase):
    def test_bull_high_win_rate(self):
        rows = [{"action":"buy","change_pct":5.0,"review_grade":"有效"},
                {"action":"buy","change_pct":4.0,"review_grade":"有效"},
                {"action":"buy","change_pct":1.0,"review_grade":"待观察"}]
        result = classify_market_regime(rows)
        self.assertEqual(result, "bull")

    def test_bear_low_win_rate(self):
        rows = [{"action":"buy","change_pct":-5.0,"review_grade":"失效"},
                {"action":"buy","change_pct":-4.0,"review_grade":"失效"},
                {"action":"buy","change_pct":1.0,"review_grade":"待观察"}]
        result = classify_market_regime(rows)
        self.assertEqual(result, "bear")

    def test_high_volatility(self):
        rows = [{"action":"buy","change_pct":10.0,"review_grade":"有效"},
                {"action":"buy","change_pct":-8.0,"review_grade":"失效"},
                {"action":"buy","change_pct":6.0,"review_grade":"有效"}]
        result = classify_market_regime(rows)
        self.assertEqual(result, "high_volatility")

    def test_empty_data(self):
        result = classify_market_regime([])
        self.assertEqual(result, "unknown")

    def test_fewer_than_3(self):
        result = classify_market_regime([{"action":"buy","change_pct":1.0}])
        self.assertEqual(result, "unknown")

    def test_summary_returns_dict(self):
        rows = [{"action":"buy","change_pct":5.0,"review_grade":"有效"},
                {"action":"buy","change_pct":4.0,"review_grade":"有效"},
                {"action":"buy","change_pct":1.0,"review_grade":"待观察"}]
        result = build_market_regime_summary(rows)
        self.assertIn("regime", result)
        self.assertIn("confidence", result)
        self.assertIn("metrics", result)

    def test_summary_metrics_structure(self):
        rows = [{"action":"buy","change_pct":5.0,"review_grade":"有效"},
                {"action":"buy","change_pct":4.0,"review_grade":"有效"},
                {"action":"buy","change_pct":1.0,"review_grade":"待观察"}]
        result = build_market_regime_summary(rows)
        self.assertIn("avg_return", result["metrics"])
        self.assertIn("volatility", result["metrics"])
        self.assertIn("win_rate", result["metrics"])

    def test_summary_empty_no_crash(self):
        result = build_market_regime_summary([])
        self.assertEqual(result["regime"], "unknown")


if __name__ == "__main__":
    unittest.main()