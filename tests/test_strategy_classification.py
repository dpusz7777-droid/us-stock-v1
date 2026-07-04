# -*- coding: utf-8 -*-
"""策略分类测试 — classify_strategy_type 的只读测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from northstar.data.recommendation_review import classify_strategy_type


class TestClassifyStrategyType(unittest.TestCase):
    """classify_strategy_type 单元测试"""

    def test_buy_up_5pct_momentum(self):
        row = {"action": "buy", "change_pct": 5.0}
        self.assertEqual(classify_strategy_type(row), "momentum")

    def test_buy_down_5pct_mean_reversion(self):
        row = {"action": "buy", "change_pct": -5.0}
        self.assertEqual(classify_strategy_type(row), "mean_reversion")

    def test_sell_up_5pct_reversal(self):
        row = {"action": "sell", "change_pct": 5.0}
        self.assertEqual(classify_strategy_type(row), "reversal")

    def test_sell_down_5pct_defensive(self):
        row = {"action": "sell", "change_pct": -5.0}
        self.assertEqual(classify_strategy_type(row), "defensive")

    def test_breakout_keyword(self):
        row = {"action": "breakout", "change_pct": 2.0}
        self.assertEqual(classify_strategy_type(row), "breakout")

    def test_unknown_action(self):
        row = {"action": "hold", "change_pct": 1.0}
        self.assertEqual(classify_strategy_type(row), "unknown")

    def test_missing_fields_no_crash(self):
        row = {}
        result = classify_strategy_type(row)
        self.assertIn(result, ["unknown", "defensive"])

    def test_chinese_buy_momentum(self):
        row = {"action": "买入", "change_pct": 5.0}
        self.assertEqual(classify_strategy_type(row), "momentum")

    def test_chinese_sell_reversal(self):
        row = {"action": "卖出", "change_pct": 5.0}
        self.assertEqual(classify_strategy_type(row), "reversal")

    def test_new_high_breakout(self):
        row = {"action": "new_high", "change_pct": 2.0}
        self.assertEqual(classify_strategy_type(row), "breakout")

    def test_by_up_1pct_momentum(self):
        row = {"action": "buy", "change_pct": 1.0}
        self.assertEqual(classify_strategy_type(row), "momentum")


if __name__ == "__main__":
    unittest.main()