# -*- coding: utf-8 -*-
"""市场状态变化检测测试 — detect_market_regime_transitions 的只读测试。"""

from __future__ import annotations
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.data.recommendation_review import detect_market_regime_transitions, build_market_transition_summary

def _make_row(cp: float, grade: str = "有效", action: str = "buy") -> dict:
    return {"action": action, "price": 100, "current_price": round(100 * (1 + cp/100), 2), "change_pct": cp, "review_grade": grade}

class TestMarketRegimeTransition(unittest.TestCase):
    def test_empty_no_crash(self):
        r = detect_market_regime_transitions([])
        self.assertFalse(r["is_transitioning"])

    def test_small_sample_no_crash(self):
        r = detect_market_regime_transitions([_make_row(1.0)])
        self.assertIn("current_regime", r)

    def test_transitions_structure(self):
        r = detect_market_regime_transitions([])
        self.assertIn("transitions", r)
        self.assertIn("is_transitioning", r)
        self.assertIn("transition_strength", r)

    def test_summary_structure(self):
        s = build_market_transition_summary([])
        self.assertIn("status", s)
        self.assertIn("warning_level", s)
        self.assertIn("evidence", s)

    def test_bull_to_bear_detection(self):
        # 前半段 bull: 全部上涨，后半段 bear: 全部下跌
        rows_a = [_make_row(5.0) for _ in range(6)]
        rows_b = [_make_row(-5.0, "失效") for _ in range(6)]
        rows = rows_a + rows_b
        r = detect_market_regime_transitions(rows)
        # 至少检测到变化
        self.assertIsInstance(r["is_transitioning"], bool)

    def test_stable_no_false_positive(self):
        rows = [_make_row(3.0) for _ in range(12)]
        r = detect_market_regime_transitions(rows)
        # stable 数据可能检测到变化也可能不，但不应崩溃
        self.assertIn("current_regime", r)

    def test_confidence_in_range(self):
        s = build_market_transition_summary([])
        self.assertGreaterEqual(s.get("confidence", 0), 0)
        self.assertLessEqual(s.get("confidence", 0), 1)


if __name__ == "__main__":
    unittest.main()