# -*- coding: utf-8 -*-
"""市场校准测试 — MarketCalibrationEngine 的只读测试。"""

from __future__ import annotations
import sys, unittest, os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.calibration.market_calibration_engine import MarketCalibrationEngine


class TestMarketCalibration(unittest.TestCase):
    def setUp(self):
        self.mce = MarketCalibrationEngine()

    def test_empty_no_crash(self):
        """空数据不崩溃"""
        r = self.mce.calibration_cycle(None, None, None)
        self.assertIn("reality_alignment_score", r)
        self.assertIn("bias_detection", r)

    def test_calibration_returns_all_fields(self):
        """校准返回全部字段"""
        r = self.mce.calibration_cycle({"real_return": 2.0}, {"shadow_return": 1.8}, {"paper_return": 2.5})
        self.assertIn("system_health", r)
        self.assertIn("drift_detected", r)
        self.assertIn("adjustments", r)

    def test_bias_detection_optimism(self):
        """shadow > real 应检测到乐观偏差"""
        b = self.mce.compute_bias_detection(real_return=1.0, shadow_return=5.0, paper_return=3.0)
        self.assertGreater(b["optimism_bias"], 0)

    def test_bias_detection_pessimism(self):
        """shadow < real 应检测到悲观偏差"""
        b = self.mce.compute_bias_detection(real_return=5.0, shadow_return=1.0, paper_return=3.0)
        self.assertLess(b["optimism_bias"], 0)

    def test_alignment_score_in_range(self):
        """一致性评分 0~100"""
        s = self.mce.reality_alignment_score(2.0, 1.8, 2.5)
        self.assertGreaterEqual(s, 0)
        self.assertLessEqual(s, 100)

    def test_high_bias_triggers_adjustment(self):
        """高偏差应触发参数调整"""
        b = {"optimism_bias": 3.0, "execution_bias": 2.0, "timing_bias": 3.0}
        a = self.mce.adjust_model_parameters(b)
        self.assertIn("confidence_multiplier", a)

    def test_drift_detection(self):
        """连续偏差应触发漂移检测"""
        for _ in range(5):
            self.mce.compute_bias_detection(1.0, 5.0, 3.0)
        d = self.mce.drift_correction_engine({"optimism_bias": 4.0})
        self.assertTrue(d["drift_detected"])

    def test_file_output(self):
        """应生成 JSON"""
        today = __import__("datetime").date.today().isoformat().replace("-", "")
        f = Path(__file__).parent.parent / "reports" / f"market_calibration_{today}.json"
        if f.exists(): os.unlink(f)
        self.mce.calibration_cycle()
        self.assertTrue(f.exists())

    def test_system_health_valid(self):
        """系统状态应有效"""
        r = self.mce.calibration_cycle({"real_return": 2.0}, {"shadow_return": 1.8}, {"paper_return": 2.5})
        self.assertIn(r["system_health"], ["calibrated", "needs_recalibration", "misaligned"])


if __name__ == "__main__":
    unittest.main()