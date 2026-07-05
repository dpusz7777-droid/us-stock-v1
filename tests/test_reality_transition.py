# -*- coding: utf-8 -*-
"""现实过渡层测试 v3 — RealityTransitionEngine 完整测试。"""

from __future__ import annotations
import sys, unittest, os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.reality_transition.reality_transition_engine import RealityTransitionEngine


class TestRealityTransition(unittest.TestCase):
    def setUp(self):
        self.rte = RealityTransitionEngine()

    def test_mirror_cycle_returns_report(self):
        r = self.rte.run_reality_mirror_cycle()
        self.assertIn("rmai_score", r)
        self.assertIn("dynamic_rmai", r)
        self.assertIn("current_regime", r)
        self.assertIn("regime_confidence", r)

    def test_regime_detection(self):
        """市场状态检测应返回有效 regime"""
        data = {"returns": [0.2, 0.3, 0.15, 0.25, 0.1], "volatility": 0.12, "spread_proxy": 0.001, "drawdown_pct": 0.02}
        r = self.rte.market_regime_detector(data)
        self.assertIn(r["regime_type"], ["trend", "range", "volatile", "liquidity_stress"])
        self.assertGreaterEqual(r["confidence"], 0.0)
        self.assertLessEqual(r["confidence"], 1.0)

    def test_rmai_dynamic_adjustment(self):
        """动态RMAI应根据regime调整"""
        trend = self.rte.compute_dynamic_rmai(90, "trend")
        range_r = self.rte.compute_dynamic_rmai(90, "range")
        volatile = self.rte.compute_dynamic_rmai(90, "volatile")
        stress = self.rte.compute_dynamic_rmai(90, "liquidity_stress")
        self.assertGreater(trend["dynamic_rmai"], stress["dynamic_rmai"])
        self.assertGreater(range_r["dynamic_rmai"], volatile["dynamic_rmai"])

    def test_liquidity_stress_blocks_go(self):
        """liquidity_stress应阻止GO"""
        self.rte._consecutive_breakdown_days = 0
        r = self.rte.capital_deployment_readiness_engine({"score": 90}, {"breakdown_detected": False}, regime="liquidity_stress", regime_confidence=0.8)
        self.assertEqual(r["status"], "NO_GO")

    def test_trend_regime_allows_conditional(self):
        """trend regime下高RMAI应允许GO"""
        self.rte._consecutive_breakdown_days = 0
        r = self.rte.capital_deployment_readiness_engine({"score": 88}, {"breakdown_detected": False}, regime="trend", regime_confidence=0.7)
        self.assertEqual(r["status"], "GO")

    def test_micro_live_feedback_updates_rmai(self):
        """micro_live反馈应更新RMAI"""
        self.rte._rmai_history = [85.0]
        m = self.rte.micro_live_cycle(2.0)
        self.assertIn("rmai_corrected", m)
        self.assertIn("pnl_alignment", m)

    def test_stress_test_returns_keys(self):
        s = self.rte.stress_test_mode({"live_return": 2.0}, {"shadow_return": 1.8}, {"paper_return": 2.5})
        self.assertIn("rmai_volatility", s)

    def test_walk_forward_returns_keys(self):
        w = self.rte.walk_forward_validation({"live_return": 2.0}, {"shadow_return": 1.8}, {"paper_return": 2.5})
        self.assertIn("stability_score", w)

    def test_kill_switch_triggers(self):
        self.rte.trigger_kill_switch(5.0)
        self.assertTrue(self.rte._kill_switch_active)

    def test_file_output(self):
        today = __import__("datetime").date.today().isoformat().replace("-", "")
        f = Path(__file__).parent.parent / "reports" / f"reality_transition_{today}.json"
        if f.exists(): os.unlink(f)
        self.rte.run_reality_mirror_cycle()
        self.assertTrue(f.exists())


if __name__ == "__main__":
    unittest.main()