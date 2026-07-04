# -*- coding: utf-8 -*-
"""策略统计测试 — build_strategy_summary 的只读测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from northstar.data.recommendation_review import build_strategy_summary, classify_recommendation_review_result


def _make_row(action: str, price: float = 100.0, current_price: float = 100.0) -> dict:
    row = {"action": action, "symbol": "NVDA", "price": price, "current_price": current_price,
           "change_pct": round((current_price - price) / price * 100, 2)}
    grade = classify_recommendation_review_result(row)
    row["review_grade"] = grade["review_grade"]
    return row


class TestBuildStrategySummary(unittest.TestCase):
    """build_strategy_summary 单元测试"""

    def test_momentum_win_classification(self):
        # buy + 5% → momentum + 有效
        rows = [_make_row("buy", 100, 105)]
        result = build_strategy_summary(rows)
        self.assertIn("momentum", result["strategies"])
        self.assertEqual(result["strategies"]["momentum"]["win_count"], 1)

    def test_defensive_classification(self):
        # sell + 全部 → defensive
        rows = [_make_row("sell", 100, 95)]
        result = build_strategy_summary(rows)
        self.assertIn("defensive", result["strategies"])

    def test_top_strategy_exists(self):
        rows = [
            _make_row("buy", 100, 105),  # momentum
            _make_row("buy", 100, 95),   # mean_reversion 失效
            _make_row("sell", 100, 105), # reversal 失效
        ]
        result = build_strategy_summary(rows)
        self.assertIn(result["top_strategy"], result["strategies"])

    def test_win_rate_calculation(self):
        rows = [
            _make_row("buy", 100, 105),  # momentum 有效
            _make_row("buy", 100, 105),  # momentum 有效
            _make_row("buy", 100, 95),   # mean_reversion 失效
        ]
        result = build_strategy_summary(rows)
        # momentum: 2 win, 0 loss
        self.assertAlmostEqual(result["strategies"]["momentum"]["win_rate"], 100.0)

    def test_empty_list(self):
        result = build_strategy_summary([])
        self.assertEqual(result["top_strategy"], "unknown")

    def test_unknown_no_crash(self):
        rows = [_make_row("持有", 100, 100)]
        result = build_strategy_summary(rows)
        self.assertIn("unknown", result["strategies"])

    def test_best_and_worst_strategy(self):
        rows = [
            _make_row("buy", 100, 105),  # momentum 有效
            _make_row("sell", 100, 105), # reversal 失效
        ]
        result = build_strategy_summary(rows)
        self.assertIn(result["best_strategy"], ["momentum", "reversal", "defensive", "unknown"])
        self.assertIn(result["worst_strategy"], ["momentum", "reversal", "defensive", "unknown"])

    def test_none_input_no_crash(self):
        result = build_strategy_summary(None)  # type: ignore
        # 空输入应返回 empty dict 和 unknown 缺省值
        self.assertEqual(result.get("top_strategy", ""), "unknown")


if __name__ == "__main__":
    unittest.main()