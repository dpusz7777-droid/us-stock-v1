# -*- coding: utf-8 -*-
"""现实过渡层测试 v2 — RealityTransitionEngine 完整测试。"""

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
        self.assertIn("capital_readiness", r)
        self.assertIn("breakdown_detected", r)
        self.assertIn("stress_test", r)
        self.assertIn("walk_forward", r)
        self.assertIn("micro_live_sandbox", r)

    def test_rmai_in_range(self):
        rmai = self.rte.compute_reality_alignment_index(2.0, 1.8, 2.5)
        self.assertGreaterEqual(rmai["score"], 0)
        self.assertLessEqual(rmai["score"], 100)

    def test_breakdown_detected_on_large_deviation(self):
        b = self.rte.detect_reality_breakdown(2.0, -3.0, 4.0)
        self.assertTrue(b["breakdown_detected"])

    def test_high_rmai_go_readiness(self):
        self.rte._consecutive_breakdown_days = 0
        rmai = {"score": 90}
        breakdown = {"breakdown_detected": False}
        r = self.rte.capital_deployment_readiness_engine(rmai, breakdown)
        self.assertEqual(r["status"], "GO")

    def test_stress_test_returns_keys(self):
        s = self.rte.stress_test_mode({"live_return": 2.0}, {"shadow_return": 1.8}, {"paper_return": 2.5})
        for key in ("rmai_volatility", "breakdown_trigger_frequency", "false_go_rate", "false_no_go_rate"):
            self.assertIn(key, s)

    def test_walk_forward_returns_keys(self):
        w = self.rte.walk_forward_validation({"live_return": 2.0}, {"shadow_return": 1.8}, {"paper_return": 2.5})
        for key in ("stability_score", "regime_sensitivity", "windows_analyzed"):
            self.assertIn(key, w)

    def test_micro_live_cycle_returns_keys(self):
        m = self.rte.micro_live_cycle(2.0)
        for key in ("action", "execution_price", "slippage_pct", "pnl", "rmai_corrected"):
            self.assertIn(key, m)

    def test_kill_switch_triggers(self):
        self.rte.trigger_kill_switch(5.0)
        self.assertTrue(self.rte._kill_switch_active)

    def test_kill_switch_blocks_go(self):
        self.rte.trigger_kill_switch(5.0)
        rmai = {"score": 90}
        r = self.rte.capital_deployment_readiness_engine(rmai, {"breakdown_detected": False})
        self.assertEqual(r["status"], "NO_GO")

    def test_file_output(self):
        today = __import__("datetime").date.today().isoformat().replace("-", "")
        f = Path(__file__).parent.parent / "reports" / f"reality_transition_{today}.json"
        if f.exists(): os.unlink(f)
        self.rte.run_reality_mirror_cycle()
        self.assertTrue(f.exists())


if __name__ == "__main__":
    unittest.main()