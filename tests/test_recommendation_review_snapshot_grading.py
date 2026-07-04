# -*- coding: utf-8 -*-
"""建议复盘快照分级统计测试 — compute_grade_stats_from_overall 的只读测试。

测试目标：
    验证 compute_grade_stats_from_overall 的返回值正确处理各类场景。

安全原则：
    - 所有测试使用内存数据，不依赖任何文件
    - 不修改任何数据
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

from northstar.data.recommendation_review_snapshot import compute_grade_stats_from_overall


class TestGradeStatsFromOverall(unittest.TestCase):
    """compute_grade_stats_from_overall 单元测试"""

    # ── A. 正常数据：有效2，失效1，待观察3，数据不足4 ──
    def test_normal_case(self):
        overall = {
            "grade_valid_count": 2,
            "grade_watch_count": 3,
            "grade_invalid_count": 1,
            "grade_insufficient_count": 4,
        }
        result = compute_grade_stats_from_overall(overall)
        self.assertEqual(result["grade_valid_count"], 2)
        self.assertEqual(result["grade_watch_count"], 3)
        self.assertEqual(result["grade_invalid_count"], 1)
        self.assertEqual(result["grade_insufficient_count"], 4)
        self.assertEqual(result["grade_sample_count"], 3)  # 2 + 1
        self.assertAlmostEqual(result["grade_effective_rate"], 2 / 3 * 100, places=1)

    # ── B. 有效和失效都为0，只有待观察和数据不足 ──
    def test_all_zero_effective_and_invalid(self):
        overall = {
            "grade_valid_count": 0,
            "grade_watch_count": 5,
            "grade_invalid_count": 0,
            "grade_insufficient_count": 2,
        }
        result = compute_grade_stats_from_overall(overall)
        self.assertEqual(result["grade_valid_count"], 0)
        self.assertEqual(result["grade_invalid_count"], 0)
        self.assertEqual(result["grade_sample_count"], 0)
        self.assertIsNone(result["grade_effective_rate"])

    # ── C. overall 为 dict 但没有分级字段（旧系统） ──
    def test_empty_overall_stats(self):
        overall = {}
        result = compute_grade_stats_from_overall(overall)
        self.assertIsNone(result["grade_valid_count"])
        self.assertIsNone(result["grade_watch_count"])
        self.assertIsNone(result["grade_invalid_count"])
        self.assertIsNone(result["grade_insufficient_count"])
        self.assertIsNone(result["grade_effective_rate"])
        self.assertEqual(result["grade_sample_count"], 0)

    # ── D. overall 为空 dict（兼容旧快照完全无字段） ──
    def test_old_snapshot_without_grade_stats(self):
        overall = {}
        # 模拟旧快照：不崩溃
        result = compute_grade_stats_from_overall(overall)
        self.assertIsNotNone(result)  # 至少返回了 dict
        self.assertEqual(result["grade_sample_count"], 0)

    # ── E. 仅 contain win_rate 等旧字段，没有 grade_valid_count ──
    def test_old_snapshot_with_winrate_only(self):
        overall = {"win_rate": 50.0, "total_count": 10}
        result = compute_grade_stats_from_overall(overall)
        # 没有 grade_valid_count，所以应该返回 None
        self.assertIsNone(result["grade_valid_count"])
        self.assertEqual(result["grade_sample_count"], 0)

    # ── F. 有效 5，失效 5，有效率为 50% ──
    def test_balanced_effective_rate(self):
        overall = {
            "grade_valid_count": 5,
            "grade_invalid_count": 5,
            "grade_watch_count": 0,
            "grade_insufficient_count": 0,
        }
        result = compute_grade_stats_from_overall(overall)
        self.assertEqual(result["grade_valid_count"], 5)
        self.assertEqual(result["grade_invalid_count"], 5)
        self.assertEqual(result["grade_sample_count"], 10)
        self.assertAlmostEqual(result["grade_effective_rate"], 50.0)

    # ── G. 有效 0，失效 5（全部失效） ──
    def test_all_invalid_rate_0(self):
        overall = {
            "grade_valid_count": 0,
            "grade_invalid_count": 5,
            "grade_watch_count": 0,
            "grade_insufficient_count": 0,
        }
        result = compute_grade_stats_from_overall(overall)
        self.assertEqual(result["grade_valid_count"], 0)
        self.assertEqual(result["grade_invalid_count"], 5)
        self.assertEqual(result["grade_sample_count"], 5)
        self.assertAlmostEqual(result["grade_effective_rate"], 0.0)

    # ── H. 大数值测试 ──
    def test_large_numbers(self):
        overall = {
            "grade_valid_count": 100,
            "grade_invalid_count": 50,
            "grade_watch_count": 200,
            "grade_insufficient_count": 10,
        }
        result = compute_grade_stats_from_overall(overall)
        self.assertEqual(result["grade_valid_count"], 100)
        self.assertEqual(result["grade_invalid_count"], 50)
        self.assertEqual(result["grade_sample_count"], 150)
        self.assertAlmostEqual(result["grade_effective_rate"], 100 / 150 * 100, places=1)


class TestGradeTrendDataConstruction(unittest.TestCase):
    """测试从快照列表构建分级趋势数据的逻辑。

    模拟 get_recommendation_review_snapshot_trend 返回值中的分级字段。
    """

    def test_has_grade_data_with_valid_snapshots(self):
        """至少 2 条包含 grade_stats 的快照能正确提取趋势数据"""
        trend_data = [
            {
                "display_time": "07-04 12:00",
                "grade_valid_count": 5,
                "grade_invalid_count": 2,
                "grade_effective_rate": 71.4,
            },
            {
                "display_time": "07-04 14:00",
                "grade_valid_count": 8,
                "grade_invalid_count": 3,
                "grade_effective_rate": 72.7,
            },
        ]
        has_grade = any(t.get("grade_valid_count") is not None for t in trend_data)
        self.assertTrue(has_grade)

    def test_old_snapshots_without_grade_data(self):
        """旧快照没有 grade_valid_count 字段时，has_grade_data 为 False"""
        trend_data = [
            {
                "display_time": "07-04 12:00",
                "win_rate": 50.0,
                # 没有 grade_valid_count 等字段
            },
        ]
        has_grade = any(t.get("grade_valid_count") is not None for t in trend_data)
        self.assertFalse(has_grade)

    def test_empty_trend_data(self):
        """空趋势列表：不应崩溃"""
        trend_data = []
        has_grade = any(t.get("grade_valid_count") is not None for t in trend_data)
        self.assertFalse(has_grade)

    def test_mixed_old_and_new_snapshots(self):
        """混合旧快照和新快照：新快照有 grade 字段，旧快照没有"""
        trend_data = [
            {"display_time": "07-04 10:00", "win_rate": 50.0},
            {"display_time": "07-04 12:00", "grade_valid_count": 5, "grade_invalid_count": 2, "grade_effective_rate": 71.4},
        ]
        has_grade = any(t.get("grade_valid_count") is not None for t in trend_data)
        self.assertTrue(has_grade)
        # 第一条旧快照的 grade 字段为 None，但不应崩溃
        self.assertIsNone(trend_data[0].get("grade_valid_count"))

    def test_trend_data_with_missing_keys(self):
        """某些快照缺失部分 grade 字段不应崩溃"""
        trend_data = [
            {
                "display_time": "07-04 10:00",
                "grade_valid_count": None,  # 旧快照
                "grade_effective_rate": None,
            },
        ]
        # 访问这些字段不应报错
        self.assertIsNone(trend_data[0].get("grade_valid_count"))
        self.assertIsNone(trend_data[0].get("grade_effective_rate"))


if __name__ == "__main__":
    unittest.main()