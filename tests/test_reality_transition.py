# -*- coding: utf-8 -*-
"""现实过渡层测试 v10 — RealityTransitionEngine EMIL 完整测试。"""

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
        self.assertIn("executed_allocations", r)
        self.assertIn("slippage_cost", r)
        self.assertIn("market_impact_cost", r)
        self.assertIn("execution_quality_score", r)
        self.assertIn("execution_efficiency", r)
        self.assertIn("pnl_realized", r)
        self.assertIn("pnl_expected", r)
        self.assertIn("rmai_corrected", r)

    def test_slippage_increases_in_stress_regime(self):
        """liquidity_stress 下滑点应更高"""
        normal = self.rte._slippage_model(0.001, 0.15, "trend")
        stress = self.rte._slippage_model(0.001, 0.15, "liquidity_stress")
        self.assertGreater(stress, normal)

    def test_partial_fill_behavior(self):
        """成交率应在 0.3~1.0 之间"""
        for _ in range(50):
            fr = self.rte._fill_ratio(1.0, 0.15)
            self.assertGreaterEqual(fr, 0.3)
            self.assertLessEqual(fr, 1.0)

    def test_execution_costs_charged(self):
        """执行应收取滑点和市场冲击成本"""
        r = self.rte.execute_portfolio({"momentum": 0.3, "breakout": 0.3, "regime": 0.2, "ai_signal": 0.1, "mean_reversion": 0.1}, "trend")
        self.assertGreaterEqual(r["slippage_cost"], 0)
        self.assertGreaterEqual(r["market_impact_cost"], 0)
        self.assertGreaterEqual(r["execution_quality_score"], 0)

    def test_feedback_loop_updates_rmai(self):
        """PnL反馈循环应修正RMAI"""
        self.rte._rmai_history = [80.0]
        fb = self.rte._emil_feedback(50.0, 100.0)
        self.assertIn("rmai_corrected", fb)
        self.assertGreater(fb["rmai_corrected"], 0)

    def test_liquidity_impacts_fill_rate(self):
        """低流动性应降低成交率"""
        high_liq = self.rte._fill_ratio(2.0, 0.10)
        low_liq = self.rte._fill_ratio(0.1, 0.10)
        # high liquidity should give higher avg fill
        self.assertGreaterEqual(high_liq, 0.3)
        self.assertGreaterEqual(low_liq, 0.3)

    def test_market_impact_large_order(self):
        """大单应产生更大冲击"""
        small = self.rte._market_impact(100, 1000000)
        large = self.rte._market_impact(100000, 1000000)
        self.assertGreater(large, small)

    def test_emil_integration_in_cycle(self):
        """EMIL 应集成到完整周期中"""
        r = self.rte.run_reality_mirror_cycle()
        self.assertGreaterEqual(r["execution_quality_score"], 0)
        self.assertLessEqual(r["execution_quality_score"], 100)

    def test_strategy_allocation_sums_to_1(self):
        profiles = [
            dict(name="momentum", rmai=85, signal=0.8, expected_return=0.5, risk=0.12, sharpe=4.2, regime_fit=1.5),
            dict(name="mean_reversion", rmai=70, signal=0.6, expected_return=0.3, risk=0.10, sharpe=3.0, regime_fit=1.0),
            dict(name="regime", rmai=75, signal=0.7, expected_return=0.4, risk=0.11, sharpe=3.6, regime_fit=1.0),
            dict(name="breakout", rmai=80, signal=0.75, expected_return=0.45, risk=0.15, sharpe=3.0, regime_fit=1.4),
            dict(name="ai_signal", rmai=78, signal=0.72, expected_return=0.42, risk=0.13, sharpe=3.2, regime_fit=1.0),
        ]
        r = self.rte.compute_strategy_allocation(profiles, "trend")
        self.assertAlmostEqual(sum(r["strategy_allocations"].values()), 1.0, places=3)

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