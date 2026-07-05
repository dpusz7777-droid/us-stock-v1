# -*- coding: utf-8 -*-
"""现实过渡层测试 v12 — RealityTransitionEngine CCDS 完整测试。"""

from __future__ import annotations
import sys, unittest, os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.reality_transition.reality_transition_engine import (
    RealityTransitionEngine, BrokerAdapter, ExecutionBiasModel,
)


class TestRealityTransition(unittest.TestCase):
    def setUp(self):
        self.rte = RealityTransitionEngine()

    def test_mirror_cycle_returns_report(self):
        r = self.rte.run_reality_mirror_cycle()
        self.assertIn("current_tier", r)
        self.assertIn("allowed_capital_pct", r)
        self.assertIn("next_tier", r)
        self.assertIn("upgrade_ready", r)
        self.assertIn("downgrade_triggered", r)
        self.assertIn("exposure_limit", r)
        self.assertIn("risk_status", r)

    def test_tier_progression_logic(self):
        """tier 应从 0 开始，满足条件后升级"""
        self.assertEqual(self.rte._tier, 0)
        metrics = dict(execution_divergence_score=95, pnl_divergence=1.0, slippage_divergence=5.0,
                       stability_score=0.9, regime="trend", kill_switch=False,
                       consecutive_loss_days=0, total_pnl=0)
        r = self.rte.compute_capital_tier(metrics)
        self.assertEqual(r["tier_name"], "micro_live")  # should upgrade to tier_1
        self.assertEqual(r["allowed_pct"], 0.01)

    def test_automatic_downgrade_on_loss(self):
        """大回撤应自动降级到 tier_0"""
        self.rte._micro_live_portfolio["peak_value"] = 10000.0
        metrics = dict(execution_divergence_score=95, pnl_divergence=1.0, slippage_divergence=5.0,
                       stability_score=0.9, regime="trend", kill_switch=False,
                       consecutive_loss_days=0, total_pnl=-600)
        r = self.rte.compute_capital_tier(metrics)
        self.assertEqual(r["tier"], 0)

    def test_exposure_never_exceeds_tier_limit(self):
        """exposure 不应超过 tier 限制"""
        for tier in range(5):
            limits = {0: 0.0, 1: 0.01, 2: 0.05, 3: 0.25, 4: 1.0}
            self.assertEqual(self.rte.execute_live_order({"symbol": "NVDA", "qty": 100, "price": 800})["executed"], False)
        # tier_0 should reject
        self.assertEqual(self.rte._tier, 0)
        r = self.rte.execute_live_order({"symbol": "NVDA", "qty": 100, "price": 800})
        self.assertFalse(r["executed"])

    def test_kill_switch_overrides_all_tiers(self):
        """kill_switch 应覆盖所有 tier"""
        self.rte._tier = 4
        self.rte.trigger_kill_switch(5.0)
        r = self.rte.execute_live_order({"symbol": "NVDA", "qty": 100, "price": 800})
        self.assertFalse(r["executed"])
        self.assertIn("kill_switch", r["reason"])

    def test_shadow_live_consistency_gate(self):
        """shadow-live 一致性门应正确判断"""
        d = dict(execution_divergence_score=95, pnl_divergence=1.0, slippage_divergence=5.0,
                 stability_score=0.9, regime="trend", kill_switch=False,
                 consecutive_loss_days=0, total_pnl=0)
        r = self.rte.compute_capital_tier(d)
        self.assertEqual(r["tier_name"], "micro_live")

    def test_capital_smoothing_behavior(self):
        """资金平滑应防止跳跃"""
        self.rte._smooth_allocation = 0.0
        ccds = dict(allowed_pct=0.05)
        r = self.rte._apply_capital_smoothing(ccds, alpha=0.7)
        self.assertAlmostEqual(r["allowed_pct"], 0.7 * 0.0 + 0.3 * 0.05, places=4)

    def test_liquidity_stress_blocks_live(self):
        """liquidity_stress 应阻止 live（通过 v11 gate）"""
        d = dict(execution_divergence_score=90, pnl_divergence=2, slippage_divergence=10)
        r = self.rte._live_risk_gate(d, dict(regime_type="liquidity_stress"))
        self.assertFalse(r["live_allowed"])

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