# -*- coding: utf-8 -*-
"""现实过渡层测试 v13 — RealityTransitionEngine LTTP 完整测试。"""

from __future__ import annotations
import sys, unittest, os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.reality_transition.reality_transition_engine import (
    RealityTransitionEngine, BrokerAdapter, LiveBrokerAdapter, ExecutionBiasModel,
)


class TestRealityTransition(unittest.TestCase):
    def setUp(self):
        self.rte = RealityTransitionEngine()

    def test_mirror_cycle_returns_report(self):
        r = self.rte.run_reality_mirror_cycle()
        self.assertIn("live_mode", r)
        self.assertIn("pre_flight_check", r)
        self.assertIn("capital_exposure", r)
        self.assertIn("execution_status", r)
        self.assertIn("pnl_deviation", r)
        self.assertIn("broker_status", r)

    def test_pre_live_check_blocks_unsafe_start(self):
        """不安全状态应阻止实盘"""
        self.rte._tier = 0
        r = self.rte.pre_live_check()
        self.assertFalse(r["all_clear"])
        self.assertGreater(len(r["blocked_reasons"]), 0)

    def test_pre_live_check_allows_safe_start(self):
        """安全状态应允许实盘"""
        self.rte._tier = 1
        self.rte._divergence_history = [95]
        self.rte._execution_bias.bias = 0.01
        self.rte._kill_switch_active = False
        self.rte._live_broker.status = "ready"
        r = self.rte.pre_live_check()
        self.assertTrue(r["all_clear"])

    def test_capital_limit_enforced_1_percent(self):
        """capital_exposure 应为 1% 当 micro_live_real_capital"""
        self.rte._live_mode = "micro_live_real_capital"
        r = self.rte.run_reality_mirror_cycle()
        # capital_exposure is derived from live_mode in result dict
        self.assertEqual(r["capital_exposure"], 0.01)

    def test_live_protection_fallback(self):
        """保护引擎应在高偏差时 fallback"""
        r = self.rte.live_protection_engine(dict(drawdown=0.03, divergence=30, slippage=0.005, regime="trend"))
        self.assertEqual(r["action"], "fallback_to_shadow")

    def test_live_protection_all_clear(self):
        """正常状态不应触发保护"""
        r = self.rte.live_protection_engine(dict(drawdown=0.01, divergence=10, slippage=0.0005, regime="trend"))
        self.assertEqual(r["action"], "none")

    def test_broker_adapter_live_execution(self):
        """LiveBrokerAdapter 应支持实盘方法"""
        ba = LiveBrokerAdapter()
        o = ba.submit_live_order("NVDA", 100, 800.0)
        self.assertEqual(o["order_id"], 1)
        filled = ba.confirm_fill(1)
        self.assertEqual(filled["status"], "filled")
        pnl = ba.fetch_real_pnl()
        self.assertIn("realized_pnl", pnl)
        self.assertIn("unrealized_pnl", pnl)

    def test_live_loss_triggers_shutdown(self):
        """大亏损应触发 shutdown"""
        self.rte._total_pnl = -60
        self.rte._divergence_history = [95]
        r = self.rte.run_reality_mirror_cycle()
        self.assertEqual(r["live_mode"], "shadow_only")

    def test_set_live_mode(self):
        self.rte.set_live_mode("micro_live_real_capital")
        self.assertEqual(self.rte._live_mode, "micro_live_real_capital")

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