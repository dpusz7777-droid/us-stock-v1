# -*- coding: utf-8 -*-
"""现实过渡层测试 v6 — RealityTransitionEngine UOK 完整测试。"""

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
        self.assertIn("optimized_weights", r)
        self.assertIn("objective_value", r)
        self.assertIn("expected_risk", r)
        self.assertIn("expected_return_proxy", r)
        self.assertIn("constraint_shadow_prices", r)
        self.assertIn("solver_status", r)

    def test_unified_solver_optimality(self):
        """求解器应返回合理的目标值"""
        r = self.rte.unified_optimization_kernel(RMAI=80, regime="trend", volatility=0.12, drawdown=0.03, signal_strength=0.8)
        self.assertGreater(r["objective_value"], -1000)
        self.assertIn(r["solver_status"], ["optimal", "feasible", "infeasible"])

    def test_constraint_satisfaction_all(self):
        """所有约束应被满足"""
        r = self.rte.unified_optimization_kernel(RMAI=95, regime="trend", volatility=0.30, drawdown=0.08, signal_strength=0.9)
        w = r["optimized_weights"][0]
        self.assertLessEqual(w, 1.0)
        self.assertGreaterEqual(w, 0.0)
        # volatility constraint
        self.assertLessEqual(0.30 * w, 0.10 + 0.01)
        # drawdown > 5% → w should be 0
        self.assertEqual(w, 0.0)

    def test_liquidity_stress_hard_constraint(self):
        """liquidity_stress 应强制 w ≤ 0.1"""
        r = self.rte.unified_optimization_kernel(RMAI=90, regime="liquidity_stress", volatility=0.15, drawdown=0.02, signal_strength=0.8)
        self.assertLessEqual(r["optimized_weights"][0], 0.1)

    def test_volatility_budget_respected(self):
        """波动率约束应被尊重"""
        r = self.rte.unified_optimization_kernel(RMAI=90, regime="trend", volatility=0.50, drawdown=0.01, signal_strength=0.9)
        w = r["optimized_weights"][0]
        self.assertLessEqual(0.50 * w, 0.10 + 0.01)

    def test_solver_replaces_heuristics(self):
        """求解器输出结构应替代旧heuristic字段"""
        r = self.rte.run_reality_mirror_cycle()
        self.assertNotIn("allocation_pct", r)  # v5 old key
        self.assertIn("optimized_weights", r)
        self.assertIn("solver_status", r)

    def test_regime_detection(self):
        data = {"returns": [0.2, 0.3, 0.15, 0.25, 0.1], "volatility": 0.12, "spread_proxy": 0.001, "drawdown_pct": 0.02}
        r = self.rte.market_regime_detector(data)
        self.assertIn(r["regime_type"], ["trend", "range", "volatile", "liquidity_stress"])

    def test_liquidity_stress_blocks_go(self):
        self.rte._consecutive_breakdown_days = 0
        r = self.rte.capital_deployment_readiness_engine({"score": 90}, {"breakdown_detected": False}, regime="liquidity_stress", regime_confidence=0.8)
        self.assertEqual(r["status"], "NO_GO")

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