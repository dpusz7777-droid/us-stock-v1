# -*- coding: utf-8 -*-
"""策略稳健性测试 — run_robustness_analysis 的只读测试。"""

from __future__ import annotations
import sys, unittest, os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.robustness.robustness_engine import (
    run_robustness_analysis,
    run_regime_test,
    run_universe_test,
    calculate_stability_score,
    calculate_overfitting_score,
    REGIME_PRICE_DATA,
)


class TestRobustnessEngine(unittest.TestCase):
    def test_empty_no_crash(self):
        """空数据不崩溃"""
        r = run_robustness_analysis()
        self.assertIn("regime_performance", r)
        self.assertIn("universe_performance", r)
        self.assertIn("stability_score", r)
        self.assertIn("overfitting_score", r)

    def test_regime_test_has_all_regimes(self):
        """regime_test 应包含三种市场环境"""
        r = run_regime_test(REGIME_PRICE_DATA)
        for regime in ("bull", "bear", "sideways"):
            self.assertIn(regime, r)

    def test_universe_test_has_all_universes(self):
        """universe_test 应包含所有股票池"""
        r = run_universe_test(REGIME_PRICE_DATA)
        for name in ("MEGA_CAP", "AI_ONLY", "SEMI", "DIVERSIFIED"):
            self.assertIn(name, r)

    def test_regime_result_has_keys(self):
        """regime 结果应包含所需字段"""
        r = run_regime_test(REGIME_PRICE_DATA)
        for regime, data in r.items():
            self.assertIn("return_pct", data)
            self.assertIn("win_rate", data)
            self.assertIn("max_drawdown_pct", data)

    def test_stability_score_in_range(self):
        """稳定性评分应在 0~100 之间"""
        r = run_regime_test(REGIME_PRICE_DATA)
        score = calculate_stability_score(r)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_overfitting_score_in_range(self):
        """过拟合评分应在 0~100 之间"""
        r = run_regime_test(REGIME_PRICE_DATA)
        score = calculate_overfitting_score(r)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_best_worst_regime(self):
        """best/worst regime 应正确输出"""
        r = run_robustness_analysis()
        self.assertIn(r["best_regime"], ["bull", "bear", "sideways", "unknown"])
        self.assertIn(r["worst_regime"], ["bull", "bear", "sideways", "unknown"])

    def test_file_output(self):
        """应生成 JSON 文件"""
        today = __import__("datetime").date.today().isoformat().replace("-", "")
        report_file = Path(__file__).parent.parent / "reports" / f"robustness_report_{today}.json"
        if report_file.exists():
            os.unlink(report_file)
        r = run_robustness_analysis()
        self.assertTrue(report_file.exists())

    def test_stability_overfitting_not_both_high(self):
        """stability 高时 overfitting 不应也高（逻辑合理性）"""
        r = run_robustness_analysis()
        if r["stability_score"] > 60:
            self.assertLess(r["overfitting_score"], 80)


if __name__ == "__main__":
    unittest.main()