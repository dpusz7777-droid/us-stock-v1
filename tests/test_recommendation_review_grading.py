# -*- coding: utf-8 -*-
"""建议复盘分级规则测试 — classify_recommendation_review_result 的只读测试。

测试目标：
    验证 classify_recommendation_review_result(row) 的返回值：
    - review_grade: str        有效 / 待观察 / 失效 / 数据不足
    - review_grade_reason: str  一句话原因
    - review_grade_score: int   100 / 60 / 20 / 0

安全原则：
    - 所有测试使用内存数据，不依赖任何文件
    - 不修改建议记录
    - 不联网、不获取实时价格
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from northstar.data.recommendation_review import classify_recommendation_review_result


class TestRecommendationReviewGrading(unittest.TestCase):
    """建议复盘分级规则测试"""

    # ── A. 买入类建议，涨跌幅 +5% → 有效 ──
    def test_buy_up_5pct_should_be_effective(self):
        row = {
            "action": "buy",
            "symbol": "NVDA",
            "price": 100.0,
            "current_price": 105.0,
            "change_pct": 5.0,
        }
        result = classify_recommendation_review_result(row)
        self.assertEqual(result["review_grade"], "有效")
        self.assertEqual(result["review_grade_score"], 100)
        self.assertIn("上涨", result["review_grade_reason"])

    # ── B. 买入类建议，涨跌幅 -5% → 失效 ──
    def test_buy_down_5pct_should_be_invalid(self):
        row = {
            "action": "buy",
            "symbol": "NVDA",
            "price": 100.0,
            "current_price": 95.0,
            "change_pct": -5.0,
        }
        result = classify_recommendation_review_result(row)
        self.assertEqual(result["review_grade"], "失效")
        self.assertEqual(result["review_grade_score"], 20)
        self.assertIn("下跌", result["review_grade_reason"])

    # ── C. 买入类建议，涨跌幅 +1% → 待观察 ──
    def test_buy_up_1pct_should_be_watch(self):
        row = {
            "action": "buy",
            "symbol": "NVDA",
            "price": 100.0,
            "current_price": 101.0,
            "change_pct": 1.0,
        }
        result = classify_recommendation_review_result(row)
        self.assertEqual(result["review_grade"], "待观察")
        self.assertEqual(result["review_grade_score"], 60)
        self.assertIn("±3%", result["review_grade_reason"])

    # ── D. 卖出类建议，涨跌幅 -5% → 有效（下跌=正确） ──
    def test_sell_down_5pct_should_be_effective(self):
        row = {
            "action": "sell",
            "symbol": "NVDA",
            "price": 100.0,
            "current_price": 95.0,
            "change_pct": -5.0,
        }
        result = classify_recommendation_review_result(row)
        self.assertEqual(result["review_grade"], "有效")
        self.assertEqual(result["review_grade_score"], 100)
        self.assertIn("卖出", result["review_grade_reason"])
        self.assertIn("下跌", result["review_grade_reason"])

    # ── E. 卖出类建议，涨跌幅 +5% → 失效（上涨=错误） ──
    def test_sell_up_5pct_should_be_invalid(self):
        row = {
            "action": "sell",
            "symbol": "NVDA",
            "price": 100.0,
            "current_price": 105.0,
            "change_pct": 5.0,
        }
        result = classify_recommendation_review_result(row)
        self.assertEqual(result["review_grade"], "失效")
        self.assertEqual(result["review_grade_score"], 20)
        self.assertIn("卖出", result["review_grade_reason"])
        self.assertIn("上涨", result["review_grade_reason"])

    # ── F. 缺少 current_price → 数据不足 ──
    def test_missing_current_price_should_be_insufficient(self):
        row = {
            "action": "buy",
            "symbol": "NVDA",
            "price": 100.0,
            "current_price": None,
            "change_pct": None,
        }
        result = classify_recommendation_review_result(row)
        self.assertEqual(result["review_grade"], "数据不足")
        self.assertEqual(result["review_grade_score"], 0)
        self.assertIn("缺少当前价格", result["review_grade_reason"])

    # ── G. 缺少 action → 数据不足 ──
    def test_missing_action_should_be_insufficient(self):
        row = {
            "action": "",
            "symbol": "NVDA",
            "price": 100.0,
            "current_price": 105.0,
            "change_pct": 5.0,
        }
        result = classify_recommendation_review_result(row)
        self.assertEqual(result["review_grade"], "数据不足")
        self.assertEqual(result["review_grade_score"], 0)
        self.assertIn("缺少建议动作", result["review_grade_reason"])

    # ── H. 中文动作“买入”，涨跌幅 +5% → 有效 ──
    def test_chinese_buy_up_5pct_should_be_effective(self):
        row = {
            "action": "买入",
            "symbol": "NVDA",
            "price": 100.0,
            "current_price": 105.0,
            "change_pct": 5.0,
        }
        result = classify_recommendation_review_result(row)
        self.assertEqual(result["review_grade"], "有效")
        self.assertEqual(result["review_grade_score"], 100)

    # ── I. 中文动作“减仓”，涨跌幅 -5% → 有效 ──
    def test_chinese_reduce_down_5pct_should_be_effective(self):
        row = {
            "action": "减仓",
            "symbol": "NVDA",
            "price": 100.0,
            "current_price": 95.0,
            "change_pct": -5.0,
        }
        result = classify_recommendation_review_result(row)
        self.assertEqual(result["review_grade"], "有效")
        self.assertEqual(result["review_grade_score"], 100)

    # ── J. 中性动作“持有”，数据完整 → 待观察 ──
    def test_hold_with_complete_data_should_be_watch(self):
        row = {
            "action": "持有",
            "symbol": "NVDA",
            "price": 100.0,
            "current_price": 105.0,
            "change_pct": 5.0,
        }
        result = classify_recommendation_review_result(row)
        self.assertEqual(result["review_grade"], "待观察")
        self.assertEqual(result["review_grade_score"], 60)
        self.assertIn("中性", result["review_grade_reason"])

    # ── K. 缺少 symbol → 数据不足 ──
    def test_missing_symbol_should_be_insufficient(self):
        row = {
            "action": "buy",
            "symbol": "",
            "price": 100.0,
            "current_price": 105.0,
            "change_pct": 5.0,
        }
        result = classify_recommendation_review_result(row)
        self.assertEqual(result["review_grade"], "数据不足")
        self.assertEqual(result["review_grade_score"], 0)
        self.assertIn("缺少股票代码", result["review_grade_reason"])

    # ── L. 缺少 price → 数据不足 ──
    def test_missing_price_should_be_insufficient(self):
        row = {
            "action": "buy",
            "symbol": "NVDA",
            "price": None,
            "current_price": 105.0,
            "change_pct": 5.0,
        }
        result = classify_recommendation_review_result(row)
        self.assertEqual(result["review_grade"], "数据不足")
        self.assertEqual(result["review_grade_score"], 0)
        self.assertIn("缺少建议价格", result["review_grade_reason"])

    # ── M. 卖出类建议，涨跌幅 0%（持平）→ 待观察 ──
    def test_sell_flat_should_be_watch(self):
        row = {
            "action": "sell",
            "symbol": "NVDA",
            "price": 100.0,
            "current_price": 100.0,
            "change_pct": 0.0,
        }
        result = classify_recommendation_review_result(row)
        self.assertEqual(result["review_grade"], "待观察")
        self.assertEqual(result["review_grade_score"], 60)

    # ── N. 英文动作 "add"，涨跌幅 +5% → 有效 ──
    def test_add_up_5pct_should_be_effective(self):
        row = {
            "action": "add",
            "symbol": "NVDA",
            "price": 100.0,
            "current_price": 105.0,
            "change_pct": 5.0,
        }
        result = classify_recommendation_review_result(row)
        self.assertEqual(result["review_grade"], "有效")
        self.assertEqual(result["review_grade_score"], 100)

    # ── O. 英文动作 "avoid"，涨跌幅 -5% → 有效 ──
    def test_avoid_down_5pct_should_be_effective(self):
        row = {
            "action": "avoid",
            "symbol": "NVDA",
            "price": 100.0,
            "current_price": 95.0,
            "change_pct": -5.0,
        }
        result = classify_recommendation_review_result(row)
        self.assertEqual(result["review_grade"], "有效")
        self.assertEqual(result["review_grade_score"], 100)

    # ── P. 缺少 change_pct → 数据不足 ──
    def test_missing_change_pct_should_be_insufficient(self):
        row = {
            "action": "buy",
            "symbol": "NVDA",
            "price": 100.0,
            "current_price": 105.0,
            "change_pct": None,
        }
        result = classify_recommendation_review_result(row)
        self.assertEqual(result["review_grade"], "数据不足")
        self.assertEqual(result["review_grade_score"], 0)
        self.assertIn("缺少涨跌幅", result["review_grade_reason"])

    # ── Q. 异常字段处理（change_pct 不是数字）→ 数据不足 ──
    def test_invalid_change_pct_should_be_insufficient(self):
        row = {
            "action": "buy",
            "symbol": "NVDA",
            "price": 100.0,
            "current_price": 105.0,
            "change_pct": "not_a_number",
        }
        result = classify_recommendation_review_result(row)
        self.assertEqual(result["review_grade"], "数据不足")
        self.assertEqual(result["review_grade_score"], 0)


if __name__ == "__main__":
    unittest.main()