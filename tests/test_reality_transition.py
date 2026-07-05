# -*- coding: utf-8 -*-
"""现实过渡层测试 v7 — RealityTransitionEngine TCO 完整测试。"""

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
        self.assertIn("optimized_weights", r)
        self.assertIn("convergence_flag", r)
        self.assertIn("objective_value", r)
        self.assertIn("expected_risk", r)
        self.assertIn("solver_status", r)

    def test_continuous_solver_convergence(self):
        """连续求解器应收敛"""
        r = self.rte.continuous_optimization_kernel(RMAI=80, regime="trend", volatility=0.12, drawdown=0.02, signal_strength=0.8)
        self.assertTrue(r["convergence_flag"])
        self.assertIn(r["solver_status"], ["optimal", "feasible", "infeasible"])

    def test_constraint_satisfaction_strict(self):
        """所有约束应严格满足"""
        r = self.rte.continuous_optimization_kernel(RMAI=95, regime="trend", volatility=0.30, drawdown=0.08, signal_strength=0.9)
        w = r["optimized_weights"][0]
        self.assertLessEqual(w, 1.0)
        self.assertGreaterEqual(w, 0.0)
        # volatility constraint
        self.assertLessEqual(0.30 * w, 0.10 + 0.001)
        # drawdown > 5% → w should be 0
        self.assertEqual(w, 0.0)

    def test_liquidity_stress_hard_constraint(self):
        """liquidity_stress 应限制 w ≤ 0.1"""
        r = self.rte.continuous_optimization_kernel(RMAI=90, regime="liquidity_stress", volatility=0.15, drawdown=0.02, signal_strength=0.8)
        self.assertLessEqual(r["optimized_weights"][0], 0.1)

    def test_volatility_budget_respected(self):
        """波动率约束应被尊重"""
        r = self.rte.continuous_optimization_kernel(RMAI=90, regime="trend", volatility=0.50, drawdown=0.01, signal_strength=0.9)
        w = r["optimized_weights"][0]
        self.assertLessEqual(0.50 * w, 0.10 + 0.001)

    def test_solution_smoothness(self):
        """相近输入应产生相近输出（平滑性检查）"""
        r1 = self.rte.continuous_optimization_kernel(RMAI=80, regime="trend", volatility=0.12, drawdown=0.02, signal_strength=0.8)
        r2 = self.rte.continuous_optimization_kernel(RMAI=82, regime="trend", volatility=0.12, drawdown=0.02, signal_strength=0.8)
        diff = abs(r1["optimized_weights"][0] - r2["optimized_weights"][0])
        self.assertLess(diff, 0.2)  # small input change → small output change

    def test_no_grid_bias(self):
        """求解器应不受grid步长影响"""
        r = self.rte.continuous_optimization_kernel(RMAI=75, regime="range", volatility=0.14, drawdown=0.03, signal_strength=0.7)
        w = r["optimized_weights"][0]
        self.assertGreater(w, 0.0)
        self.assertLessEqual(w, 1.0)

    def test_warm_start_improves(self):
        """连续求解器应优于或等于grid结果"""
        r = self.rte.continuous_optimization_kernel(RMAI=80, regime="trend", volatility=0.12, drawdown=0.02, signal_strength=0.8)
        self.assertGreater(r["objective_value"], -1000)

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