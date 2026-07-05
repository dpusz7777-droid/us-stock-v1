# -*- coding: utf-8 -*-
"""现实过渡层测试 v4 — RealityTransitionEngine 完整测试。"""

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
        self.assertIn("capital_allocation_pct", r)
        self.assertIn("allocation_action", r)
        self.assertIn("allocation_risk_level", r)
        self.assertIn("risk_adjusted_exposure", r)

    def test_allocation_continuity(self):
        """分配应为连续值 0~100"""
        a = self.rte.compute_capital_allocation_signal(rmai=80, regime="trend", regime_confidence=0.9, stability_score=0.9, drawdown=0.0)
        self.assertGreaterEqual(a["allocation_pct"], 0)
        self.assertLessEqual(a["allocation_pct"], 100)
        self.assertIsInstance(a["allocation_pct"], float)

    def test_liquidity_stress_caps_allocation(self):
        """liquidity_stress 应限制 ≤ 10%"""
        a = self.rte.compute_capital_allocation_signal(rmai=90, regime="liquidity_stress", regime_confidence=0.9, stability_score=0.9, drawdown=0.0)
        self.assertLessEqual(a["allocation_pct"], 10)

    def test_drawdown_reduces_position_size(self):
        """回撤 > 5% 应使 allocation = 0"""
        a_high = self.rte.compute_capital_allocation_signal(rmai=90, regime="trend", regime_confidence=0.9, stability_score=0.9, drawdown=0.0)
        a_low = self.rte.compute_capital_allocation_signal(rmai=90, regime="trend", regime_confidence=0.9, stability_score=0.9, drawdown=0.06)
        self.assertGreater(a_high["allocation_pct"], a_low["allocation_pct"])
        self.assertEqual(a_low["allocation_pct"], 0.0)

    def test_trend_increases_allocation(self):
        """trend 应产生比 volatile 更高的 allocation"""
        trend = self.rte.compute_capital_allocation_signal(rmai=80, regime="trend", regime_confidence=0.8)
        volatile = self.rte.compute_capital_allocation_signal(rmai=80, regime="volatile", regime_confidence=0.8)
        self.assertGreater(trend["allocation_pct"], volatile["allocation_pct"])

    def test_allocation_never_exceeds_100(self):
        """无论输入多大，allocation 不应超过 100%"""
        a = self.rte.compute_capital_allocation_signal(rmai=200, regime="trend", regime_confidence=2.0, stability_score=2.0, drawdown=0.0)
        self.assertLessEqual(a["allocation_pct"], 100)

    def test_regime_detection(self):
        data = {"returns": [0.2, 0.3, 0.15, 0.25, 0.1], "volatility": 0.12, "spread_proxy": 0.001, "drawdown_pct": 0.02}
        r = self.rte.market_regime_detector(data)
        self.assertIn(r["regime_type"], ["trend", "range", "volatile", "liquidity_stress"])

    def test_liquidity_stress_blocks_go(self):
        self.rte._consecutive_breakdown_days = 0
        r = self.rte.capital_deployment_readiness_engine({"score": 90}, {"breakdown_detected": False}, regime="liquidity_stress", regime_confidence=0.8)
        self.assertEqual(r["status"], "NO_GO")

    def test_micro_live_feedback_updates_rmai(self):
        self.rte._rmai_history = [85.0]
        m = self.rte.micro_live_cycle(2.0)
        self.assertIn("rmai_corrected", m)
        self.assertIn("pnl_alignment", m)

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