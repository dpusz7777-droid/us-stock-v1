# -*- coding: utf-8 -*-
"""建议失效原因归类测试 — classify_recommendation_failure_reason 的只读测试。

测试目标：
    验证 classify_recommendation_failure_reason 的返回值。

安全原则：
    - 所有测试使用内存数据，不依赖任何文件
    - 不修改任何数据
    - 不联网、不获取实时价格
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from northstar.data.recommendation_review import classify_recommendation_failure_reason


class TestClassifyFailureReason(unittest.TestCase):
    """classify_recommendation_failure_reason 单元测试"""

    # ── A. 非失效建议 → severity=无 ──
    def test_non_failure_should_return_none_severity(self):
        row = {"review_grade": "有效", "action": "buy", "symbol": "NVDA", "price": 100, "current_price": 105, "change_pct": 5.0}
        result = classify_recommendation_failure_reason(row)
        self.assertEqual(result["failure_reason"], "非失效建议")
        self.assertEqual(result["failure_severity"], "无")

    # ── B. 买入类失效 -4% → 买入后下跌 / 低 ──
    def test_buy_failure_neg4_should_be_low(self):
        row = {"review_grade": "失效", "action": "buy", "symbol": "NVDA", "price": 100, "current_price": 96, "change_pct": -4.0}
        result = classify_recommendation_failure_reason(row)
        self.assertEqual(result["failure_reason"], "买入后下跌")
        self.assertEqual(result["failure_severity"], "低")

    # ── C. 买入类失效 -7% → 买入后下跌 / 中 ──
    def test_buy_failure_neg7_should_be_medium(self):
        row = {"review_grade": "失效", "action": "buy", "symbol": "NVDA", "price": 100, "current_price": 93, "change_pct": -7.0}
        result = classify_recommendation_failure_reason(row)
        self.assertEqual(result["failure_reason"], "买入后下跌")
        self.assertEqual(result["failure_severity"], "中")

    # ── D. 买入类失效 -12% → 买入后下跌 / 高 ──
    def test_buy_failure_neg12_should_be_high(self):
        row = {"review_grade": "失效", "action": "buy", "symbol": "NVDA", "price": 100, "current_price": 88, "change_pct": -12.0}
        result = classify_recommendation_failure_reason(row)
        self.assertEqual(result["failure_reason"], "买入后下跌")
        self.assertEqual(result["failure_severity"], "高")

    # ── E. 卖出类失效 +4% → 卖出后上涨 / 低 ──
    def test_sell_failure_pos4_should_be_low(self):
        row = {"review_grade": "失效", "action": "sell", "symbol": "NVDA", "price": 100, "current_price": 104, "change_pct": 4.0}
        result = classify_recommendation_failure_reason(row)
        self.assertEqual(result["failure_reason"], "卖出后上涨")
        self.assertEqual(result["failure_severity"], "低")

    # ── F. 卖出类失效 +7% → 卖出后上涨 / 中 ──
    def test_sell_failure_pos7_should_be_medium(self):
        row = {"review_grade": "失效", "action": "sell", "symbol": "NVDA", "price": 100, "current_price": 107, "change_pct": 7.0}
        result = classify_recommendation_failure_reason(row)
        self.assertEqual(result["failure_reason"], "卖出后上涨")
        self.assertEqual(result["failure_severity"], "中")

    # ── G. 卖出类失效 +12% → 卖出后上涨 / 高 ──
    def test_sell_failure_pos12_should_be_high(self):
        row = {"review_grade": "失效", "action": "sell", "symbol": "NVDA", "price": 100, "current_price": 112, "change_pct": 12.0}
        result = classify_recommendation_failure_reason(row)
        self.assertEqual(result["failure_reason"], "卖出后上涨")
        self.assertEqual(result["failure_severity"], "高")

    # ── H. 中文"买入"失效 → 买入后下跌 ──
    def test_chinese_buy_failure_should_be_buy_down(self):
        row = {"review_grade": "失效", "action": "买入", "symbol": "NVDA", "price": 100, "current_price": 95, "change_pct": -5.0}
        result = classify_recommendation_failure_reason(row)
        self.assertEqual(result["failure_reason"], "买入后下跌")
        self.assertEqual(result["failure_severity"], "中")

    # ── I. 中文"减仓"失效 → 卖出后上涨 ──
    def test_chinese_reduce_failure_should_be_sell_up(self):
        row = {"review_grade": "失效", "action": "减仓", "symbol": "NVDA", "price": 100, "current_price": 105, "change_pct": 5.0}
        result = classify_recommendation_failure_reason(row)
        self.assertEqual(result["failure_reason"], "卖出后上涨")
        self.assertEqual(result["failure_severity"], "中")

    # ── J. action 缺失 → 数据不足 ──
    def test_missing_action_should_return_insufficient(self):
        row = {"review_grade": "失效", "action": "", "symbol": "NVDA", "price": 100, "current_price": 95, "change_pct": -5.0}
        result = classify_recommendation_failure_reason(row)
        self.assertEqual(result["failure_reason"], "数据不足导致无法判断")

    # ── K. change_pct 非数字 → 数据不足 ──
    def test_invalid_change_pct_should_return_insufficient(self):
        row = {"review_grade": "失效", "action": "buy", "symbol": "NVDA", "price": 100, "current_price": 95, "change_pct": "not_a_number"}
        result = classify_recommendation_failure_reason(row)
        self.assertEqual(result["failure_reason"], "数据不足导致无法判断")

    # ── L. 未知 action 且失效 → 动作类型无法识别 ──
    def test_unknown_action_should_return_unrecognized(self):
        row = {"review_grade": "失效", "action": "unknown_action_xyz", "symbol": "NVDA", "price": 100, "current_price": 95, "change_pct": -5.0}
        result = classify_recommendation_failure_reason(row)
        self.assertEqual(result["failure_reason"], "动作类型无法识别")

    # ── M. 缺失 current_price → 数据不足 ──
    def test_missing_current_price_should_return_insufficient(self):
        row = {"review_grade": "失效", "action": "buy", "symbol": "NVDA", "price": 100, "current_price": None, "change_pct": -5.0}
        result = classify_recommendation_failure_reason(row)
        self.assertEqual(result["failure_reason"], "数据不足导致无法判断")

    # ── N. 无 review_grade 字段但数据完整 → 按实际数据判断 ──
    def test_no_review_grade_with_buy_failure_should_return_buy_down(self):
        row = {"action": "buy", "symbol": "NVDA", "price": 100, "current_price": 95, "change_pct": -5.0}
        result = classify_recommendation_failure_reason(row)
        # 虽然没有 review_grade 字段，但数据完整，函数能判断是买入后下跌
        self.assertEqual(result["failure_reason"], "买入后下跌")

    # ── O. 缺失 price → 数据不足 ──
    def test_missing_price_should_return_insufficient(self):
        row = {"review_grade": "失效", "action": "buy", "symbol": "NVDA", "price": None, "current_price": 95, "change_pct": -5.0}
        result = classify_recommendation_failure_reason(row)
        self.assertEqual(result["failure_reason"], "数据不足导致无法判断")


if __name__ == "__main__":
    unittest.main()