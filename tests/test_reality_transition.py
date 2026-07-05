# -*- coding: utf-8 -*-
"""现实过渡层测试 v11 — RealityTransitionEngine SLTS 完整测试。"""

from __future__ import annotations
import sys, unittest, os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.reality_transition.reality_transition_engine import (
    RealityTransitionEngine,
    BrokerAdapter,
    ExecutionBiasModel,
)


class TestRealityTransition(unittest.TestCase):
    def setUp(self):
        self.rte = RealityTransitionEngine()

    def test_mirror_cycle_returns_report(self):
        r = self.rte.run_reality_mirror_cycle()
        self.assertIn("mode", r)
        self.assertIn("execution_divergence_score", r)
        self.assertIn("live_readiness_score", r)
        self.assertIn("live_allowed", r)
        self.assertIn("broker_adapter_status", r)
        self.assertIn("slippage_bias", r)

    def test_shadow_vs_live_divergence_detection(self):
        """shadow vs live 偏差检测应返回结构"""
        shadow = dict(slippage_cost=10.0, pnl_realized=50.0, execution_efficiency=90.0)
        live_sim = dict(slippage_cost=12.0, pnl_realized=48.0, execution_efficiency=85.0)
        d = self.rte.compute_market_divergence(shadow, live_sim)
        self.assertIn("execution_divergence_score", d)
        self.assertIn("fill_divergence", d)
        self.assertIn("slippage_divergence", d)
        self.assertIn("pnl_divergence", d)

    def test_live_mode_blocked_when_risk_high(self):
        """高风险时应阻止 live 模式"""
        self.rte._kill_switch_active = True
        d = dict(execution_divergence_score=50, pnl_divergence=10, slippage_divergence=30)
        r = self.rte._live_risk_gate(d, dict(regime_type="trend"))
        self.assertFalse(r["live_allowed"])

    def test_broker_adapter_interface(self):
        """BrokerAdapter 应提供标准接口"""
        ba = BrokerAdapter()
        o = ba.submit_order("NVDA", 100, 800.0)
        self.assertEqual(o["status"], "submitted")
        self.assertTrue(ba.cancel_order(o["order_id"]))
        self.assertEqual(len(ba.fetch_fills()), 0)
        self.assertGreater(len(ba.fetch_positions()), 0)

    def test_execution_bias_learning(self):
        """EMA 偏差模型应学习"""
        ebm = ExecutionBiasModel(alpha=0.3)
        ebm.update(0.1)
        ebm.update(0.2)
        self.assertAlmostEqual(ebm.bias, 0.2 * 0.3 + 0.1 * 0.7 * 0.3, places=3)

    def test_auto_fallback_to_shadow(self):
        """divergence 高时应 fallback 到 shadow"""
        d = dict(execution_divergence_score=40, pnl_divergence=15, slippage_divergence=25)
        r = self.rte._live_risk_gate(d, dict(regime_type="trend"))
        self.assertFalse(r["live_allowed"])

    def test_liquidity_stress_blocks_live(self):
        """liquidity_stress 应阻止 live"""
        d = dict(execution_divergence_score=90, pnl_divergence=2, slippage_divergence=10)
        r = self.rte._live_risk_gate(d, dict(regime_type="liquidity_stress"))
        self.assertFalse(r["live_allowed"])

    def test_set_mode(self):
        """set_mode 应更改模式"""
        self.rte.set_mode("live_shadow")
        self.assertEqual(self.rte.mode, "live_shadow")

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