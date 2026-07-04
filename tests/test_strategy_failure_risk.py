# -*- coding: utf-8 -*-
"""策略失效预警测试 — build_strategy_failure_risk_summary 的只读测试。"""

from __future__ import annotations
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.data.recommendation_review import build_strategy_failure_risk_summary, build_strategy_failure_warning


class TestStrategyFailureRisk(unittest.TestCase):
    def test_empty_no_crash(self):
        r = build_strategy_failure_risk_summary([])
        self.assertIn("strategy_failure_risk", r)

    def test_risk_score_in_range(self):
        rows = [{"action":"buy","change_pct":5.0,"review_grade":"有效"} for _ in range(6)]
        r = build_strategy_failure_risk_summary(rows)
        for st, data in r["strategy_failure_risk"].items():
            self.assertGreaterEqual(data["risk_score"], 0.0)
            self.assertLessEqual(data["risk_score"], 1.0)

    def test_has_risk_fields(self):
        rows = [{"action":"buy","change_pct":5.0,"review_grade":"有效"} for _ in range(6)]
        r = build_strategy_failure_risk_summary(rows)
        for st, data in r["strategy_failure_risk"].items():
            self.assertIn("recent_win_rate", data)
            self.assertIn("historical_win_rate", data)
            self.assertIn("degradation", data)
            self.assertIn("risk_score", data)

    def test_warning_returns_dict(self):
        rows = [{"action":"buy","change_pct":5.0,"review_grade":"有效"} for _ in range(6)]
        w = build_strategy_failure_warning(rows)
        self.assertIn("warning_level", w)
        self.assertIn("system_status", w)
        self.assertIn("affected_strategies", w)

    def test_warning_empty_no_crash(self):
        w = build_strategy_failure_warning([])
        self.assertIn(w["system_status"], ["insufficient_data", "stable", "watch", "degrading"])

    def test_high_risk_listed(self):
        # 构造 degraded 数据：前半段都有效，后半段都失效
        rows_hist = [{"action":"buy","change_pct":5.0,"review_grade":"有效"} for _ in range(4)]
        rows_recent = [{"action":"buy","change_pct":-5.0,"review_grade":"失效"} for _ in range(4)]
        rows = rows_hist + rows_recent
        r = build_strategy_failure_risk_summary(rows)
        self.assertIsInstance(r["high_risk_strategies"], list)

    def test_missing_field_no_crash(self):
        rows = [{} for _ in range(6)]
        r = build_strategy_failure_risk_summary(rows)
        self.assertIn("strategy_failure_risk", r)


if __name__ == "__main__":
    unittest.main()