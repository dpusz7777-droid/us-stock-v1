# -*- coding: utf-8 -*-
"""建议复盘质量解释测试 — build_recommendation_review_quality_explanation 的只读测试。

测试目标：
    验证 build_recommendation_review_quality_explanation 的返回值。

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

from northstar.data.recommendation_review import (
    build_recommendation_review_quality_explanation,
    classify_recommendation_review_result,
)


def _make_row(action: str, price: float = 100.0, current_price: float = 100.0, change_pct: float = 0.0) -> dict:
    """构造一条带分级标签的模拟复盘行。"""
    row = {
        "action": action,
        "symbol": "NVDA",
        "price": price,
        "current_price": current_price,
        "change_pct": change_pct,
    }
    grade = classify_recommendation_review_result(row)
    row["review_grade"] = grade["review_grade"]
    return row


def _make_insufficient_row() -> dict:
    """构造一条数据不足的行（缺少 price 和 current_price）。"""
    row = {
        "action": "buy",
        "symbol": "NVDA",
        "price": None,
        "current_price": None,
        "change_pct": None,
    }
    grade = classify_recommendation_review_result(row)
    row["review_grade"] = grade["review_grade"]
    return row


class TestBuildQualityExplanation(unittest.TestCase):
    """build_recommendation_review_quality_explanation 单元测试"""

    # ── A. 空列表 → 暂无足够样本 ──
    def test_empty_list_should_be_insufficient(self):
        result = build_recommendation_review_quality_explanation([])
        self.assertEqual(result["quality_level"], "暂无足够样本")
        self.assertIn("暂无建议记录", result["main_issue"])

    # ── B. 数据不足占比 >= 50% → 较差 ──
    def test_high_insufficient_ratio_should_be_poor(self):
        rows = [
            _make_insufficient_row(),  # 数据不足
            _make_insufficient_row(),  # 数据不足
            _make_insufficient_row(),  # 数据不足
            _make_row("buy", 100, 105, 5.0),   # 有效
        ]
        result = build_recommendation_review_quality_explanation(rows)
        self.assertEqual(result["quality_level"], "较差")
        self.assertIn("数据不足", result["main_issue"])

    # ── C. 有效+失效 样本数 < 3 → 一般 ──
    def test_few_effective_samples_should_be_general(self):
        rows = [
            _make_row("buy", 100, 105, 5.0),  # 有效
            _make_row("持有", 100, 105, 5.0),  # 待观察
        ]
        result = build_recommendation_review_quality_explanation(rows)
        self.assertEqual(result["quality_level"], "一般")
        self.assertIn("可判断样本", result["main_issue"])

    # ── D. 失效数量 > 有效数量 → 一般 ──
    def test_more_invalid_than_valid_should_be_general(self):
        rows = [
            _make_row("buy", 100, 95, -5.0),   # 失效
            _make_row("buy", 100, 95, -5.0),   # 失效
            _make_row("buy", 100, 105, 5.0),   # 有效
            _make_row("持有", 100, 105, 5.0),  # 待观察
        ]
        result = build_recommendation_review_quality_explanation(rows)
        self.assertEqual(result["quality_level"], "一般")
        self.assertIn("失效建议多于有效建议", result["main_issue"])

    # ── E. 有效率 >= 60% 且 样本数 >= 3 → 良好 ──
    def test_good_effective_rate_should_be_good(self):
        rows = [
            _make_row("buy", 100, 105, 5.0),   # 有效
            _make_row("buy", 100, 105, 5.0),   # 有效
            _make_row("buy", 100, 105, 5.0),   # 有效
            _make_row("buy", 100, 95, -5.0),   # 失效
            _make_row("持有", 100, 105, 5.0),  # 待观察
        ]
        result = build_recommendation_review_quality_explanation(rows)
        self.assertEqual(result["quality_level"], "良好")
        self.assertIn("暂无明显问题", result["main_issue"])

    # ── F. 缺少 review_grade 字段时不崩溃 ──
    def test_missing_review_grade_should_not_crash(self):
        rows = [
            {"action": "buy", "symbol": "NVDA", "price": 100, "current_price": 105, "change_pct": 5.0},
            # 没有 review_grade 字段
        ]
        result = build_recommendation_review_quality_explanation(rows)
        self.assertIn(result["quality_level"], ["良好", "一般", "较差", "暂无足够样本"])

    # ── G. 中文分级标签能识别 ──
    def test_chinese_grade_tags_should_be_recognized(self):
        rows = [
            {"action": "买入", "symbol": "NVDA", "price": 100, "current_price": 105, "change_pct": 5.0, "review_grade": "有效"},
            {"action": "买入", "symbol": "NVDA", "price": 100, "current_price": 105, "change_pct": 5.0, "review_grade": "有效"},
            {"action": "买入", "symbol": "NVDA", "price": 100, "current_price": 105, "change_pct": 5.0, "review_grade": "有效"},
            {"action": "买入", "symbol": "NVDA", "price": 100, "current_price": 95, "change_pct": -5.0, "review_grade": "失效"},
        ]
        result = build_recommendation_review_quality_explanation(rows)
        self.assertEqual(result["quality_level"], "良好")

    # ── H. 输入为 None 时应兼容 ──
    def test_none_input_should_not_crash(self):
        result = build_recommendation_review_quality_explanation(None)  # type: ignore
        self.assertIn(result["quality_level"], ["暂无足够样本", "一般", "较差", "良好"])

    # ── I. 有效期率 60% 以下但样本充足 → 一般 ──
    def test_below_60pct_with_enough_samples_should_be_general(self):
        rows = [
            _make_row("buy", 100, 105, 5.0),   # 有效
            _make_row("buy", 100, 95, -5.0),   # 失效
            _make_row("buy", 100, 95, -5.0),   # 失效
            _make_row("持有", 100, 105, 5.0),  # 待观察
        ]
        result = build_recommendation_review_quality_explanation(rows)
        self.assertEqual(result["quality_level"], "一般")
        # 3 条可判断 (1有效+2失效)，失效多于有效
        self.assertIn("失效建议多于有效建议", result["main_issue"])

    # ── J. 刚好等于 3 条且全部有效 → 良好 ──
    def test_exactly_3_all_valid_should_be_good(self):
        rows = [
            _make_row("buy", 100, 105, 5.0),   # 有效
            _make_row("buy", 100, 105, 5.0),   # 有效
            _make_row("buy", 100, 105, 5.0),   # 有效
        ]
        result = build_recommendation_review_quality_explanation(rows)
        self.assertEqual(result["quality_level"], "良好")


if __name__ == "__main__":
    unittest.main()